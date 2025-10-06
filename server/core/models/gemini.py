"""Gemini model integration for AI Agent"""

import asyncio
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncGenerator
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.callbacks import AsyncCallbackHandler
from pydantic import BaseModel, Field

from ..utils.config import config
from ..utils.logger import logger


def _normalize_content(value: Any) -> str:
    """Normalize model content to a plain string.

    Handles cases where LangChain returns content as a list of parts.
    """
    if isinstance(value, str):
        return value
    # List of parts (dicts or objects). Attempt to extract text fields.
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            # Common shapes: {"type": "text", "text": "..."}
            try:
                if isinstance(item, dict):
                    if "text" in item and isinstance(item["text"], str):
                        parts.append(item["text"]) 
                    elif "content" in item and isinstance(item["content"], str):
                        parts.append(item["content"]) 
                    else:
                        # Fallback stringification
                        parts.append(str(item))
                else:
                    # Object with .text or .content attr
                    text_attr = getattr(item, "text", None)
                    if isinstance(text_attr, str):
                        parts.append(text_attr)
                    else:
                        content_attr = getattr(item, "content", None)
                        if isinstance(content_attr, str):
                            parts.append(content_attr)
                        else:
                            parts.append(str(item))
            except Exception:
                parts.append(str(item))
        return "".join(parts)
    # Fallback
    return str(value)


class GeminiResponse(BaseModel):
    """Response model for Gemini"""
    content: str = Field(..., description="Response content")
    usage: Optional[Dict[str, Any]] = Field(None, description="Token usage information")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    cache_metrics: Optional[Dict[str, Any]] = Field(None, description="Context caching metrics")


