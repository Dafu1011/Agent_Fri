from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json

from ..schemas.media import MediaInfo


class MediaFileCache:
    def __init__(self, root: Path, ttl_seconds: int, namespace: str = "media-v4") -> None:
        self.root = root
        self.ttl_seconds = max(0, ttl_seconds)
        self.namespace = namespace

    def key_for(self, url: str) -> str:
        value = f"{self.namespace}:{url}" if self.namespace else url
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def path_for(self, url: str) -> Path:
        return self.path_for_key(self.key_for(url))

    def path_for_key(self, key: str) -> Path:
        safe_key = "".join(ch for ch in key if ch.isalnum() or ch in {"-", "_"})
        return self.root / f"{safe_key or 'invalid'}.json"

    def get(self, url: str) -> MediaInfo | None:
        return self._read_path(self.path_for(url))

    def get_by_key(self, key: str) -> MediaInfo | None:
        return self._read_path(self.path_for_key(key))

    def _read_path(self, path: Path) -> MediaInfo | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now(timezone.utc) >= expires_at:
                return None
            return MediaInfo.model_validate(payload["data"])
        except Exception:
            return None

    def set(self, url: str, info: MediaInfo) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "url": url,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            "data": info.model_dump(mode="json"),
        }
        path = self.path_for(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class MediaRedisCache:
    def __init__(self, redis_client, ttl_seconds: int, namespace: str = "media-v4") -> None:
        self.redis_client = redis_client
        self.ttl_seconds = max(0, ttl_seconds)
        self.namespace = namespace

    def key_for(self, url: str) -> str:
        value = f"{self.namespace}:{url}" if self.namespace else url
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def redis_key_for_key(self, key: str) -> str:
        safe_key = "".join(ch for ch in key if ch.isalnum() or ch in {"-", "_"})
        return f"zf:media:parse:{self.namespace}:{safe_key or 'invalid'}"

    def get(self, url: str) -> MediaInfo | None:
        return self.get_by_key(self.key_for(url))

    def get_by_key(self, key: str) -> MediaInfo | None:
        try:
            raw = self.redis_client.get(self.redis_key_for_key(key))
        except Exception:
            return None
        return self._decode(raw)

    def set(self, url: str, info: MediaInfo) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "url": url,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            "data": info.model_dump(mode="json"),
        }
        try:
            self.redis_client.setex(
                self.redis_key_for_key(self.key_for(url)),
                max(1, self.ttl_seconds),
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception:
            return

    def _decode(self, raw: object) -> MediaInfo | None:
        if not raw:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(str(raw))
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now(timezone.utc) >= expires_at:
                return None
            return MediaInfo.model_validate(payload["data"])
        except Exception:
            return None


class MediaCompositeCache:
    def __init__(self, primary, fallback) -> None:
        self.primary = primary
        self.fallback = fallback

    def key_for(self, url: str) -> str:
        return self.fallback.key_for(url)

    def get(self, url: str) -> MediaInfo | None:
        try:
            cached = self.primary.get(url)
        except Exception:
            cached = None
        if cached:
            return cached
        return self.fallback.get(url)

    def get_by_key(self, key: str) -> MediaInfo | None:
        try:
            cached = self.primary.get_by_key(key)
        except Exception:
            cached = None
        if cached:
            return cached
        return self.fallback.get_by_key(key)

    def set(self, url: str, info: MediaInfo) -> None:
        try:
            self.primary.set(url, info)
        except Exception:
            pass
        self.fallback.set(url, info)
