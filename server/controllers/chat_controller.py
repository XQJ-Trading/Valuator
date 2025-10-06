"""Chat controller for handling chat-related API endpoints"""

from typing import Dict, Any, Optional
from fastapi import HTTPException

from server.core.agent.react_agent import AIAgent
from server.core.utils.logger import logger


class ChatController:
    """Controller for chat operations"""
    
    def __init__(self, agent: AIAgent):
        """Initialize chat controller with AI agent"""
        self.agent = agent
        
    async def send_message(self, message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send a chat message and get response
        
        Args:
            message: User message
            metadata: Additional metadata
            
        Returns:
            Dict containing response and metadata
        """
        try:
            logger.info(f"Processing chat message: {message[:100]}...")
            
            # Get response from agent
            response = await self.agent.chat(message, metadata)
            
            return {
                "response": response,
                "status": "success",
                "metadata": metadata or {}
            }
            
        except Exception as e:
            logger.error(f"Error processing chat message: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def send_message_stream(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Send a chat message and stream response
        
        Args:
            message: User message
            metadata: Additional metadata
            
        Yields:
            Response chunks
        """
        try:
            logger.info(f"Processing streaming chat message: {message[:100]}...")
            
            async for chunk in self.agent.chat_stream(message, metadata):
                yield chunk
                
        except Exception as e:
            logger.error(f"Error processing streaming chat message: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def get_agent_status(self) -> Dict[str, Any]:
        """Get agent status information"""
        try:
            return self.agent.get_status()
        except Exception as e:
            logger.error(f"Error getting agent status: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def get_available_tools(self) -> Dict[str, Any]:
        """Get list of available tools"""
        try:
            tools = self.agent.get_available_tools()
            return {
                "tools": tools,
                "count": len(tools),
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Error getting available tools: {e}")
            raise HTTPException(status_code=500, detail=str(e))
