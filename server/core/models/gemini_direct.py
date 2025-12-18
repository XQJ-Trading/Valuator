"""Direct Google Gemini integration (supports legacy and new SDKs)"""

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
    """
    Direct Google Gemini SDK wrapper

    - Uses google-genai for Gemini 3.x models (supports thinking_level)
    - Falls back to google-generativeai for legacy models
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
        self.model_name = model
        self.streaming_enabled = streaming
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.top_p = top_p
        self.top_k = top_k

        self.using_google_genai = self._should_use_google_genai(model)
        normalized_thinking = self._normalize_thinking_level(thinking_level)

        if self.using_google_genai:
            # New Google AI Python SDK path (google-genai) for Gemini 3.x
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

            try:
                generation_kwargs = {
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "top_p": top_p,
                    "top_k": top_k,
                }

                # Add thinking config only if supported by the installed SDK
                thinking_supported = False
                if thinking_config:
                    model_fields = getattr(
                        genai_types.GenerateContentConfig, "model_fields", {}
                    )
                    thinking_supported = "thinking" in model_fields
                    if thinking_supported:
                        generation_kwargs["thinking"] = thinking_config
                    else:
                        logger.warning(
                            "Thinking config is requested but this google-genai version "
                            "does not support the 'thinking' field. Skipping."
                        )

                self._genai_client = google_genai.Client(api_key=google_api_key)
                self._generation_config = genai_types.GenerateContentConfig(
                    **generation_kwargs
                )
                self.thinking_level = (
                    normalized_thinking
                    if thinking_config and thinking_supported
                    else None
                )
                logger.info(f"Initialized Gemini (google-genai) model: {model}")
                if self.thinking_level:
                    logger.info(f"  - Thinking level: {self.thinking_level}")
                elif normalized_thinking:
                    logger.info("Thinking level requested but not applied.")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini (google-genai) model: {e}")
                raise
        else:
            # Legacy google.generativeai SDK path
            try:
                import google.generativeai as legacy_genai
            except ImportError as e:
                raise ImportError(
                    "google-generativeai is required for Gemini legacy models. "
                    "Install with `pip install google-generativeai`."
                ) from e

            if normalized_thinking:
                logger.warning(
                    "Thinking level is only supported on Gemini 3.x models via google-genai. "
                    "Ignoring thinking_level for legacy SDK models."
                )

            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "top_p": top_p,
                "top_k": top_k,
            }

            try:
                legacy_genai.configure(api_key=google_api_key)
                self.model = legacy_genai.GenerativeModel(
                    model_name=model, generation_config=generation_config
                )
                self.thinking_level = None
                self._generation_config = generation_config

                logger.info(f"Initialized Gemini Generative AI model: {model}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Generative AI model: {e}")
                raise

    def _convert_to_content_objects(self, contents_dict: List[Dict[str, Any]]):
        """
        Convert dictionary format to Content objects for google-genai SDK

        Args:
            contents_dict: List of dictionaries with 'role' and 'parts'

        Returns:
            List of Content objects or dictionaries (depending on SDK)
        """
        if not self.using_google_genai:
            return contents_dict

        from google.genai import types as genai_types

        content_objects = []
        for content_dict in contents_dict:
            role = content_dict.get("role", "user")
            parts = content_dict.get("parts", [])

            # Convert string parts to Part objects
            # The SDK expects Part objects with text attribute
            part_objects = []
            for part in parts:
                if isinstance(part, str):
                    # Create Part object from string
                    part_objects.append(genai_types.Part(text=part))
                elif isinstance(part, dict):
                    # If it's already a dict with text, convert to Part
                    if "text" in part:
                        part_objects.append(genai_types.Part(text=part["text"]))
                    else:
                        # Try to create Part from dict directly
                        part_objects.append(genai_types.Part(**part))
                else:
                    # If already a Part object, use it directly
                    part_objects.append(part)

            # Create Content object with role and parts
            # Use role enum if available, otherwise string
            try:
                # Try to use role as enum if available
                role_enum = getattr(genai_types.Role, role.upper(), role)
                content_obj = genai_types.Content(role=role_enum, parts=part_objects)
            except (AttributeError, TypeError):
                # Fall back to string role
                content_obj = genai_types.Content(role=role, parts=part_objects)

            content_objects.append(content_obj)

        return content_objects

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
            # Make API call in thread pool (SDKs are synchronous)
            if self.using_google_genai:
                # Convert dictionaries to Content objects for new SDK
                content_objects = self._convert_to_content_objects(contents)
                response = await asyncio.to_thread(
                    self._genai_client.models.generate_content,
                    model=self.model_name,
                    contents=content_objects,
                    config=self._generation_config,
                )
            else:
                response = await asyncio.to_thread(
                    self.model.generate_content, contents
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
                if self.using_google_genai:
                    # Convert dictionaries to Content objects for new SDK
                    content_objects = self._convert_to_content_objects(contents)
                    return self._genai_client.models.generate_content(
                        model=self.model_name,
                        contents=content_objects,
                        config=self._generation_config,
                        stream=True,
                    )
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
            if self.using_google_genai:
                # Convert dictionaries to Content objects for new SDK
                content_objects = self._convert_to_content_objects(contents)
                response = await asyncio.to_thread(
                    self._genai_client.models.generate_content,
                    model=self.model_name,
                    contents=content_objects,
                    config=self._generation_config,
                )
            else:
                response = await asyncio.to_thread(
                    self.model.generate_content, contents
                )

            # Convert and return
            ai_message = google_to_langchain_message(response, extract_thinking=True)
            return ai_message

        except Exception as e:
            logger.error(f"Error in Gemini Direct Model ainvoke: {e}")
            raise

    def _should_use_google_genai(self, model_name: str) -> bool:
        """Gemini 3.x models require the new google-genai SDK."""
        return model_name.startswith("gemini-3")

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
