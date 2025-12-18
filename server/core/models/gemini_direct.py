"""Direct Google Gemini integration via google-genai (Gemini 3.x only)"""

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import Generation, LLMResult

from ..utils.logger import logger
from ..utils.message_converter import (
    google_to_langchain_message,
    langchain_to_google_messages,
)


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

        try:
            # Make API call in thread pool (SDK is synchronous)
            content_objects = self._convert_to_content_objects(contents)
            response = await asyncio.to_thread(
                self._genai_client.models.generate_content,
                model=self.model_name,
                contents=content_objects,
                config=self._generation_config,
            )

            # Convert response to LangChain format
            ai_message = google_to_langchain_message(response, extract_thinking=True)

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

        try:
            # Make API call
            content_objects = self._convert_to_content_objects(contents)
            response = await asyncio.to_thread(
                self._genai_client.models.generate_content,
                model=self.model_name,
                contents=content_objects,
                config=self._generation_config,
            )

            # Convert and return
            ai_message = google_to_langchain_message(response, extract_thinking=True)
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