class GeminiChatSession:
    """Represents a chat session with the Gemini model"""
    def __init__(self, model, initial_messages: List[BaseMessage]):
        self.model = model
        self.history: List[BaseMessage] = initial_messages

    async def send_message(
        self,
        message: str,
        callbacks: Optional[List[AsyncCallbackHandler]] = None
    ) -> GeminiResponse:
        """Send a message in the session and get a response"""
        self.history.append(HumanMessage(content=message))
        
        response = await self.model.agenerate(
            messages=[self.history],
            callbacks=callbacks
        )

        # Prefer AIMessage fields if available (LangChain wraps usage there)
        generation = response.generations[0][0]
        message_obj = getattr(generation, 'message', None)
        if message_obj and getattr(message_obj, 'content', None) is not None:
            content = _normalize_content(message_obj.content)
        else:
            content = _normalize_content(getattr(generation, 'text', ""))

        # Extract usage from AIMessage.usage_metadata first, then fall back
        usage = None
        if message_obj is not None:
            usage = getattr(message_obj, 'usage_metadata', None)
        if usage is None:
            gen_info = getattr(generation, 'generation_info', None) or {}
            if isinstance(gen_info, dict):
                usage = gen_info.get('usage_metadata')

        # Extract cache metrics from usage metadata
        cache_metrics = self._extract_cache_metrics(usage)

        # 파일로 응답 저장 (환경 설정에 따라)
        if config.enable_response_logging:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"response_{timestamp}.json"
                filepath = os.path.join("logs", "low_level_query", filename)

                # 응답 데이터 구성
                response_data = {
                    "timestamp": timestamp,
                    "model": self.model.model,
                    "content": content,
                    "usage": usage,
                    "cache_metrics": cache_metrics,
                    "message_count": len(self.history)
                }

                # 파일 저장
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(response_data, f, ensure_ascii=False, indent=2)

                logger.debug(f"응답을 파일로 저장했습니다: {filepath}")
            except Exception as e:
                logger.warning(f"응답 파일 저장 실패: {e}")
        
        self.history.append(AIMessage(content=content))
        
        return GeminiResponse(
            content=content,
            usage=usage,
            metadata={"model": self.model.model},
            cache_metrics=cache_metrics
        )
    
    def _extract_cache_metrics(self, usage_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract context caching metrics from usage metadata"""
        if not usage_metadata:
            return None
        
        # Extract cache-related fields from usage metadata
        cache_metrics = {}
        
        # Common cache fields in Gemini API usage metadata
        cache_fields = [
            'cached_content_token_count',  # Number of cached tokens used
            'candidates_token_count',      # Output tokens
            'prompt_token_count',          # Total input tokens
            'total_token_count'            # Total tokens
        ]
        
        for field in cache_fields:
            if field in usage_metadata:
                cache_metrics[field] = usage_metadata[field]
        
        # Calculate cache efficiency if we have the data
        if 'cached_content_token_count' in cache_metrics and 'prompt_token_count' in cache_metrics:
            cached_tokens = cache_metrics['cached_content_token_count']
            total_input_tokens = cache_metrics['prompt_token_count']
            
            if total_input_tokens > 0:
                cache_hit_ratio = cached_tokens / total_input_tokens
                cache_metrics['cache_hit_ratio'] = cache_hit_ratio
                cache_metrics['cache_efficiency_percentage'] = round(cache_hit_ratio * 100, 2)
                
                # Log cache metrics
                if cached_tokens > 0:
                    logger.info(f"🔄 Context Cache Hit - Cached: {cached_tokens} tokens, "
                              f"Total Input: {total_input_tokens} tokens, "
                              f"Cache Efficiency: {cache_metrics['cache_efficiency_percentage']}%")
                else:
                    logger.debug(f"📤 No Cache Hit - Total Input: {total_input_tokens} tokens")
        
        return cache_metrics if cache_metrics else None

    async def stream_message(
        self,
        message: str,
        callbacks: Optional[List[AsyncCallbackHandler]] = None
    ) -> AsyncGenerator[str, None]:
        """Send a message and stream the response"""
        self.history.append(HumanMessage(content=message))
        
        streamed_content = ""
        # LangChain ChatGoogleGenerativeAI expects nested messages for streaming
        yielded_any = False
        async for chunk in self.model.astream(messages=[self.history], callbacks=callbacks):
            if hasattr(chunk, 'content') and chunk.content:
                streamed_content += chunk.content
                yielded_any = True
                yield chunk.content
        # Fallback if provider returned no chunks
        if not yielded_any:
            response = await self.send_message(message, callbacks=callbacks)
            yield response.content
        
        self.history.append(AIMessage(content=streamed_content))


class GeminiModel:
    """Gemini model wrapper for AI Agent"""
    
    def __init__(self, model_name: Optional[str] = None):
        """
        Initialize Gemini model
        
        Args:
            model_name: Model name to use (defaults to config value)
        """
        self.model_name = model_name or config.agent_model
        self.llm = None
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the Gemini model"""
        try:
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=config.google_api_key,
                temperature=config.temperature,
                max_output_tokens=config.max_tokens,
                top_p=config.top_p,
                top_k=config.top_k,
                streaming=True,
                convert_system_message_to_human=True,
            )
            logger.info(f"Initialized Gemini model: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            raise
    
    async def generate_response(
        self, 
        messages: List[BaseMessage],
        callbacks: Optional[List[AsyncCallbackHandler]] = None
    ) -> GeminiResponse:
        """
        Generate response from Gemini model
        
        Args:
            messages: List of messages for conversation
            callbacks: Optional callbacks for streaming
            
        Returns:
            GeminiResponse object
        """
        try:
            logger.debug(f"Generating response with {len(messages)} messages")
            
            # Remove callbacks parameter as it's not supported
            response = await self.llm.agenerate(
                messages=[messages]
            )
            
            # Extract response content & usage similar to session path
            generation = response.generations[0][0]
            message_obj = getattr(generation, 'message', None)
            if message_obj and getattr(message_obj, 'content', None) is not None:
                content = _normalize_content(message_obj.content)
            else:
                content = _normalize_content(getattr(generation, 'text', ""))
            
            usage = None
            if message_obj is not None:
                usage = getattr(message_obj, 'usage_metadata', None)
            if usage is None:
                gen_info = getattr(generation, 'generation_info', None) or {}
                if isinstance(gen_info, dict):
                    usage = gen_info.get('usage_metadata')
            
            # Extract cache metrics from usage metadata
            cache_metrics = self._extract_cache_metrics(usage)
            
            logger.debug(f"Generated response: {len(content)} characters")
            
            return GeminiResponse(
                content=content,
                usage=usage,
                metadata={"model": self.model_name},
                cache_metrics=cache_metrics
            )
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise
    
    async def generate_streaming_response(
        self, 
        messages: List[BaseMessage],
        callbacks: Optional[List[AsyncCallbackHandler]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming response from Gemini model
        
        Args:
            messages: List of messages for conversation
            callbacks: Optional callbacks for streaming
            
        Yields:
            Response chunks as they are generated
        """
        try:
            logger.debug(f"Generating streaming response with {len(messages)} messages")
            
            yielded_any = False
            # Use nested messages shape for ChatGoogleGenerativeAI
            async for chunk in self.llm.astream(messages=[messages]):
                if hasattr(chunk, 'content') and chunk.content:
                    yielded_any = True
                    yield chunk.content
            if not yielded_any:
                logger.warning("No generation chunks were returned; falling back to non-streaming response")
                full = await self.generate_response(messages, callbacks=callbacks)
                # Optionally split into chunks for smoother UI
                yield full.content
                    
        except Exception as e:
            logger.error(f"Error generating streaming response: {e}")
            # Fallback on error as well
            try:
                full = await self.generate_response(messages, callbacks=callbacks)
                yield full.content
            except Exception as ee:
                logger.error(f"Fallback also failed: {ee}")
                raise
    
    def create_system_message(self, content: str) -> SystemMessage:
        """Create a system message"""
        return SystemMessage(content=content)
    
    def create_human_message(self, content: str) -> HumanMessage:
        """Create a human message"""
        return HumanMessage(content=content)
    
    def create_ai_message(self, content: str) -> AIMessage:
        """Create an AI message"""
        return AIMessage(content=content)
    
    def format_messages(
        self, 
        system_prompt: str, 
        conversation_history: List[Dict[str, str]],
        current_input: str
    ) -> List[BaseMessage]:
        """
        Format messages for Gemini model
        
        Args:
            system_prompt: System prompt for the conversation
            conversation_history: Previous conversation history
            current_input: Current user input
            
        Returns:
            Formatted list of messages
        """
        messages = []
        
        # Add system message
        if system_prompt:
            messages.append(self.create_system_message(system_prompt))
        
        # Add conversation history
        for turn in conversation_history:
            if turn.get("role") == "user":
                messages.append(self.create_human_message(turn["content"]))
            elif turn.get("role") == "assistant":
                messages.append(self.create_ai_message(turn["content"]))
        
        # Add current input
        messages.append(self.create_human_message(current_input))
        
        return messages
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information"""
        return {
            "model_name": self.model_name,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "top_p": config.top_p,
            "top_k": config.top_k
        }

    def _extract_cache_metrics(self, usage_metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Extract context caching metrics from usage metadata"""
        if not usage_metadata:
            return None
        
        # Extract cache-related fields from usage metadata
        cache_metrics: Dict[str, Any] = {}
        
        # Support both Google raw fields and LangChain UsageMetadata fields
        # Raw Google fields
        if 'prompt_token_count' in usage_metadata:
            cache_metrics['prompt_token_count'] = usage_metadata.get('prompt_token_count', 0)
            cache_metrics['candidates_token_count'] = usage_metadata.get('candidates_token_count', 0)
            cache_metrics['total_token_count'] = usage_metadata.get('total_token_count', 0)
            cache_metrics['cached_content_token_count'] = usage_metadata.get('cached_content_token_count', 0)
        else:
            # LangChain UsageMetadata shape: input_tokens/output_tokens/total_tokens
            input_tokens = usage_metadata.get('input_tokens', 0)
            output_tokens = usage_metadata.get('output_tokens', 0)
            total_tokens = usage_metadata.get('total_tokens', input_tokens + output_tokens)
            cache_metrics['prompt_token_count'] = input_tokens
            cache_metrics['candidates_token_count'] = output_tokens
            cache_metrics['total_token_count'] = total_tokens
            # LangChain does not expose cached tokens; set 0
            cache_metrics['cached_content_token_count'] = usage_metadata.get('cached_content_token_count', 0) or 0
        
        # Calculate cache efficiency if we have the data
        cached_tokens = cache_metrics.get('cached_content_token_count', 0)
        total_input_tokens = cache_metrics.get('prompt_token_count', 0)
        if total_input_tokens > 0:
            cache_hit_ratio = (cached_tokens / total_input_tokens) if cached_tokens > 0 else 0.0
            cache_metrics['cache_hit_ratio'] = cache_hit_ratio
            cache_metrics['cache_efficiency_percentage'] = round(cache_hit_ratio * 100, 2)
            # Log cache metrics
            if cached_tokens > 0:
                logger.info(
                    f"🔄 Context Cache Hit - Cached: {cached_tokens} tokens, "
                    f"Total Input: {total_input_tokens} tokens, "
                    f"Cache Efficiency: {cache_metrics['cache_efficiency_percentage']}%"
                )
            else:
                logger.debug(f"📤 No Cache Hit - Total Input: {total_input_tokens} tokens")
        
        return cache_metrics if cache_metrics else None

    def start_chat_session(self, initial_messages: List[BaseMessage]) -> GeminiChatSession:
        """Starts a new chat session"""
        return GeminiChatSession(self.llm, initial_messages)
