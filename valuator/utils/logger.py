from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
from pathlib import Path
from typing import Iterator

from .config import config

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_session_log_path: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "valuator_session_log_path",
    default=None,
)


class _SessionLogRouter(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.RLock()
        self._handlers: dict[str, logging.FileHandler] = {}

    def emit(self, record: logging.LogRecord) -> None:
        path = _session_log_path.get()
        if not path:
            return
        handler = self._handler_for(path)
        handler.emit(record)

    def close_path(self, path: str | Path | None) -> None:
        if path is None:
            return
        key = str(Path(path))
        with self._lock:
            handler = self._handlers.pop(key, None)
        if handler is not None:
            handler.close()

    def close(self) -> None:
        with self._lock:
            handlers = list(self._handlers.values())
            self._handlers.clear()
        for handler in handlers:
            handler.close()
        super().close()

    def _handler_for(self, path: str | Path) -> logging.FileHandler:
        key = str(Path(path))
        with self._lock:
            handler = self._handlers.get(key)
            if handler is None:
                filepath = Path(key)
                filepath.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.FileHandler(filepath, encoding="utf-8")
                if self.formatter is not None:
                    handler.setFormatter(self.formatter)
                self._handlers[key] = handler
            return handler


logger = logging.getLogger("valuator")
if not logger.handlers:
    logging.basicConfig(
        level=config.log_level,
        format=_LOG_FORMAT,
    )
logger.setLevel(config.log_level)

_session_log_router = _SessionLogRouter()
_session_log_router.setFormatter(logging.Formatter(_LOG_FORMAT))
logger.addHandler(_session_log_router)


@contextlib.contextmanager
def session_log_file(path: str | Path | None) -> Iterator[None]:
    if path is None:
        yield
        return
    token = _session_log_path.set(str(Path(path)))
    try:
        yield
    finally:
        _session_log_path.reset(token)


def close_session_log_file(path: str | Path | None) -> None:
    _session_log_router.close_path(path)
