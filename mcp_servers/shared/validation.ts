/**
 * Shared validation utilities for Klavis MCP servers.
 * 
 * Provides consistent environment variable validation and error handling
 * across all TypeScript/Node.js-based MCP servers.
 */

export enum ValidationLevel {
    REQUIRED = 'required',
    OPTIONAL = 'optional',
    CONDITIONAL = 'conditional'
}

export interface EnvVarConfig {
    name: string;
    description: string;
    validationLevel: ValidationLevel;
    defaultValue?: string;
    setupUrl?: string;
    requiredPermissions?: string[];
    dependsOn?: string; // For conditional variables
}

export interface AuthErrorResponse {
    success: boolean;
    error: string;
    message: string;
    statusCode: number;
    type: 'authentication_error' | 'authorization_error';
    troubleshooting: {
        checkToken: string;
        checkPermissions: string;
        checkExpiration: string;
    };
}

export interface ConfigErrorResponse {
    success: boolean;
    error: string;
    message: string;
    statusCode: number;
    type: 'configuration_error';
    missingVariables: string[];
}

export class CredentialValidator {
    private serviceName: string;
    private logger: { error: (msg: string) => void; info: (msg: string) => void };

    constructor(serviceName: string, logger?: any) {
        this.serviceName = serviceName;
        this.logger = logger || console;
    }

    /**
     * Validate environment variables according to their configuration.
     */
    validateEnvVars(envVars: Record<string, EnvVarConfig>): Record<string, string> {
        const validatedVars: Record<string, string> = {};
        const missingRequired: EnvVarConfig[] = [];
        const missingConditional: EnvVarConfig[] = [];

        for (const [varName, config] of Object.entries(envVars)) {
            const value = process.env[varName] || config.defaultValue;

            if (config.validationLevel === ValidationLevel.REQUIRED) {
                if (!value || value.trim() === '') {
                    missingRequired.push(config);
                } else {
                    validatedVars[varName] = value;
                }
            } else if (config.validationLevel === ValidationLevel.CONDITIONAL) {
                // Check if the conditional dependency is met
                if (config.dependsOn && process.env[config.dependsOn]) {
                    if (!value || value.trim() === '') {
                        missingConditional.push(config);
                    } else {
                        validatedVars[varName] = value;
                    }
                } else if (value) {
                    validatedVars[varName] = value;
                }
            } else { // OPTIONAL
                if (value) {
                    validatedVars[varName] = value;
                }
            }
        }

        // Generate helpful error messages for missing variables
        if (missingRequired.length > 0 || missingConditional.length > 0) {
            const errorMessage = this.generateErrorMessage(missingRequired, missingConditional);
            throw new Error(errorMessage);
        }

        return validatedVars;
    }

    private generateErrorMessage(missingRequired: EnvVarConfig[], missingConditional: EnvVarConfig[]): string {
        const lines: string[] = [`❌ ${this.serviceName} MCP Server Configuration Error\n`];

        if (missingRequired.length > 0) {
            lines.push('Missing required environment variables:');
            for (const config of missingRequired) {
                lines.push(`  • ${config.name}: ${config.description}`);
                if (config.setupUrl) {
                    lines.push(`    Setup: ${config.setupUrl}`);
                }
                if (config.requiredPermissions) {
                    lines.push(`    Required permissions: ${config.requiredPermissions.join(', ')}`);
                }
                lines.push('');
            }
        }

        if (missingConditional.length > 0) {
            lines.push('Missing conditional environment variables:');
            for (const config of missingConditional) {
                lines.push(`  • ${config.name}: ${config.description}`);
                if (config.dependsOn) {
                    lines.push(`    Required when ${config.dependsOn} is set`);
                }
                lines.push('');
            }
        }

        const firstMissing = missingRequired[0] || missingConditional[0];
        lines.push(
            'To fix this:',
            '1. Set the environment variables in your shell:',
            `   export ${firstMissing.name}=your_token_here`,
            '',
            '2. Or add to a .env file:',
            `   ${firstMissing.name}=your_token_here`,
            '',
            `3. Restart the ${this.serviceName} MCP server`
        );

        return lines.join('\n');
    }

    static createAuthErrorResponse(service: string, errorDetails: string, statusCode: number = 401): AuthErrorResponse {
        return {
            success: false,
            error: `${service} Authentication Error`,
            message: errorDetails,
            statusCode,
            type: statusCode === 401 ? 'authentication_error' : 'authorization_error',
            troubleshooting: {
                checkToken: `Verify your ${service} access token is valid`,
                checkPermissions: `Ensure your ${service} token has required permissions`,
                checkExpiration: `Check if your ${service} token has expired`
            }
        };
    }

    static createConfigErrorResponse(service: string, missingVars: string[]): ConfigErrorResponse {
        return {
            success: false,
            error: `${service} Configuration Error`,
            message: `Missing required environment variables: ${missingVars.join(', ')}`,
            statusCode: 500,
            type: 'configuration_error',
            missingVariables: missingVars
        };
    }
}

/**
 * Convenience function for validating environment variables during server startup.
 */
export function validateStartupConfig(
    serviceName: string, 
    envVars: Record<string, EnvVarConfig>, 
    logger?: any
): Record<string, string> {
    const validator = new CredentialValidator(serviceName, logger);
    return validator.validateEnvVars(envVars);
}

/**
 * Validate authentication token from request headers or environment.
 */
export function validateAuthToken(
    tokenFromHeader: string | undefined,
    envVarName: string,
    serviceName: string
): string {
    const token = tokenFromHeader || process.env[envVarName];
    
    if (!token || token.trim() === '') {
        throw new Error(
            `${serviceName} authentication token is missing. ` +
            `Provide it via ${envVarName} environment variable or x-auth-token header.`
        );
    }
    
    return token;
}

// Common environment variable configurations for reuse
export const COMMON_ENV_VARS: Record<string, EnvVarConfig> = {
    PORT: {
        name: 'PORT',
        description: 'Port for the MCP server to listen on',
        validationLevel: ValidationLevel.OPTIONAL,
        defaultValue: '5000'
    },
    LOG_LEVEL: {
        name: 'LOG_LEVEL',
        description: 'Logging level (debug, info, warn, error)',
        validationLevel: ValidationLevel.OPTIONAL,
        defaultValue: 'info'
    }
};