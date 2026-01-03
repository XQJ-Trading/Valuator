"""Direct Google Gemini integration via google-genai (Gemini 3.x only)"""

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import Generation, LLMResult
from pydantic import BaseModel, Field

from ..utils.config import config
from ..utils.logger import logger
from ..utils.message_converter import (
    google_to_langchain_message,
    langchain_to_google_messages,
)


def _save_raw_api_log(
    request_data: Dict[str, Any],
    response_data: Dict[str, Any],
    model_name: str,
) -> None:
    """Save raw API request and response to file"""
    if not config.gemini_low_level_request_logging:
        return

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"request_response_{timestamp}.json"
        filepath = os.path.join("logs", "gemini_low_level_request", filename)
        if os.path.exists(filepath):
            unique_id = uuid.uuid4().hex
            filename = f"request_response_{timestamp}_{unique_id}.json"
            filepath = os.path.join("logs", "gemini_low_level_request", filename)

        full_data = {
            "timestamp": timestamp,
            "model": model_name,
            "request": request_data,
            "response": response_data,
        }

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2, default=str)

        logger.debug(f"Raw API 요청/응답을 파일로 저장했습니다: {filepath}")
    except Exception as e:
        logger.warning(f"Raw API 로그 저장 실패: {e}")


class GlobalGeminiRateLimiter:
    """전역 Gemini API Rate Limiter - API key 단위로 TPM 제한을 관리"""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        # 모델별 TPM 제한 (Token per Minute)
        self.model_limits = {
            # 기본값 (모델명 매칭이 안될 경우)
            "default": 1_000_000,
        }

        # 모델별 토큰 사용 이력: [(timestamp, tokens), ...]
        self.usage_history = {}

    def _get_model_key(self, model_name: str) -> str:
        """모델명을 정규화하여 키로 사용"""
        # Gemini 3 모델만 지원
        return "default"

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
                    oldest_timestamp = min(
                        timestamp for timestamp, _ in self.usage_history[model_key]
                    )
                    wait_time = max(0, 60.0 - (current_time - oldest_timestamp))

                    if wait_time > 0:
                        usage_percentage = (current_usage / limit) * 100
                        logger.info(
                            f"🕐 70% 임계값 초과 대기중 - 모델: {model_name}, "
                            f"현재 사용량: {current_usage:,}/{limit:,} ({usage_percentage:.1f}%), "
                            f"임계값: {threshold:,}, 대기 시간: {wait_time:.1f}초"
                        )
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

        logger.debug(
            f"📊 토큰 사용량 기록 - 모델: {model_name}, "
            f"사용: {tokens_used:,}, 1분간 총 사용량: {current_usage:,}/{limit:,} "
            f"({usage_percentage:.1f}%)"
        )


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


