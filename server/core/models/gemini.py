"""Gemini model integration for AI Agent"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncGenerator
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.callbacks import AsyncCallbackHandler
from pydantic import BaseModel, Field

from ..utils.config import config
from ..utils.logger import logger


class GlobalGeminiRateLimiter:
    """전역 Gemini API Rate Limiter - API key 단위로 TPM 제한을 관리"""
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        # 모델별 TPM 제한 (Token per Minute)
        self.model_limits = {
            "gemini-2.5-pro": 2_000_000,
            "gemini-2.5-flash": 1_000_000,
            # 기본값 (모델명 매칭이 안될 경우)
            "default": 1_000_000
        }
        
        # 모델별 토큰 사용 이력: [(timestamp, tokens), ...]
        self.usage_history = {
            "gemini-2.5-pro": [],
            "gemini-2.5-flash": []
        }
    
    def _get_model_key(self, model_name: str) -> str:
        """모델명을 정규화하여 키로 사용"""
        model_name = model_name.lower()
        if "2.5-pro" in model_name or "2.5pro" in model_name:
            return "gemini-2.5-pro"
        elif "2.5-flash" in model_name or "2.5flash" in model_name:
            return "gemini-2.5-flash"
        else:
            return "gemini-2.5-flash"  # 기본값으로 Flash 사용
    
    def _cleanup_old_records(self, model_key: str, current_time: float):
        """1분 이상 된 기록들을 정리"""
        minute_ago = current_time - 60.0
        if model_key not in self.usage_history:
            self.usage_history[model_key] = []
        
        self.usage_history[model_key] = [
            (timestamp, tokens) 
            for timestamp, tokens in self.usage_history[model_key]
            if timestamp > minute_ago
        ]
    
    def _get_current_usage(self, model_key: str, current_time: float) -> int:
        """현재 1분간의 토큰 사용량 계산"""
        self._cleanup_old_records(model_key, current_time)
        return sum(tokens for _, tokens in self.usage_history[model_key])
    
    async def wait_if_needed(self, model_name: str):
        """현재 사용량이 70% 초과시 대기"""
        async with self._lock:
            model_key = self._get_model_key(model_name)
            current_time = time.time()
            limit = self.model_limits.get(model_key, self.model_limits["default"])
            
            current_usage = self._get_current_usage(model_key, current_time)
            threshold = int(limit * 0.7)  # 70% 임계값
            
            if current_usage > threshold:
                # 가장 오래된 기록의 시간을 찾아서 대기 시간 계산
                if self.usage_history[model_key]:
                    oldest_timestamp = min(timestamp for timestamp, _ in self.usage_history[model_key])
                    wait_time = max(0, 60.0 - (current_time - oldest_timestamp))
                    
                    if wait_time > 0:
                        usage_percentage = (current_usage / limit) * 100
                        logger.info(f"🕐 70% 임계값 초과 대기중 - 모델: {model_name}, "
                                  f"현재 사용량: {current_usage:,}/{limit:,} ({usage_percentage:.1f}%), "
                                  f"임계값: {threshold:,}, 대기 시간: {wait_time:.1f}초")
                        await asyncio.sleep(wait_time)
    
    def record_usage(self, model_name: str, tokens_used: int):
        """API 호출 후 실제 토큰 사용량을 기록"""
        if tokens_used <= 0:
            return
            
        model_key = self._get_model_key(model_name)
        current_time = time.time()
        
        if model_key not in self.usage_history:
            self.usage_history[model_key] = []
            
        self.usage_history[model_key].append((current_time, tokens_used))
        
        # 기록 정리
        self._cleanup_old_records(model_key, current_time)
        
        # 현재 사용량 로깅
        current_usage = sum(tokens for _, tokens in self.usage_history[model_key])
        limit = self.model_limits.get(model_key, self.model_limits["default"])
        usage_percentage = (current_usage / limit) * 100
        
        logger.debug(f"📊 토큰 사용량 기록 - 모델: {model_name}, "
                    f"사용: {tokens_used:,}, 1분간 총 사용량: {current_usage:,}/{limit:,} "
                    f"({usage_percentage:.1f}%)")


def get_rate_limiter() -> GlobalGeminiRateLimiter:
    """전역 rate limiter 인스턴스를 반환"""
    return GlobalGeminiRateLimiter()


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
        
        # Rate limiting - 70% 임계값 체크 및 대기
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_if_needed(self.model.model)
        
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

        # Rate limiting - 실제 사용된 토큰 수를 기록
        if usage:
            total_tokens = self._extract_total_tokens(usage)
            if total_tokens > 0:
                rate_limiter.record_usage(self.model.model, total_tokens)

        # save log of gemini_low_level_request as file IO
        if config.gemini_low_level_request_logging:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"request_response_{timestamp}.json"
                filepath = os.path.join("logs", "gemini_low_level_request", filename)

                # 요청 데이터 구성
                request_data = {
                    "timestamp": timestamp,
                    "model": self.model.model,
                    "messages": [
                        {
                            "type": msg.__class__.__name__,
                            "content": msg.content
                        } for msg in self.history
                    ],
                    "model_config": {
                        "temperature": getattr(self.model, 'temperature', None),
                        "max_output_tokens": getattr(self.model, 'max_output_tokens', None),
                        "top_p": getattr(self.model, 'top_p', None),
                        "top_k": getattr(self.model, 'top_k', None)
                    }
                }

                # 응답 데이터 구성
                response_data = {
                    "content": content,
                    "usage": usage,
                    "message_count": len(self.history)
                }

                # 요청과 응답을 모두 포함한 전체 데이터
                full_data = {
                    "request": request_data,
                    "response": response_data,
                    "metadata": {
                        "session_id": id(self),  # 세션 식별용
                        "total_messages": len(self.history)
                    }
                }

                # 파일 저장
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(full_data, f, ensure_ascii=False, indent=2)

                logger.debug(f"요청과 응답을 파일로 저장했습니다: {filepath}")
            except Exception as e:
                logger.warning(f"요청/응답 파일 저장 실패: {e}")
        
        self.history.append(AIMessage(content=content))
        
        return GeminiResponse(
            content=content,
            usage=usage,
            metadata={"model": self.model.model},
        )
    
    def _extract_total_tokens(self, usage_metadata: Dict[str, Any]) -> int:
        """usage metadata에서 총 토큰 사용량 추출"""
        if not usage_metadata:
            return 0
        
        # Google API 형식
        if 'total_token_count' in usage_metadata:
            return usage_metadata['total_token_count']
        
        # LangChain 형식
        if 'total_tokens' in usage_metadata:
            return usage_metadata['total_tokens']
        
        # 분리된 형식에서 합산
        input_tokens = usage_metadata.get('input_tokens', 0) or usage_metadata.get('prompt_token_count', 0)
        output_tokens = usage_metadata.get('output_tokens', 0) or usage_metadata.get('candidates_token_count', 0)
        
        return input_tokens + output_tokens

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
            )
            logger.info(f"Initialized Gemini model: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            raise
     
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

        # Add system prompt as HumanMessage (Gemini doesn't support SystemMessage)
        if system_prompt and system_prompt.strip():
            messages.append(self.create_human_message(system_prompt))

        # Add conversation history - filter out empty content
        for turn in conversation_history:
            role = turn.get("role")
            content = turn.get("content", "")

            # Skip empty or whitespace-only content
            if not content or not content.strip():
                continue

            if role == "user":
                messages.append(self.create_human_message(content))
            elif role == "assistant":
                messages.append(self.create_ai_message(content))

        # Add current input - only if it has content
        if current_input and current_input.strip():
            messages.append(self.create_human_message(current_input))

        return messages

    def start_chat_session(self, initial_messages: List[BaseMessage]) -> GeminiChatSession:
        """Starts a new chat session"""
        return GeminiChatSession(self.llm, initial_messages)
