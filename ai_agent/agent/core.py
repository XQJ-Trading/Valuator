"""Core AI Agent implementation"""

import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator, Callable
from datetime import datetime

from ..models.gemini import GeminiModel, GeminiResponse
from ..utils.config import config
from ..utils.logger import logger


class GeminiAgent:
    """Main AI Agent class using Gemini model"""
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None
    ):
        """
        Initialize Gemini Agent
        
        Args:
            model_name: Name of the Gemini model to use
            system_prompt: System prompt for the agent
        """
        self.model_name = model_name or config.agent_model
        self.system_prompt = system_prompt or self._get_default_system_prompt()
        self.model = GeminiModel(self.model_name)
        
        logger.info(f"Initialized Gemini Agent: {config.agent_name} v{config.agent_version}")
        logger.debug(f"Using model: {self.model_name}")
    
    def _get_default_system_prompt(self) -> str:
        """Get default system prompt"""
        return """You are a helpful AI assistant powered by Google's Gemini model. 
You are designed to be helpful, harmless, and honest. You can engage in conversations, 
answer questions, help with tasks, and provide information on a wide variety of topics.

Key guidelines:
- Be concise but comprehensive in your responses
- If you're unsure about something, say so rather than guessing
- Be respectful and professional in all interactions
- Use clear and easy-to-understand language
- When appropriate, provide examples or explanations to help users understand concepts better"""
    
    async def chat(
        self, 
        message: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Chat with the agent
        
        Args:
            message: User message
            metadata: Additional metadata for the message
            
        Returns:
            Agent response
        """
        try:
            # Format messages for the model
            formatted_messages = self.model.format_messages(
                system_prompt=self.system_prompt,
                conversation_history=[],
                current_input=message
            )
            
            # Generate complete response
            response = await self.model.generate_response(formatted_messages)
            
            logger.debug(f"Generated response: {len(response.content)} characters")
            return response.content
                
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            error_msg = "I apologize, but I encountered an error while processing your request. Please try again."
            return error_msg
    
    async def chat_stream(
        self, 
        message: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Chat with the agent using streaming
        
        Args:
            message: User message
            metadata: Additional metadata for the message
            
        Yields:
            Response chunks as they are generated
        """
        try:
            # Format messages for the model
            formatted_messages = self.model.format_messages(
                system_prompt=self.system_prompt,
                conversation_history=[],
                current_input=message
            )
            
            # Stream response
            response_content = ""
            async for chunk in self.model.generate_streaming_response(formatted_messages):
                response_content += chunk
                yield chunk
                
        except Exception as e:
            logger.error(f"Error in chat_stream: {e}")
            error_msg = "I apologize, but I encountered an error while processing your request. Please try again."
            yield error_msg
    
    def set_system_prompt(self, prompt: str):
        """Update the system prompt"""
        self.system_prompt = prompt
        logger.info("Updated system prompt")
    
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information"""
        model_info = self.model.get_model_info()
        model_info.update({
            "agent_name": config.agent_name,
            "agent_version": config.agent_version,
            "system_prompt_length": len(self.system_prompt)
        })
        return model_info
    
    def add_tool(self, tool_func: Callable, tool_name: Optional[str] = None):
        
        # Note: Tool integration is handled by ReActAgent
        # This method is kept for compatibility
        logger.info(f"Tool registration noted: {tool_name or tool_func.__name__}. Use ReActAgent for full tool support.")
    
    async def reset(self):
        """Reset the agent to initial state"""
        self.system_prompt = self._get_default_system_prompt()
        logger.info("Reset agent to initial state")
    
    def is_ready(self) -> bool:
        """Check if agent is ready to process requests"""
        return (
            self.model is not None and 
            self.system_prompt is not None
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get agent status"""
        return {
            "ready": self.is_ready(),
            "model_info": self.get_model_info(),
            "timestamp": datetime.now().isoformat()
        }
