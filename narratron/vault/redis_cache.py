"""快取層 Redis。預設本機 dict；可選連 docker-compose 的 redis 服務。"""

from __future__ import annotations

import time


class Redis:
    def __init__(self, url: str | None = None) -> None:
        self._url = url
        self._data: dict[str, bytes] = {}
        self._expire_at: dict[str, float] = {}

    def get(self, key: str) -> bytes | None:
        deadline = self._expire_at.get(key)
        if deadline is not None and time.time() > deadline:
            self._data.pop(key, None)
            self._expire_at.pop(key, None)
            return None
        return self._data.get(key)

    def set(self, key: str, value: bytes, ttl_seconds: int | None = None) -> None:
        self._data[key] = value
        if ttl_seconds is None:
            self._expire_at.pop(key, None)
        else:
            self._expire_at[key] = time.time() + ttl_seconds
