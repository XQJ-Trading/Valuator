"""Ensure repo root is on sys.path so `import valuator` works for any test file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _clear_company_cache() -> None:
    from domain.company import clear_cache

    clear_cache()
    yield
    clear_cache()
