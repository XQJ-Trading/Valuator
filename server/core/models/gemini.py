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
    """Global Gemini API Rate Limiter managing TPM limits per API key"""
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

        # Model TPM limits (Token per Minute)
        self.model_limits = {
            "gemini-2.5-pro": 2_000_000,
            "gemini-2.5-flash": 1_000_000,
            # Default fallback
            "default": 1_000_000
        }

        # Token usage history per model: [(timestamp, tokens), ...]
        self.usage_history = {
            "gemini-2.5-pro": [],
            "gemini-2.5-flash": []
        }

    def _get_model_key(self, model_name: str) -> str:
        """Normalize model name for key lookup"""
        model_name = model_name.lower()
        if "2.5-pro" in model_name or "2.5pro" in model_name:
            return "gemini-2.5-pro"
        elif "2.5-flash" in model_name or "2.5flash" in model_name:
            return "gemini-2.5-flash"
        else:
            return "gemini-2.5-flash"

    def _cleanup_old_records(self, model_key: str, current_time: float):
        """Remove records older than 1 minute"""
        minute_ago = current_time - 60.0
        if model_key not in self.usage_history:
            self.usage_history[model_key] = []

        self.usage_history[model_key] = [
            (timestamp, tokens)
            for timestamp, tokens in self.usage_history[model_key]
            if timestamp > minute_ago
        ]

    def _get_current_usage(self, model_key: str, current_time: float) -> int:
        """Calculate current 1-minute token usage"""
        self._cleanup_old_records(model_key, current_time)
        return sum(tokens for _, tokens in self.usage_history[model_key])

    async def wait_if_needed(self, model_name: str):
        """Wait if usage exceeds 70% threshold"""
        async with self._lock:
            model_key = self._get_model_key(model_name)
            current_time = time.time()
            limit = self.model_limits.get(model_key, self.model_limits["default"])

            current_usage = self._get_current_usage(model_key, current_time)
            threshold = int(limit * 0.7)  # 70% threshold

            if current_usage > threshold:
                # Calculate wait time from oldest record
                if self.usage_history[model_key]:
                    oldest_timestamp = min(timestamp for timestamp, _ in self.usage_history[model_key])
                    wait_time = max(0, 60.0 - (current_time - oldest_timestamp))

                    if wait_time > 0:
                        usage_percentage = (current_usage / limit) * 100
                        logger.info(f"🕐 Throttling (70%+ threshold) - Model: {model_name}, "
                                  f"Usage: {current_usage:,}/{limit:,} ({usage_percentage:.1f}%), "
                                  f"Threshold: {threshold:,}, Wait: {wait_time:.1f}s")
                        await asyncio.sleep(wait_time)

    def record_usage(self, model_name: str, tokens_used: int):
        """Record actual token usage after API call"""
        if tokens_used <= 0:
            return

        model_key = self._get_model_key(model_name)
        current_time = time.time()

        if model_key not in self.usage_history:
            self.usage_history[model_key] = []

        self.usage_history[model_key].append((current_time, tokens_used))
        self._cleanup_old_records(model_key, current_time)

        current_usage = sum(tokens for _, tokens in self.usage_history[model_key])
        limit = self.model_limits.get(model_key, self.model_limits["default"])
        usage_percentage = (current_usage / limit) * 100

        logger.debug(f"📊 Token usage - Model: {model_name}, "
                    f"Used: {tokens_used:,}, 1min total: {current_usage:,}/{limit:,} "
                    f"({usage_percentage:.1f}%)")


