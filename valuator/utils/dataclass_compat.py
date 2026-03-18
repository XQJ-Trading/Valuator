from __future__ import annotations

import sys
from dataclasses import dataclass as _dataclass
from dataclasses import field
from typing import Any, Callable, TypeVar, overload

__all__ = ["dataclass", "field"]

_T = TypeVar("_T")


if sys.version_info >= (3, 10):
    dataclass = _dataclass
else:
    _UNSUPPORTED_KWARGS = frozenset({"kw_only", "match_args", "slots"})

    @overload
    def dataclass(_cls: type[_T], /) -> type[_T]: ...

    @overload
    def dataclass(**kwargs: Any) -> Callable[[type[_T]], type[_T]]: ...

    def dataclass(_cls: type[_T] | None = None, /, **kwargs: Any):
        normalized_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in _UNSUPPORTED_KWARGS
        }

        if _cls is None:
            return lambda cls: _dataclass(cls, **normalized_kwargs)
        return _dataclass(_cls, **normalized_kwargs)
