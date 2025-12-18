"""Configuration management for AI Agent"""

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration class for AI Agent"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Google Gemini API Configuration
    google_api_key: Optional[str] = Field(
        default=None, description="Google API key", alias="GOOGLE_API_KEY"
    )

    # Perplexity API Configuration
    perplexity_api_key: Optional[str] = Field(default=None, alias="PPLX_API_KEY")

    # Agent Configuration
    agent_name: str = Field(default="AIAgent", alias="AGENT_NAME")
    agent_version: str = Field(default="2.0.0", alias="AGENT_VERSION")
    agent_model: str = Field(default="gemini-3-flash-preview", alias="AGENT_MODEL")

    # Supported Models Configuration (as string, parsed to list)
    supported_models_str: str = Field(
        default="gemini-3-flash-preview,gemini-3-pro-preview,gemini-flash-latest,gemini-pro-latest",
        alias="SUPPORTED_MODELS",
        description="Comma-separated list of supported model names",
    )

    # Model Configuration
    temperature: float = Field(default=0.7, alias="TEMPERATURE")
    max_tokens: int = Field(default=2048, alias="MAX_TOKENS")
    top_p: float = Field(default=0.8, alias="TOP_P")
    top_k: int = Field(default=40, alias="TOP_K")

    # ReAct Engine Configuration
    react_max_retries: int = Field(default=3, alias="REACT_MAX_RETRIES")
    react_max_thought_cycles: int = Field(default=5, alias="REACT_MAX_THOUGHT_CYCLES")

    # Tool Configuration
    code_execution_timeout: int = Field(default=30, alias="CODE_EXECUTION_TIMEOUT")

    # Logging Configuration
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: Optional[str] = Field(default=None, alias="LOG_FILE")

    # Response Logging Configuration
    gemini_low_level_request_logging: bool = Field(
        default=False, alias="GEMINI_LOW_LEVEL_REQUEST_LOGGING"
    )

    # MongoDB Configuration
    mongodb_enabled: bool = Field(default=False, alias="MONGODB_ENABLED")
    mongodb_uri: Optional[str] = Field(default=None, alias="MONGODB_URI")
    mongodb_database: str = Field(default="ai_agent", alias="MONGODB_DATABASE")
    mongodb_collection: str = Field(
        default="react_sessions", alias="MONGODB_COLLECTION"
    )

    @property
    def supported_models(self) -> List[str]:
        """Parse supported models from comma-separated string"""
        if not self.supported_models_str or self.supported_models_str.strip() == "":
            return [
                "gemini-3-flash-preview",
                "gemini-3-pro-preview",
                "gemini-flash-latest",
                "gemini-pro-latest",
            ]

        # Clean up the string and split by comma
        models_str = self.supported_models_str.strip().strip("[]").strip('"').strip("'")
        if not models_str:
            return [
                "gemini-3-flash-preview",
                "gemini-3-pro-preview",
                "gemini-flash-latest",
                "gemini-pro-latest",
            ]

        # Split by comma and clean up each item
        models = [
            model.strip().strip('"').strip("'") for model in models_str.split(",")
        ]
        return [model for model in models if model]

    @field_validator("agent_model")
    @classmethod
    def validate_agent_model(cls, v, info):
        """Ensure agent_model is in supported_models"""
        # Note: This validator runs before supported_models is processed,
        # so we'll do this validation in validate_config method instead
        return v

    @classmethod
    def load_from_file(cls, env_file: Optional[str] = None) -> "Config":
        """Load configuration from environment file"""
        if env_file is None:
            # Try to find .env file in project root
            project_root = Path(__file__).parent.parent.parent
            env_file = str(project_root / ".env")

        if env_file and Path(env_file).exists():
            load_dotenv(env_file)

        return cls()

    def validate_config(self) -> bool:
        """Validate configuration"""
        if not self.google_api_key or self.google_api_key == "your_google_api_key_here":
            raise ValueError(
                "Google API key is required. Please set GOOGLE_API_KEY in your environment."
            )

        # Validate that agent_model is in supported_models
        if self.agent_model not in self.supported_models:
            raise ValueError(
                f"Default agent model '{self.agent_model}' is not in supported models: {self.supported_models}. "
                f"Please update AGENT_MODEL or add it to SUPPORTED_MODELS."
            )

        return True


# Global config instance
config = Config.load_from_file()