class GeminiDirectModel:
    """Direct Google Gemini SDK wrapper (google-genai only)"""

    def __init__(
        self,
        model: str,
        google_api_key: str,
        temperature: float = 1.0,
        max_output_tokens: int = 2048,
        top_p: float = 0.8,
        top_k: int = 40,
        thinking_level: Optional[str] = None,
        streaming: bool = True,
        **kwargs,
    ):
        """
        Initialize Gemini Direct Model

        Args:
            model: Model name (e.g., 'gemini-3-pro-preview', 'gemini-3-flash-preview')
            google_api_key: Google API key
            temperature: Temperature for generation (0.0-1.0)
            max_output_tokens: Maximum tokens to generate
            top_p: Top-p sampling parameter
            top_k: Top-k sampling parameter
            thinking_level: Thinking level for Gemini3 ('high', 'low', or None)
            streaming: Whether to support streaming
            **kwargs: Additional parameters
        """
        self.model_name = model
        self.streaming_enabled = streaming
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.top_p = top_p
        self.top_k = top_k

        normalized_thinking = self._normalize_thinking_level(thinking_level)

        self._init_google_genai(
            model=model,
            google_api_key=google_api_key,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            top_k=top_k,
            normalized_thinking=normalized_thinking,
        )

    def _convert_to_content_objects(self, contents_dict: List[Dict[str, Any]]):
        from google.genai import types as genai_types

        converted = []
        for item in contents_dict:
            parts = [
                p if isinstance(p, genai_types.Part) else genai_types.Part(text=str(p))
                for p in item.get("parts", [])
            ]
            converted.append(
                genai_types.Content(role=item.get("role", "user"), parts=parts)
            )
        return converted

    async def agenerate(
        self,
        messages: List[List[BaseMessage]],
        callbacks: Optional[List] = None,
        **kwargs,
    ) -> LLMResult:
        """
        Generate response asynchronously (LangChain-compatible interface)

        Args:
            messages: List of message lists (LangChain format)
            callbacks: Optional callbacks (not fully supported in direct API)
            **kwargs: Additional parameters

        Returns:
            LLMResult with generations
        """
        # LangChain passes messages as List[List[BaseMessage]]
        # We process the first list
        message_list = messages[0] if messages else []

        # Convert messages to Google API format
        contents = langchain_to_google_messages(message_list)

        # Rate limiting - 70% 임계값 체크 및 대기
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_if_needed(self.model_name)

        try:
            # Prepare request data for logging
            request_data = {
                "contents": contents,
                "generation_config": {
                    "temperature": self.temperature,
                    "max_output_tokens": self.max_output_tokens,
                    "top_p": self.top_p,
                    "top_k": self.top_k,
                },
            }

            # Make API call in thread pool (SDK is synchronous)
            content_objects = self._convert_to_content_objects(contents)
            response = await asyncio.to_thread(
                self._genai_client.models.generate_content,
                model=self.model_name,
                contents=content_objects,
                config=self._generation_config,
            )

            # Prepare response data for logging
            response_data = {
                "text": getattr(response, "text", None),
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": part.text}
                                for part in candidate.content.parts
                                if hasattr(part, "text")
                            ]
                        },
                        "finish_reason": str(getattr(candidate, "finish_reason", None)),
                        "safety_ratings": [
                            {
                                "category": str(rating.category),
                                "probability": str(rating.probability),
                            }
                            for rating in (getattr(candidate, "safety_ratings", None) or [])
                        ],
                    }
                    for candidate in (getattr(response, "candidates", None) or [])
                ],
                "usage_metadata": {
                    "prompt_token_count": getattr(
                        response.usage_metadata, "prompt_token_count", 0
                    ),
                    "candidates_token_count": getattr(
                        response.usage_metadata, "candidates_token_count", 0
                    ),
                    "total_token_count": getattr(
                        response.usage_metadata, "total_token_count", 0
                    ),
                }
                if hasattr(response, "usage_metadata")
                else None,
                "prompt_feedback": str(getattr(response, "prompt_feedback", None)),
            }

            # Save raw API log
            _save_raw_api_log(request_data, response_data, self.model_name)

            # Convert response to LangChain format
            ai_message = google_to_langchain_message(response, extract_thinking=True)

            # Rate limiting - 실제 사용된 토큰 수를 기록
            if hasattr(ai_message, "usage_metadata") and ai_message.usage_metadata:
                total_tokens = ai_message.usage_metadata.get("total_tokens", 0)
                if total_tokens > 0:
                    rate_limiter.record_usage(self.model_name, total_tokens)

            # Create Generation object
            generation = Generation(
                text=ai_message.content,
                message=ai_message,
                generation_info={
                    "finish_reason": (
                        ai_message.response_metadata.get("finish_reason")
                        if hasattr(ai_message, "response_metadata")
                        else None
                    ),
                    "safety_ratings": (
                        ai_message.response_metadata.get("safety_ratings")
                        if hasattr(ai_message, "response_metadata")
                        else None
                    ),
                },
            )

            # Create LLMResult
            llm_result = LLMResult(
                generations=[[generation]],
                llm_output={
                    "model_name": self.model_name,
                    "thinking_level": self.thinking_level,
                },
            )

            return llm_result

        except Exception as e:
            logger.error(f"Error in Gemini Direct Model agenerate: {e}")
            raise

    async def astream(
        self, messages: List[BaseMessage], callbacks: Optional[List] = None, **kwargs
    ) -> AsyncGenerator[AIMessage, None]:
        """
        Stream response asynchronously

        Args:
            messages: List of messages (single conversation)
            callbacks: Optional callbacks
            **kwargs: Additional parameters

        Yields:
            AIMessage chunks with content
        """
        # Convert messages to Google API format
        contents = langchain_to_google_messages(messages)

        try:
            # Generate with streaming in thread pool
            def _generate_stream():
                content_objects = self._convert_to_content_objects(contents)
                return self._genai_client.models.generate_content(
                    model=self.model_name,
                    contents=content_objects,
                    config=self._generation_config,
                    stream=True,
                )

            response_stream = await asyncio.to_thread(_generate_stream)

            # Stream chunks
            for chunk in response_stream:
                if hasattr(chunk, "text") and chunk.text:
                    # Create AIMessage chunk
                    ai_chunk = AIMessage(content=chunk.text)
                    yield ai_chunk

        except Exception as e:
            logger.error(f"Error in Gemini Direct Model astream: {e}")
            raise

    async def ainvoke(
        self, messages: List[BaseMessage], callbacks: Optional[List] = None, **kwargs
    ) -> AIMessage:
        """
        Invoke model with messages and return AIMessage

        Args:
            messages: List of messages
            callbacks: Optional callbacks
            **kwargs: Additional parameters

        Returns:
            AIMessage with response
        """
        # Convert messages to Google API format
        contents = langchain_to_google_messages(messages)

        # Rate limiting - 70% 임계값 체크 및 대기
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_if_needed(self.model_name)

        try:
            # Prepare request data for logging
            request_data = {
                "contents": contents,
                "generation_config": {
                    "temperature": self.temperature,
                    "max_output_tokens": self.max_output_tokens,
                    "top_p": self.top_p,
                    "top_k": self.top_k,
                },
            }

            # Make API call
            content_objects = self._convert_to_content_objects(contents)
            response = await asyncio.to_thread(
                self._genai_client.models.generate_content,
                model=self.model_name,
                contents=content_objects,
                config=self._generation_config,
            )

            # Prepare response data for logging
            response_data = {
                "text": getattr(response, "text", None),
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": part.text}
                                for part in candidate.content.parts
                                if hasattr(part, "text")
                            ]
                        },
                        "finish_reason": str(getattr(candidate, "finish_reason", None)),
                        "safety_ratings": [
                            {
                                "category": str(rating.category),
                                "probability": str(rating.probability),
                            }
                            for rating in (getattr(candidate, "safety_ratings", None) or [])
                        ],
                    }
                    for candidate in (getattr(response, "candidates", None) or [])
                ],
                "usage_metadata": {
                    "prompt_token_count": getattr(
                        response.usage_metadata, "prompt_token_count", 0
                    ),
                    "candidates_token_count": getattr(
                        response.usage_metadata, "candidates_token_count", 0
                    ),
                    "total_token_count": getattr(
                        response.usage_metadata, "total_token_count", 0
                    ),
                }
                if hasattr(response, "usage_metadata")
                else None,
                "prompt_feedback": str(getattr(response, "prompt_feedback", None)),
            }

            # Save raw API log
            _save_raw_api_log(request_data, response_data, self.model_name)

            # Convert and return
            ai_message = google_to_langchain_message(response, extract_thinking=True)

            # Rate limiting - 실제 사용된 토큰 수를 기록
            if hasattr(ai_message, "usage_metadata") and ai_message.usage_metadata:
                total_tokens = ai_message.usage_metadata.get("total_tokens", 0)
                if total_tokens > 0:
                    rate_limiter.record_usage(self.model_name, total_tokens)

            return ai_message

        except Exception as e:
            logger.error(f"Error in Gemini Direct Model ainvoke: {e}")
            raise

    def _normalize_thinking_level(self, thinking_level: Optional[str]) -> Optional[str]:
        """Validate and normalize thinking level."""
        if thinking_level is None:
            return None

        normalized = thinking_level.lower()
        if normalized not in ("high", "low"):
            raise ValueError(
                f"Invalid thinking_level: '{thinking_level}'. "
                f"Must be 'high', 'low', or None."
            )
        return normalized

    def _build_thinking_config(self, genai_types, thinking_level: Optional[str]):
        """Build thinking config for google-genai if requested."""
        if not thinking_level:
            return None

        budget_tokens = 4000 if thinking_level == "low" else 12000

        try:
            return genai_types.ThinkingConfig(budget_tokens=budget_tokens)
        except Exception as e:
            logger.warning(
                f"Failed to apply thinking_level '{thinking_level}': {e}. "
                "Continuing without thinking config."
            )
            return None

    def _init_google_genai(
        self,
        model: str,
        google_api_key: str,
        temperature: float,
        max_output_tokens: int,
        top_p: float,
        top_k: int,
        normalized_thinking: Optional[str],
    ):
        try:
            from google import genai as google_genai
            from google.genai import types as genai_types
        except ImportError as e:
            raise ImportError(
                "google-genai is required for Gemini 3.x models. "
                "Install with `pip install google-genai`."
            ) from e

        thinking_config = self._build_thinking_config(
            genai_types=genai_types, thinking_level=normalized_thinking
        )

        generation_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "top_p": top_p,
            "top_k": top_k,
        }

        supports_thinking = "thinking" in getattr(
            genai_types.GenerateContentConfig, "model_fields", {}
        )
        if thinking_config and supports_thinking:
            generation_kwargs["thinking"] = thinking_config
        elif thinking_config:
            logger.warning(
                "Thinking config requested but this google-genai version "
                "does not support the 'thinking' field. Skipping."
            )

        self._genai_client = google_genai.Client(api_key=google_api_key)
        self._generation_config = genai_types.GenerateContentConfig(
            **generation_kwargs
        )
        self.thinking_level = normalized_thinking if "thinking" in generation_kwargs else None
        logger.info(f"Initialized Gemini (google-genai) model: {model}")
        if self.thinking_level:
            logger.info(f"  - Thinking level: {self.thinking_level}")
        elif normalized_thinking:
            logger.info("Thinking level requested but not applied.")


