from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def json_ready(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, BaseModel):
        return json_ready(obj.model_dump())
    if is_dataclass(obj) and not isinstance(obj, type):
        return json_ready(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(item) for item in obj]
    return str(obj)
