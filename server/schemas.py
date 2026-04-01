from __future__ import annotations

from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, field_validator

from .api_support import resolve_request_model


class ChatRequest(BaseModel):
    query: str
    model: Optional[str] = None
    thinking_level: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    valuation_profile: Optional[Union[str, bool]] = None
    system_context: Optional[str] = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        return resolve_request_model(v)

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, v):
        if v is not None and v.lower() not in ("high", "low"):
            raise ValueError(
                f"Invalid thinking_level: {v}. Must be 'high', 'low', or None."
            )
        return v.lower() if v else None


class TaskRewriteRequest(BaseModel):
    task: str
    model: Optional[str] = None
    custom_prompt: Optional[str] = None
    thinking_level: Optional[str] = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        return resolve_request_model(v)

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, v):
        if v is not None and v.lower() not in ("high", "low"):
            raise ValueError(
                f"Invalid thinking_level: {v}. Must be 'high', 'low', or None."
            )
        return v.lower() if v else None
