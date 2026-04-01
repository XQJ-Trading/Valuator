from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _encode_session_log_filename(session_dir: str, step_file: str) -> str:
    return f"{session_dir}__{step_file}"


def _decode_session_log_filename(filename: str) -> Optional[tuple[str, str]]:
    if "__" not in filename:
        return None
    session_part, step_part = filename.split("__", 1)
    if not session_part or not step_part:
        return None
    if not session_part.startswith("session_"):
        return None
    if not step_part.startswith("step_") or not step_part.endswith(".json"):
        return None
    if not _SAFE_NAME_RE.match(session_part):
        return None
    if not _SAFE_NAME_RE.match(step_part):
        return None
    return session_part, step_part


def _resolve_gemini_log_path(filename: str, logs_dir: Path) -> Path:
    if filename.startswith("request_response_") and filename.endswith(".json"):
        safe_name = os.path.basename(filename)
        return logs_dir / safe_name

    decoded = _decode_session_log_filename(filename)
    if decoded is None:
        raise HTTPException(status_code=400, detail="Invalid filename format")

    session_part, step_part = decoded
    return logs_dir / session_part / step_part


def _extract_request_response_timestamp(filename: str) -> Optional[str]:
    match = re.match(r"^request_response_(\d{8}_\d{6}(?:_\d{6})?)\.json$", filename)
    if match:
        return match.group(1)
    return None


def _extract_step_timestamp(filename: str) -> Optional[str]:
    match = re.match(r"^step_\d+_(\d{8}_\d{6}(?:_\d{6})?)\.json$", filename)
    if match:
        return match.group(1)
    return None


def _parse_gemini_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    if not timestamp_str:
        return None
    for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    return None
