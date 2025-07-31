"""
Shared validation utilities for Klavis MCP servers.

Provides consistent environment variable validation and error handling
across all Python-based MCP servers.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class ValidationLevel(Enum):
    """Validation level for environment variables."""
    REQUIRED = "required"
    OPTIONAL = "optional"
    CONDITIONAL = "conditional"


@dataclass
class EnvVarConfig:
    """Configuration for an environment variable."""
    name: str
    description: str
    validation_level: ValidationLevel
    default_value: Optional[str] = None
    setup_url: Optional[str] = None
    required_permissions: Optional[List[str]] = None
    depends_on: Optional[str] = None  # For conditional variables


class CredentialValidator:
    """Utility class for validating environment variables and handling auth errors."""
    
    def __init__(self, service_name: str, logger: Optional[logging.Logger] = None):
        self.service_name = service_name
        self.logger = logger or logging.getLogger(__name__)
    
    def validate_env_vars(self, env_vars: Dict[str, EnvVarConfig]) -> Dict[str, str]:
        """
        Validate environment variables according to their configuration.
        
        Args:
            env_vars: Dictionary mapping variable names to their configuration
            
        Returns:
            Dictionary of validated environment variables
            
        Raises:
            ValueError: If required environment variables are missing or invalid
        """
        validated_vars = {}
        missing_required = []
        missing_conditional = []
        
        for var_name, config in env_vars.items():
            value = os.getenv(var_name, config.default_value)
            
            if config.validation_level == ValidationLevel.REQUIRED:
                if not value or value.strip() == "":
                    missing_required.append(config)
                else:
                    validated_vars[var_name] = value
                    
            elif config.validation_level == ValidationLevel.CONDITIONAL:
                # Check if the conditional dependency is met
                if config.depends_on and os.getenv(config.depends_on):
                    if not value or value.strip() == "":
                        missing_conditional.append(config)
                    else:
                        validated_vars[var_name] = value
                elif value:
                    validated_vars[var_name] = value
                    
            else:  # OPTIONAL
                if value:
                    validated_vars[var_name] = value
        
        # Generate helpful error messages for missing variables
        if missing_required or missing_conditional:
            error_message = self._generate_error_message(missing_required, missing_conditional)
            raise ValueError(error_message)
        
        return validated_vars
    
    def _generate_error_message(self, missing_required: List[EnvVarConfig], 
                               missing_conditional: List[EnvVarConfig]) -> str:
        """Generate a helpful error message for missing environment variables."""
        lines = [f"❌ {self.service_name} MCP Server Configuration Error\n"]
        
        if missing_required:
            lines.append("Missing required environment variables:")
            for config in missing_required:
                lines.append(f"  • {config.name}: {config.description}")
                if config.setup_url:
                    lines.append(f"    Setup: {config.setup_url}")
                if config.required_permissions:
                    lines.append(f"    Required permissions: {', '.join(config.required_permissions)}")
                lines.append("")
        
        if missing_conditional:
            lines.append("Missing conditional environment variables:")
            for config in missing_conditional:
                lines.append(f"  • {config.name}: {config.description}")
                if config.depends_on:
                    lines.append(f"    Required when {config.depends_on} is set")
                lines.append("")
        
        lines.extend([
            "To fix this:",
            "1. Set the environment variables in your shell:",
            f"   export {missing_required[0].name if missing_required else missing_conditional[0].name}=your_token_here",
            "",
            "2. Or add to a .env file:",
            f"   {missing_required[0].name if missing_required else missing_conditional[0].name}=your_token_here",
            "",
            f"3. Restart the {self.service_name} MCP server",
        ])
        
        return "\n".join(lines)
    
    @staticmethod
    def create_auth_error_response(service: str, error_details: str, 
                                 status_code: int = 401) -> Dict[str, Any]:
        """
        Create a consistent error response for authentication failures.
        
        Args:
            service: Name of the service (e.g., "GitHub", "Slack")
            error_details: Specific error details
            status_code: HTTP status code (401 for auth, 403 for permissions)
            
        Returns:
            Standardized error response dictionary
        """
        return {
            "success": False,
            "error": f"{service} Authentication Error",
            "message": error_details,
            "status_code": status_code,
            "type": "authentication_error" if status_code == 401 else "authorization_error",
            "troubleshooting": {
                "check_token": f"Verify your {service} access token is valid",
                "check_permissions": f"Ensure your {service} token has required permissions",
                "check_expiration": f"Check if your {service} token has expired"
            }
        }
    
    @staticmethod
    def create_config_error_response(service: str, missing_vars: List[str]) -> Dict[str, Any]:
        """
        Create a consistent error response for configuration issues.
        
        Args:
            service: Name of the service
            missing_vars: List of missing environment variables
            
        Returns:
            Standardized error response dictionary
        """
        return {
            "success": False,
            "error": f"{service} Configuration Error",
            "message": f"Missing required environment variables: {', '.join(missing_vars)}",
            "status_code": 500,
            "type": "configuration_error",
            "missing_variables": missing_vars
        }


def validate_startup_config(service_name: str, env_vars: Dict[str, EnvVarConfig], 
                          logger: Optional[logging.Logger] = None) -> Dict[str, str]:
    """
    Convenience function for validating environment variables during server startup.
    
    Args:
        service_name: Name of the service for error messages
        env_vars: Dictionary of environment variable configurations
        logger: Optional logger instance
        
    Returns:
        Dictionary of validated environment variables
        
    Raises:
        ValueError: If validation fails with helpful error message
    """
    validator = CredentialValidator(service_name, logger)
    return validator.validate_env_vars(env_vars)


# Common environment variable configurations for reuse
COMMON_ENV_VARS = {
    "PORT": EnvVarConfig(
        name="PORT",
        description="Port for the MCP server to listen on",
        validation_level=ValidationLevel.OPTIONAL,
        default_value="5000"
    ),
    "LOG_LEVEL": EnvVarConfig(
        name="LOG_LEVEL", 
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
        validation_level=ValidationLevel.OPTIONAL,
        default_value="INFO"
    )
}