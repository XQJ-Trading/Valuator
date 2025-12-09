"""Direct Google Generative AI SDK integration (without LangChain wrapper)"""

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

import google.generativeai as genai
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import Generation, LLMResult

from ..utils.logger import logger
from ..utils.message_converter import (
    google_to_langchain_message,
    langchain_to_google_messages,
)


class GeminiDirectModel:
    """
    Direct Google Generative AI SDK wrapper

    This class provides a LangChain-compatible interface while using
    Google's Generative AI SDK directly, allowing better control and
    access to latest features like thinking parameter.
    """

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
        # Configure API key
        genai.configure(api_key=google_api_key)

        # Validate thinking_level if provided
        # Note: thinking_level is not supported in google.generativeai SDK
        # It requires google.genai SDK (newer version)
        if thinking_level is not None:
            thinking_level_lower = thinking_level.lower()
            if thinking_level_lower not in ("high", "low"):
                raise ValueError(
                    f"Invalid thinking_level: '{thinking_level}'. "
                    f"Must be 'high', 'low', or None. "
                    f"Note: thinking_level is only supported for Gemini 3.0 models."
                )
            thinking_level = thinking_level_lower
            # Warn that thinking_level is not supported in current SDK
            logger.warning(
                f"thinking_level '{thinking_level}' is requested but not supported in google.generativeai SDK. "
                f"To use thinking_level, upgrade to google.genai SDK. "
                f"Continuing without thinking_level..."
            )
            # Set to None to avoid errors
            thinking_level = None

        # Build generation config (thinking_level is not supported in GenerationConfig)
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "top_p": top_p,
            "top_k": top_k,
        }

        # Create model instance
        try:
            self.model = genai.GenerativeModel(
                model_name=model, generation_config=generation_config
            )
            self.model_name = model
            self.streaming_enabled = streaming
            self.thinking_level = thinking_level
            # Store configuration parameters as instance attributes for inspection
            self.temperature = temperature
            self.max_output_tokens = max_output_tokens
            self.top_p = top_p
            self.top_k = top_k

            logger.info(f"Initialized Gemini Direct Model: {model}")
            if thinking_level:
                logger.info(f"  - Thinking level: {thinking_level}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini Direct Model: {e}")
            raise

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
            # Make API call in thread pool (Google SDK is synchronous)
            # Note: thinking_level is not supported in google.generativeai SDK
            response = await asyncio.to_thread(self.model.generate_content, contents)

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
                return self.model.generate_content(contents, stream=True)

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
            # Note: thinking_level is not supported in google.generativeai SDK
            response = await asyncio.to_thread(self.model.generate_content, contents)

            # Convert and return
            ai_message = google_to_langchain_message(response, extract_thinking=True)
            return ai_message

        except Exception as e:
            logger.error(f"Error in Gemini Direct Model ainvoke: {e}")
            raise


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
