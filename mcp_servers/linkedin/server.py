import os
import logging
import contextlib
import json
import sys
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

import click
from dotenv import load_dotenv
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

# Import shared validation utilities
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from shared.validation import (
    validate_startup_config,
    EnvVarConfig,
    ValidationLevel,
    COMMON_ENV_VARS,
    CredentialValidator
)

from tools import (
    linkedin_token_context,
    get_profile_info,
    create_post,
    format_rich_post,
    create_url_share,
)

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linkedin-mcp-server")

# Define environment variable requirements
LINKEDIN_ENV_VARS = {
    "LINKEDIN_ACCESS_TOKEN": EnvVarConfig(
        name="LINKEDIN_ACCESS_TOKEN",
        description="LinkedIn access token for API authentication",
        validation_level=ValidationLevel.REQUIRED,
        setup_url="https://www.linkedin.com/developers/apps",
        required_permissions=["r_liteprofile", "r_emailaddress", "w_member_social"]
    ),
    **COMMON_ENV_VARS
}

# Validate environment variables on startup
try:
    validated_vars = validate_startup_config("LinkedIn", LINKEDIN_ENV_VARS, logger)
    LINKEDIN_ACCESS_TOKEN = validated_vars["LINKEDIN_ACCESS_TOKEN"]
    LINKEDIN_MCP_SERVER_PORT = int(validated_vars.get("PORT", "5000"))
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    sys.exit(1)

