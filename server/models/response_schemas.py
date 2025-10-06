"""API Response Schema Models"""

from typing import Dict, Any, Optional, List, Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class ChatResponse(BaseModel):
    """Standard chat response model"""
    response: str = Field(..., description="AI agent response text")
    status: Literal["success", "error"] = Field(default="success", description="Response status")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        json_schema_extra = {
            "example": {
                "response": "Hello! How can I help you today?",
                "status": "success", 
                "metadata": {"model": "gemini-1.5-pro", "tools_used": []}
            }
        }


class DetailedChatResponse(BaseModel):
    """Detailed chat response with ReAct information"""
    response: str = Field(..., description="AI agent response text")
    status: Literal["success", "error"] = Field(default="success", description="Response status")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    react_state: Optional[Dict[str, Any]] = Field(None, description="ReAct engine state information")
    reasoning_steps: int = Field(0, description="Number of reasoning steps taken")
    tools_used: List[str] = Field(default_factory=list, description="List of tools used during processing")
    success: bool = Field(True, description="Whether the operation was successful")
    
    class Config:
        json_schema_extra = {
            "example": {
                "response": "Based on my analysis, the stock price is $150.",
                "status": "success",
                "metadata": {"model": "gemini-1.5-pro", "query": "What is AAPL stock price?"},
                "react_state": {"is_completed": True, "error": None},
                "reasoning_steps": 3,
                "tools_used": ["yfinance", "web_search"],
                "success": True
            }
        }


class StreamEvent(BaseModel):
    """Stream event model for Server-Sent Events"""
    type: Literal["start", "thought", "action", "observation", "final_answer", "error", "token", "end"] = Field(..., description="Event type")
    content: str = Field(..., description="Event content")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Event metadata")
    timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="Event timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "thought",
                "content": "I need to search for the current stock price.",
                "metadata": {"step": 1},
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class ModelInfo(BaseModel):
    """Model information response"""
    models: List[str] = Field(..., description="List of supported models")
    default: str = Field(..., description="Default model name")
    
    class Config:
        json_schema_extra = {
            "example": {
                "models": ["gemini-1.5-pro", "gemini-1.5-flash"],
                "default": "gemini-1.5-pro"
            }
        }


class AgentStatus(BaseModel):
    """Agent status response"""
    ready: bool = Field(..., description="Whether the agent is ready")
    model_info: Dict[str, Any] = Field(..., description="Model configuration information")
    react_enabled: bool = Field(True, description="Whether ReAct capabilities are enabled")
    available_tools: int = Field(..., description="Number of available tools")
    timestamp: str = Field(..., description="Status check timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ready": True,
                "model_info": {"model_name": "gemini-1.5-pro", "temperature": 0.1},
                "react_enabled": True,
                "available_tools": 4,
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class ErrorResponse(BaseModel):
    """Error response model"""
    detail: str = Field(..., description="Error message")
    status: Literal["error"] = Field(default="error", description="Response status")
    error_code: Optional[str] = Field(None, description="Specific error code")
    
    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Model not supported",
                "status": "error",
                "error_code": "INVALID_MODEL"
            }
        }


# Union types for response documentation
ChatResponseUnion = Union[ChatResponse, DetailedChatResponse, ErrorResponse]
