from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import contextvars
import json
import time
from typing import Any

from app.config import Settings, get_settings


HEALTHY_STATUSES = {"healthy", "valid", "active", "ok", "success"}
UNHEALTHY_STATUSES = {"expired", "invalid", "disabled", "failed", "error"}

PLATFORM_USER_AGENT_FIELDS = {
    "douyin": "MEDIA_DOUYIN_USER_AGENT",
    "xiaohongshu": "MEDIA_XHS_USER_AGENT",
    "kuaishou": "MEDIA_KUAISHOU_USER_AGENT",
}

_cookie_cooldowns: dict[tuple[str, str], float] = {}
_current_cookie_identities: contextvars.ContextVar[dict[str, "CookieIdentity"]] = contextvars.ContextVar(
    "media_current_cookie_identities",
    default={},
)


@dataclass(frozen=True)
class CookieIdentity:
    platform: str
    cookie: str = ""
    user_agent: str = ""
    account_id: str = ""
    name: str = ""


class CookiePool:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else resolve_cookie_pool_path()

    def get(self, platform: str) -> CookieIdentity:
        candidates = [
            identity
            for account_id, record in self._iter_records()
            if self._platform_matches(record, platform)
            if self._is_usable(record)
            if (identity := self._to_identity(platform, account_id, record)).cookie
            if not _is_in_cooldown(identity)
        ]
        if not candidates:
            return CookieIdentity(platform=platform)
        return candidates[0]

    def _iter_records(self) -> list[tuple[str, dict[str, Any]]]:
        if not self.path or not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        return list(_iter_cookie_records(raw))

    @staticmethod
    def _platform_matches(record: dict[str, Any], platform: str) -> bool:
        return str(record.get("platform", "")).strip().lower() == platform

    @staticmethod
    def _is_usable(record: dict[str, Any]) -> bool:
        status = str(record.get("status", "")).strip().lower()
        if status in UNHEALTHY_STATUSES:
            return False
        if status and status not in HEALTHY_STATUSES:
            return False
        if record.get("enabled") is False or record.get("valid") is False:
            return False
        return not _is_expired(record)

    @staticmethod
    def _to_identity(platform: str, account_id: str, record: dict[str, Any]) -> CookieIdentity:
        return CookieIdentity(
            platform=platform,
            cookie=_extract_cookie(record),
            user_agent=_extract_user_agent(record),
            account_id=account_id,
            name=str(record.get("name") or account_id),
        )

    @staticmethod
    def _sort_key(identity: CookieIdentity) -> tuple[bool, str]:
        # Prefer named/real accounts, then keep JSON order stable through account id.
        return (bool(identity.name), identity.account_id)


def get_platform_cookie_identity(platform: str) -> CookieIdentity:
    settings = get_settings()
    identity = CookiePool(settings.MEDIA_COOKIE_POOL_PATH).get(platform)
    if identity.user_agent:
        selected = identity
    else:
        selected = replace(identity, user_agent=_configured_user_agent(platform, settings))
    current = dict(_current_cookie_identities.get())
    current[platform] = selected
    _current_cookie_identities.set(current)
    return selected


def mark_platform_cookie_failure(platform: str, *, cooldown_seconds: int | None = None) -> None:
    identity = _current_cookie_identities.get().get(platform)
    if identity:
        mark_cookie_failure(identity, cooldown_seconds=cooldown_seconds)


def mark_platform_cookie_success(platform: str) -> None:
    identity = _current_cookie_identities.get().get(platform)
    if identity and identity.account_id:
        _cookie_cooldowns.pop((identity.platform, identity.account_id), None)


def mark_cookie_failure(identity: CookieIdentity, *, cooldown_seconds: int | None = None) -> None:
    if not identity.account_id:
        return
    settings = get_settings()
    ttl = cooldown_seconds if cooldown_seconds is not None else settings.MEDIA_COOKIE_FAILURE_COOLDOWN_SECONDS
    _cookie_cooldowns[(identity.platform, identity.account_id)] = time.monotonic() + max(1, int(ttl))


def reset_cookie_runtime_state() -> None:
    _cookie_cooldowns.clear()
    _current_cookie_identities.set({})


def resolve_cookie_pool_path(configured_path: str = "") -> Path | None:
    if configured_path:
        return Path(configured_path)

    candidates: list[Path] = []
    for base in [Path.cwd(), *Path.cwd().parents, *Path(__file__).resolve().parents]:
        candidate = base / "cookie_manager" / "cookies.json"
        if candidate not in candidates:
            candidates.append(candidate)

    return next((candidate for candidate in candidates if candidate.exists()), None)


def _iter_cookie_records(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw, list):
        return [
            (str(item.get("account_id") or item.get("id") or index), item)
            for index, item in enumerate(raw)
            if isinstance(item, dict)
        ]
    if not isinstance(raw, dict):
        return []

    records: list[tuple[str, dict[str, Any]]] = []
    for key, value in raw.items():
        if isinstance(value, dict) and value.get("platform"):
            records.append((str(value.get("account_id") or key), value))
            continue
        if isinstance(value, dict):
            nested = value.get("accounts") or value.get("items") or value.get("cookies")
            if isinstance(nested, list):
                for index, item in enumerate(nested):
                    if isinstance(item, dict):
                        item = {**item, "platform": item.get("platform") or key}
                        records.append((str(item.get("account_id") or item.get("id") or f"{key}_{index}"), item))
            elif _extract_cookie(value):
                value = {**value, "platform": value.get("platform") or key}
                records.append((str(value.get("account_id") or value.get("id") or key), value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    item = {**item, "platform": item.get("platform") or key}
                    records.append((str(item.get("account_id") or item.get("id") or f"{key}_{index}"), item))
    return records


def _extract_cookie(record: dict[str, Any]) -> str:
    for key in ("cookie", "cookie_header", "cookie_string", "Cookie"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    cookies = record.get("cookies")
    if isinstance(cookies, list):
        parts = []
        for item in cookies:
            if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
                parts.append(f"{item['name']}={item['value']}")
        return "; ".join(parts)
    if isinstance(cookies, dict):
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if value is not None)
    return ""


def _extract_user_agent(record: dict[str, Any]) -> str:
    for key in ("user_agent", "userAgent", "ua"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _configured_user_agent(platform: str, settings: Settings) -> str:
    field_name = PLATFORM_USER_AGENT_FIELDS.get(platform)
    return str(getattr(settings, field_name, "") or "") if field_name else ""


def _is_in_cooldown(identity: CookieIdentity) -> bool:
    if not identity.account_id:
        return False
    key = (identity.platform, identity.account_id)
    until = _cookie_cooldowns.get(key)
    if until is None:
        return False
    if until <= time.monotonic():
        _cookie_cooldowns.pop(key, None)
        return False
    return True


def _is_expired(record: dict[str, Any]) -> bool:
    for key in ("expired_at", "expires_at", "expire_at"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            expires_at = _parse_datetime(value)
            if expires_at is None:
                return True
            now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
            return expires_at <= now
    return False


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except ValueError:
            return None
