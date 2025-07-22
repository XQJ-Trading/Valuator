# valuator/utils/datalake/cache.py

from typing import Dict
import re

class Cache:
    """
    A singleton cache class to store key-value pairs (str to str).
    Keys must be in the format: word(.word...)? (at least one, dot-separated, alphanumeric/underscore)
    """
    _instance = None
    _data: Dict[str, str] = {}
    _key_pattern = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Cache, cls).__new__(cls)
            cls._instance._data = {}
        return cls._instance

    def _validate_key(self, key: str) -> None:
        if not self._key_pattern.match(key):
            raise ValueError(f"Cache key '{key}' must be in the format word(.word...) (alphanumeric/underscore, dot-separated, at least one word)")

    def set(self, key: str, value: str) -> None:
        self._validate_key(key)
        self._data[key] = value

    def get(self, key: str, default: str = "") -> str:
        self._validate_key(key)
        return self._data.get(key, default)

    def __setitem__(self, key: str, value: str) -> None:
        self.set(key, value)

    def __getitem__(self, key: str) -> str:
        self._validate_key(key)
        return self._data.get(key, "")

    def __str__(self) -> str:
        return str(self._data) 