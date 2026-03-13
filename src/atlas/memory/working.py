"""Working Memory — fast in-memory key-value store for current operational context."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class WorkingMemoryStore:
    """Dict-backed working memory with optional max key eviction (LRU)."""

    def __init__(self, max_keys: int = 100):
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._max_keys = max_keys

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        while len(self._store) > self._max_keys:
            self._store.popitem(last=False)

    def get(self, key: str) -> Any | None:
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]
        return None

    def clear(self) -> None:
        self._store.clear()

    def get_all(self) -> dict[str, Any]:
        return dict(self._store)