def get_rate_limiter() -> GlobalGeminiRateLimiter:
    """Return global rate limiter instance"""
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
    grounding_metadata: Optional[Dict[str, Any]] = Field(None, description="Search grounding metadata")


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

        # Rate limiting check
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_if_needed(self.model.model)

        response = await self.model.agenerate(
            messages=[self.history],
            callbacks=callbacks
        )

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

        grounding_metadata = self._extract_grounding_metadata(generation)
        code_execution_metadata = self._extract_code_execution_metadata(generation)

        # Record actual token usage
        if usage:
            total_tokens = self._extract_total_tokens(usage)
            if total_tokens > 0:
                rate_limiter.record_usage(self.model.model, total_tokens)

        # Save low-level request/response logs
        if config.gemini_low_level_request_logging:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"request_response_{timestamp}.json"
                filepath = os.path.join("logs", "gemini_low_level_request", filename)

                # Build request data
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

                # Build response data
                response_data = {
                    "content": content,
                    "usage": usage,
                    "message_count": len(self.history),
                    "grounding_metadata": grounding_metadata,
                    "code_execution_metadata": code_execution_metadata
                }

                # Complete request/response data
                full_data = {
                    "request": request_data,
                    "response": response_data,
                    "metadata": {
                        "session_id": id(self),
                        "total_messages": len(self.history)
                    }
                }

                # Save to file
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(full_data, f, ensure_ascii=False, indent=2)

                logger.debug(f"Saved request/response to: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to save request/response: {e}")

        self.history.append(AIMessage(content=content))

        return GeminiResponse(
            content=content,
            usage=usage,
            metadata={"model": self.model.model},
            grounding_metadata=grounding_metadata,
        )

    def _extract_grounding_metadata(self, generation) -> Optional[Dict[str, Any]]:
        """Extract search grounding metadata from response"""
        try:
            gen_info = getattr(generation, 'generation_info', None) or {}

            if 'candidates' in gen_info and len(gen_info['candidates']) > 0:
                candidate = gen_info['candidates'][0]

                if 'groundingMetadata' in candidate:
                    grounding_data = candidate['groundingMetadata']

                    metadata = {
                        "search_queries": [],
                        "grounding_chunks": [],
                        "grounding_supports": [],
                        "search_entry_point": None
                    }

                    if 'webSearchQueries' in grounding_data:
                        metadata["search_queries"] = grounding_data['webSearchQueries']

                    if 'searchEntryPoint' in grounding_data:
                        metadata["search_entry_point"] = grounding_data['searchEntryPoint']

                    if 'groundingChunks' in grounding_data:
                        for chunk in grounding_data['groundingChunks']:
                            chunk_info = {
                                "title": chunk.get('web', {}).get('title', ''),
                                "uri": chunk.get('web', {}).get('uri', ''),
                            }
                            metadata["grounding_chunks"].append(chunk_info)

                    # Extract grounding supports
                    if 'groundingSupports' in grounding_data:
                        supports = []
                        for support in grounding_data['groundingSupports']:
                            support_info = {
                                "segment": support.get('segment', {}),
                                "grounding_chunk_indices": support.get('groundingChunkIndices', [])
                            }
                            supports.append(support_info)
                        metadata["grounding_supports"] = supports

                    if metadata["search_queries"] or metadata["grounding_chunks"]:
                        logger.debug(f"Grounding metadata extracted: {len(metadata['search_queries'])} queries, {len(metadata['grounding_chunks'])} chunks")
                        return metadata

            return None

        except Exception as e:
            logger.warning(f"Failed to extract grounding metadata: {e}")
            return None

    def _extract_code_execution_metadata(self, generation) -> Optional[Dict[str, Any]]:
        """Extract code execution metadata (text, executableCode, codeExecutionResult)"""
        try:
            gen_info = getattr(generation, 'generation_info', None) or {}

            if 'candidates' in gen_info and len(gen_info['candidates']) > 0:
                candidate = gen_info['candidates'][0]

                if 'content' in candidate and 'parts' in candidate['content']:
                    parts = candidate['content']['parts']

                    metadata = {
                        "text_parts": [],
                        "executable_code_parts": [],
                        "code_execution_results": []
                    }

                    for part in parts:
                        if 'text' in part:
                            metadata["text_parts"].append(part['text'])

                        if 'executableCode' in part:
                            exec_code = part['executableCode']
                            code_info = {
                                "language": exec_code.get('language'),
                                "code": exec_code.get('code')
                            }
                            metadata["executable_code_parts"].append(code_info)

                        if 'codeExecutionResult' in part:
                            exec_result = part['codeExecutionResult']
                            result_info = {
                                "outcome": exec_result.get('outcome'),
                                "output": exec_result.get('output')
                            }
                            metadata["code_execution_results"].append(result_info)

                    if metadata["executable_code_parts"] or metadata["code_execution_results"]:
                        logger.debug(f"Code execution metadata extracted: {len(metadata['executable_code_parts'])} code parts, {len(metadata['code_execution_results'])} results")
                        return metadata

            return None

        except Exception as e:
            logger.warning(f"Failed to extract code execution metadata: {e}")
            return None

    def _extract_total_tokens(self, usage_metadata: Dict[str, Any]) -> int:
        """Extract total tokens from usage metadata"""
        if not usage_metadata:
            return 0

        if 'total_token_count' in usage_metadata:
            return usage_metadata['total_token_count']

        if 'total_tokens' in usage_metadata:
            return usage_metadata['total_tokens']

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
            # Configure base model
            model_kwargs = {
                "google_api_key": config.google_api_key,
                "model": self.model_name,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "top_p": config.top_p,
                "top_k": config.top_k,
                "streaming": True,
            }

            model_kwargs["tools"] = [
                {"google_search": {}},
                {"code_execution": {}}
            ]
            logger.info(f"Enabling Google Search grounding & code execution for model: {self.model_name}")

            self.llm = ChatGoogleGenerativeAI(**model_kwargs)
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

        if system_prompt and system_prompt.strip():
            messages.append(self.create_human_message(system_prompt))

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

        if current_input and current_input.strip():
            messages.append(self.create_human_message(current_input))

        return messages

    def start_chat_session(self, initial_messages: List[BaseMessage]) -> GeminiChatSession:
        """Starts a new chat session"""
        return GeminiChatSession(self.llm, initial_messages)
