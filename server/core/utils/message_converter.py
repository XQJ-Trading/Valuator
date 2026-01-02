"""Message converter between LangChain and Google Generative AI formats"""

from collections.abc import Iterable
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage


def langchain_to_google_messages(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """
    Convert LangChain messages to Google Generative AI format

    Args:
        messages: List of LangChain BaseMessage objects

    Returns:
        List of Google API content dictionaries

    Note:
        - SystemMessage is converted to the first HumanMessage (Gemini doesn't support SystemMessage)
        - Messages alternate between 'user' and 'model' roles
    """
    contents = []
    system_parts = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            # Collect system messages to prepend to first user message
            if msg.content and str(msg.content).strip():
                system_parts.append(str(msg.content))
        elif isinstance(msg, HumanMessage):
            content = str(msg.content) if msg.content else ""
            # Skip empty messages
            if not content.strip() and not system_parts:
                continue
            # Prepend system messages to first user message
            if system_parts:
                content = "\n\n".join(system_parts) + "\n\n" + content
                system_parts = []
            # Only add non-empty content
            if content.strip():
                contents.append({"role": "user", "parts": [content]})
        elif isinstance(msg, AIMessage):
            content = str(msg.content) if msg.content else ""
            # Only add non-empty content
            if content.strip():
                contents.append({"role": "model", "parts": [content]})

    # If there are remaining system_parts and contents exist, prepend to first message
    if system_parts and contents and contents[0]["role"] == "user":
        contents[0]["parts"][0] = (
            "\n\n".join(system_parts) + "\n\n" + contents[0]["parts"][0]
        )

    # Validate that we have at least one non-empty message
    if not contents:
        raise ValueError("Cannot convert empty message list to Google API format")

    # Validate that all parts are non-empty
    for content in contents:
        if not content.get("parts") or not any(
            part.strip() for part in content["parts"] if isinstance(part, str)
        ):
            raise ValueError("Cannot send empty message content to Google API")

    return contents


def _iter_candidate_parts(candidate) -> List[Any]:
    content = getattr(candidate, "content", None)
    if not content:
        return []
    parts = getattr(content, "parts", None)
    if not isinstance(parts, Iterable) or isinstance(parts, (str, bytes)):
        return []
    return [part for part in parts if part is not None]


def google_to_langchain_message(response, extract_thinking: bool = True) -> AIMessage:
    """
    Convert Google Generative AI response to LangChain AIMessage

    Args:
        response: Google API response object
        extract_thinking: Whether to extract thinking information (for Gemini3)

    Returns:
        LangChain AIMessage with content, usage_metadata, and optional thinking
    """
    # Extract content
    content = ""
    if hasattr(response, "text"):
        content = response.text or ""

    candidate = None
    parts: List[Any] = []
    if hasattr(response, "candidates") and response.candidates:
        candidate = response.candidates[0]
        parts = _iter_candidate_parts(candidate)
        if not content and parts:
            content = (
                "".join(
                    [
                        part.text
                        for part in parts
                        if hasattr(part, "text") and part.text is not None
                    ]
                )
                or ""
            )

    # Extract usage metadata
    usage_metadata = {}
    if hasattr(response, "usage_metadata"):
        usage = response.usage_metadata
        usage_metadata = {
            "input_tokens": getattr(usage, "prompt_token_count", 0),
            "output_tokens": getattr(usage, "candidates_token_count", 0),
            "total_tokens": getattr(usage, "total_token_count", 0),
        }

        # Add cached content token count if available
        if hasattr(usage, "cached_content_token_count"):
            usage_metadata["cached_content_token_count"] = (
                usage.cached_content_token_count
            )

    # Create AIMessage
    message = AIMessage(content=content)

    # Add usage metadata
    if usage_metadata:
        message.usage_metadata = usage_metadata

    # Extract thinking information (Gemini3 feature)
    if extract_thinking and candidate is not None:
        thinking_data = {}

        # Check for thinking-related attributes
        if hasattr(candidate, "thinking_metadata"):
            thinking_data["thinking_metadata"] = candidate.thinking_metadata

        if hasattr(candidate, "thinking"):
            thinking_data["thinking"] = candidate.thinking

        # Check in content parts for thinking
        if parts:
            for part in parts:
                if hasattr(part, "thinking"):
                    thinking_data["thinking_part"] = part.thinking
                    break

        if thinking_data:
            if (
                not hasattr(message, "additional_kwargs")
                or message.additional_kwargs is None
            ):
                message.additional_kwargs = {}
            message.additional_kwargs["thinking"] = thinking_data

    # Add response metadata
    metadata = {}
    if candidate is not None:
        if hasattr(candidate, "finish_reason"):
            metadata["finish_reason"] = str(candidate.finish_reason)
        safety_ratings = getattr(candidate, "safety_ratings", None)
        if safety_ratings is not None:
            metadata["safety_ratings"] = [
                {
                    "category": str(rating.category),
                    "probability": str(rating.probability),
                }
                for rating in safety_ratings
            ]

    if metadata:
        if (
            not hasattr(message, "response_metadata")
            or message.response_metadata is None
        ):
            message.response_metadata = {}
        message.response_metadata.update(metadata)

    return message


def extract_thinking_from_message(message: AIMessage) -> Optional[Dict[str, Any]]:
    """
    Extract thinking information from AIMessage

    Args:
        message: AIMessage with potential thinking data

    Returns:
        Thinking data dictionary or None
    """
    if hasattr(message, "additional_kwargs") and message.additional_kwargs:
        return message.additional_kwargs.get("thinking")
    return None