class GeminiDirectChatModel:
    """
    Chat model wrapper for easier session-based usage

    This is a convenience class that maintains conversation history
    and provides a simpler interface for chat interactions.
    """

    def __init__(self, model: str, google_api_key: str, **kwargs):
        """
        Initialize chat model

        Args:
            model: Model name
            google_api_key: Google API key
            **kwargs: Additional parameters passed to GeminiDirectModel
        """
        self.base_model = GeminiDirectModel(
            model=model, google_api_key=google_api_key, **kwargs
        )
        self.conversation_history: List[BaseMessage] = []

    async def send_message(
        self, message: str, callbacks: Optional[List] = None
    ) -> AIMessage:
        """
        Send a message and get response

        Args:
            message: User message
            callbacks: Optional callbacks

        Returns:
            AIMessage response
        """
        from langchain_core.messages import HumanMessage

        # Add user message to history
        user_msg = HumanMessage(content=message)
        self.conversation_history.append(user_msg)

        # Get response
        response = await self.base_model.ainvoke(
            messages=self.conversation_history, callbacks=callbacks
        )

        # Add AI response to history
        self.conversation_history.append(response)

        return response

    async def stream_message(
        self, message: str, callbacks: Optional[List] = None
    ) -> AsyncGenerator[str, None]:
        """
        Send a message and stream response

        Args:
            message: User message
            callbacks: Optional callbacks

        Yields:
            Response chunks
        """
        from langchain_core.messages import HumanMessage

        # Add user message to history
        user_msg = HumanMessage(content=message)
        self.conversation_history.append(user_msg)

        # Stream response
        full_content = ""
        async for chunk in self.base_model.astream(
            messages=self.conversation_history, callbacks=callbacks
        ):
            if chunk.content:
                full_content += chunk.content
                yield chunk.content

        # Add complete AI response to history
        ai_msg = AIMessage(content=full_content)
        self.conversation_history.append(ai_msg)

    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def get_history(self) -> List[BaseMessage]:
        """Get conversation history"""
        return self.conversation_history.copy()


