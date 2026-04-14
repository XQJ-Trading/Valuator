"""Hangul jamo + ASCII alnum key for name fuzzy similarity."""

from __future__ import annotations

from jamo import h2j

_HANGUL_START = "\uac00"
_HANGUL_END = "\ud7a3"


def jamo_fuzzy_key(text: str) -> str:
    """Map Hangul syllables to jamo (via ``h2j``); keep ASCII letters/digits uppercase.

    Non-alphanumeric characters are dropped, matching ``normalized_name_key`` filtering
    intent so surface forms and corp names compare on the same basis.
    """
    parts: list[str] = []
    for ch in text.strip().upper():
        if not ch.isalnum():
            continue
        if _HANGUL_START <= ch <= _HANGUL_END:
            parts.append(h2j(ch))
        elif ch.isascii():
            parts.append(ch)
    return "".join(parts)