@click.command()
@click.option("--port", default=LINKEDIN_MCP_SERVER_PORT, help="Port to listen on for HTTP")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
@click.option(
    "--json-response",
    is_flag=True,
    default=False,
    help="Enable JSON responses for StreamableHTTP instead of SSE streams",
)
def main(
    port: int,
    log_level: str,
    json_response: bool,
) -> int:
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create the MCP server instance
    app = Server("linkedin-mcp-server")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="linkedin_get_profile_info",
                description="Get LinkedIn profile information. If person_id is not provided, gets current user's profile.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "person_id": {
                            "type": "string",
                            "description": "The LinkedIn person ID to retrieve information for. Leave empty for current user."
                        }
                    }
                }
            ),
            types.Tool(
                name="linkedin_create_post",
                description="Create a post on LinkedIn with optional title for article-style posts.",
                inputSchema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text content of the post."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional title for article-style posts. When provided, creates an article format."
                        },
                        "hashtags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of hashtags to add to the post (# will be added automatically)."
                        },
                        "visibility": {
                            "type": "string",
                            "description": "Post visibility (PUBLIC, CONNECTIONS, LOGGED_IN_USERS).",
                            "default": "PUBLIC"
                        }
                    }
                }
            ),
            types.Tool(
                name="linkedin_format_rich_post",
                description="Format rich text for LinkedIn posts with bold, italic, lists, mentions, and hashtags (utility function - doesn't post).",
                inputSchema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The base text content to format."
                        },
                        "bold_text": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Text phrases to make bold (will be wrapped with **)."
                        },
                        "italic_text": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Text phrases to make italic (will be wrapped with *)."
                        },
                        "bullet_points": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of bullet points to add."
                        },
                        "numbered_list": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of numbered items to add."
                        },
                        "hashtags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of hashtags to add."
                        },
                        "mentions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of usernames to mention (@ will be added automatically)."
                        }
                    }
                }
            ),
            types.Tool(
                name="linkedin_create_url_share",
                description="Share URLs with metadata preview on LinkedIn.",
                inputSchema={
                    "type": "object",
                    "required": ["url", "text"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to share (must be a valid URL)."
                        },
                        "text": {
                            "type": "string",
                            "description": "Commentary text to accompany the shared URL."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional title for the shared URL content."
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional description for the shared URL content."
                        },
                        "visibility": {
                            "type": "string",
                            "description": "Post visibility (PUBLIC, CONNECTIONS, LOGGED_IN_USERS).",
                            "default": "PUBLIC"
                        }
                    }
                }
            ),
        ]

    @app.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        
        if name == "linkedin_create_post":
            text = arguments.get("text")
            title = arguments.get("title")
            hashtags = arguments.get("hashtags")
            visibility = arguments.get("visibility", "PUBLIC")
            if not text:
                return [
                    types.TextContent(
                        type="text",
                        text="Error: text parameter is required",
                    )
                ]
            try:
                result = await create_post(text, title, visibility, hashtags)
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]
            except Exception as e:
                logger.exception(f"Error executing tool {name}: {e}")
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error: {str(e)}",
                    )
                ]
        
        elif name == "linkedin_format_rich_post":
            text = arguments.get("text")
            bold_text = arguments.get("bold_text")
            italic_text = arguments.get("italic_text")
            bullet_points = arguments.get("bullet_points")
            numbered_list = arguments.get("numbered_list")
            hashtags = arguments.get("hashtags")
            mentions = arguments.get("mentions")
            
            if not text:
                return [
                    types.TextContent(
                        type="text",
                        text="Error: text parameter is required",
                    )
                ]
            try:
                result = format_rich_post(
                    text=text,
                    bold_text=bold_text,
                    italic_text=italic_text,
                    bullet_points=bullet_points,
                    numbered_list=numbered_list,
                    hashtags=hashtags,
                    mentions=mentions
                )
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]
            except Exception as e:
                logger.exception(f"Error executing tool {name}: {e}")
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error: {str(e)}",
                    )
                ]
        
        elif name == "linkedin_create_url_share":
            url = arguments.get("url")
            text = arguments.get("text")
            title = arguments.get("title")
            description = arguments.get("description")
            visibility = arguments.get("visibility", "PUBLIC")
            
            if not url:
                return [
                    types.TextContent(
                        type="text",
                        text="Error: url parameter is required",
                    )
                ]
            if not text:
                return [
                    types.TextContent(
                        type="text",
                        text="Error: text parameter is required",
                    )
                ]
            try:
                result = await create_url_share(url, text, title, description, visibility)
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]
            except Exception as e:
                logger.exception(f"Error executing tool {name}: {e}")
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error: {str(e)}",
                    )
                ]
        
        elif name == "linkedin_get_profile_info":
            person_id = arguments.get("person_id")
            try:
                result = await get_profile_info(person_id)
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]
            except Exception as e:
                logger.exception(f"Error executing tool {name}: {e}")
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error: {str(e)}",
                    )
                ]
        
        else:
            return [
                types.TextContent(
                    type="text",
                    text=f"Unknown tool: {name}",
                )
            ]

    # Set up SSE transport
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        logger.info("Handling SSE connection")
        
        # Extract LinkedIn access token from headers (fallback to environment)
        linkedin_token = request.headers.get('x-linkedin-token') or LINKEDIN_ACCESS_TOKEN
        
        # Set the LinkedIn token in context for this request
        token = linkedin_token_context.set(linkedin_token or "")
        try:
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )
        finally:
            linkedin_token_context.reset(token)
        
        return Response()

    # Set up StreamableHTTP transport
    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,  # Stateless mode - can be changed to use an event store
        json_response=json_response,
        stateless=True,
    )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        logger.info("Handling StreamableHTTP request")
        
        # Extract auth token from headers (fallback to environment)
        headers = dict(scope.get("headers", []))
        auth_token = headers.get(b'x-auth-token')
        if auth_token:
            auth_token = auth_token.decode('utf-8')
        else:
            auth_token = LINKEDIN_ACCESS_TOKEN
        
        # Set the LinkedIn token in context for this request
        token = linkedin_token_context.set(auth_token or "")
        try:
            await session_manager.handle_request(scope, receive, send)
        finally:
            linkedin_token_context.reset(token)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager."""
        async with session_manager.run():
            logger.info("Application started with dual transports!")
            try:
                yield
            finally:
                logger.info("Application shutting down...")

    # Create an ASGI application with routes for both transports
    starlette_app = Starlette(
        debug=True,
        routes=[
            # SSE routes
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
            
            # StreamableHTTP route
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    logger.info(f"Server starting on port {port} with dual transports:")
    logger.info(f"  - SSE endpoint: http://localhost:{port}/sse")
    logger.info(f"  - StreamableHTTP endpoint: http://localhost:{port}/mcp")

    import uvicorn

    uvicorn.run(starlette_app, host="0.0.0.0", port=port)

    return 0

if __name__ == "__main__":
    main()