class GeminiChatSession:
    """Represents a chat session with the Gemini model"""

    def __init__(self, model, initial_messages: List[BaseMessage]):
        self.model = model
        self.history: List[BaseMessage] = initial_messages

    async def send_message(
        self, message: str, callbacks: Optional[List] = None
    ) -> GeminiResponse:
        """Send a message in the session and get a response"""
        self.history.append(HumanMessage(content=message))

        # Rate limiting - 70% 임계값 체크 및 대기
        rate_limiter = get_rate_limiter()
        model_name = getattr(self.model, "model_name", None) or "unknown"
        await rate_limiter.wait_if_needed(model_name)

        response = await self.model.agenerate(
            messages=[self.history], callbacks=callbacks
        )

        # Extract content from response
        generation = response.generations[0][0]
        message_obj = getattr(generation, "message", None)
        if message_obj and getattr(message_obj, "content", None) is not None:
            content = _normalize_content(message_obj.content)
        else:
            content = _normalize_content(getattr(generation, "text", ""))

        # Extract usage from AIMessage.usage_metadata
        usage = None
        if message_obj is not None:
            usage = getattr(message_obj, "usage_metadata", None)
        if usage is None:
            gen_info = getattr(generation, "generation_info", None) or {}
            if isinstance(gen_info, dict):
                usage = gen_info.get("usage_metadata")

        # Rate limiting - 실제 사용된 토큰 수를 기록
        if usage:
            total_tokens = self._extract_total_tokens(usage)
            if total_tokens > 0:
                model_name = getattr(self.model, "model_name", None) or "unknown"
                rate_limiter.record_usage(model_name, total_tokens)

        self.history.append(AIMessage(content=content))

        model_name = getattr(self.model, "model_name", None) or "unknown"

        return GeminiResponse(
            content=content,
            usage=usage,
            metadata={"model": model_name},
        )

    def _extract_total_tokens(self, usage_metadata: Dict[str, Any]) -> int:
        """usage metadata에서 총 토큰 사용량 추출"""
        if not usage_metadata:
            return 0

        # Google API 형식
        if "total_token_count" in usage_metadata:
            return usage_metadata["total_token_count"]

        # LangChain 형식
        if "total_tokens" in usage_metadata:
            return usage_metadata["total_tokens"]

        # 분리된 형식에서 합산
        input_tokens = usage_metadata.get("input_tokens", 0) or usage_metadata.get(
            "prompt_token_count", 0
        )
        output_tokens = usage_metadata.get("output_tokens", 0) or usage_metadata.get(
            "candidates_token_count", 0
        )

        return input_tokens + output_tokens

    async def stream_message(
        self, message: str, callbacks: Optional[List] = None
    ) -> AsyncGenerator[str, None]:
        """Send a message and stream the response"""
        self.history.append(HumanMessage(content=message))

        streamed_content = ""
        yielded_any = False
        async for chunk in self.model.astream(
            messages=self.history, callbacks=callbacks
        ):
            if hasattr(chunk, "content") and chunk.content:
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

    def __init__(
        self, model_name: Optional[str] = None, thinking_level: Optional[str] = None
    ):
        """
        Initialize Gemini model

        Args:
            model_name: Model name to use (defaults to config value)
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)
        """
        self.model_name = model_name or config.agent_model
        self.thinking_level = thinking_level
        self.llm = None
        self._initialize_model()

    def _initialize_model(self):
        """Initialize the Gemini model"""
        try:
            # Always use direct Google Generative AI SDK
            self.llm = GeminiDirectModel(
                model=self.model_name,
                google_api_key=config.google_api_key,
                temperature=config.temperature,
                max_output_tokens=config.max_tokens,
                top_p=config.top_p,
                top_k=config.top_k,
                thinking_level=self.thinking_level,
                streaming=True,
            )
            logger.info(f"Initialized Gemini Direct API model: {self.model_name}")
            if self.thinking_level:
                logger.info(f"Thinking level enabled: {self.thinking_level}")
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
        current_input: str,
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

    def start_chat_session(
        self, initial_messages: List[BaseMessage]
    ) -> GeminiChatSession:
        """Starts a new chat session"""
        return GeminiChatSession(self.llm, initial_messages)
