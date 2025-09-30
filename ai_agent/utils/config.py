"""Configuration management for AI Agent"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
except ImportError:
    from pydantic import BaseSettings, Field


class Config(BaseSettings):
    """Configuration class for AI Agent"""
    
    # Google Gemini API Configuration
    google_api_key: str = Field(description="Google API key", alias="GOOGLE_API_KEY")
    
    # Perplexity API Configuration
    perplexity_api_key: Optional[str] = Field(default=None, alias="PPLX_API_KEY")
    
    # Agent Configuration
    agent_name: str = Field(default="AIAgent", alias="AGENT_NAME")
    agent_version: str = Field(default="2.0.0", alias="AGENT_VERSION")
    agent_model: str = Field(default="gemini-2.0-flash-exp", alias="AGENT_MODEL")
    
    # Model Configuration
    temperature: float = Field(default=0.7, alias="TEMPERATURE")
    max_tokens: int = Field(default=2048, alias="MAX_TOKENS")
    top_p: float = Field(default=0.8, alias="TOP_P")
    top_k: int = Field(default=40, alias="TOP_K")
    
    # ReAct Engine Configuration
    react_max_retries: int = Field(default=3, alias="REACT_MAX_RETRIES")
    react_max_thought_cycles: int = Field(default=5, alias="REACT_MAX_THOUGHT_CYCLES")
    react_context_steps: int = Field(default=6, alias="REACT_CONTEXT_STEPS")
    
    # Tool Configuration
    code_execution_timeout: int = Field(default=30, alias="CODE_EXECUTION_TIMEOUT")
    
    # Logging Configuration
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: Optional[str] = Field(default=None, alias="LOG_FILE")
    
    # MongoDB Configuration
    mongodb_enabled: bool = Field(default=False, alias="MONGODB_ENABLED")
    mongodb_uri: Optional[str] = Field(default=None, alias="MONGODB_URI")
    mongodb_database: str = Field(default="ai_agent", alias="MONGODB_DATABASE")
    mongodb_collection: str = Field(default="react_sessions", alias="MONGODB_COLLECTION")
    
    class ConfigSettings:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # 추가 필드 무시

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
            raise ValueError("Google API key is required. Please set GOOGLE_API_KEY in your environment.")
        
        return True


# Global config instance
config = Config.load_from_file()
