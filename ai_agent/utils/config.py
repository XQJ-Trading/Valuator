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
    google_api_key: str = Field(..., env="GOOGLE_API_KEY")
    
    # Perplexity API Configuration
    perplexity_api_key: Optional[str] = Field(None, env="PPLX_API_KEY")
    
    # LangChain Configuration
    langchain_api_key: Optional[str] = Field(None, env="LANGCHAIN_API_KEY")
    langchain_tracing_v2: bool = Field(True, env="LANGCHAIN_TRACING_V2")
    langchain_project: str = Field("ai-agent-project", env="LANGCHAIN_PROJECT")
    
    # Agent Configuration
    agent_name: str = Field("GeminiAgent", env="AGENT_NAME")
    agent_version: str = Field("1.0.0", env="AGENT_VERSION")
    agent_model: str = Field("gemini-2.0-flash-exp", env="AGENT_MODEL")
    
    # Model Configuration
    temperature: float = Field(0.7, env="TEMPERATURE")
    max_tokens: int = Field(2048, env="MAX_TOKENS")
    top_p: float = Field(0.8, env="TOP_P")
    top_k: int = Field(40, env="TOP_K")
    
    
    # ReAct Engine Configuration
    react_max_retries: int = Field(3, env="REACT_MAX_RETRIES")
    react_max_thought_cycles: int = Field(5, env="REACT_MAX_THOUGHT_CYCLES")
    react_context_steps: int = Field(6, env="REACT_CONTEXT_STEPS")
    react_complexity_threshold: int = Field(2, env="REACT_COMPLEXITY_THRESHOLD")
    
    # Tool Configuration
    code_execution_timeout: int = Field(30, env="CODE_EXECUTION_TIMEOUT")
    
    # Logging Configuration
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_file: Optional[str] = Field(None, env="LOG_FILE")
    
    class Config:
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
            env_file = project_root / ".env"
        
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
