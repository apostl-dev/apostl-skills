#!/usr/bin/env python3
"""Shared public-output sanitization for Agent Native Experience artifacts."""

from __future__ import annotations

import re
from typing import Any


class SensitiveOutputError(ValueError):
    pass


FORBIDDEN_KEYS = {
    "activation_code", "api_key", "authorization", "cookie", "cookies",
    "password", "secret", "session", "session_id", "token", "oauth_token",
}
SENSITIVE_KEY_PARTS = {
    "authorization", "code", "cookie", "credential", "env", "key",
    "password", "passphrase", "secret", "session", "token",
}
SAFE_KEY_EXCEPTIONS = {
    "api_key_prefix", "code_block", "code_blocks", "error_code", "exit_code",
    "status_code", "token_count",
}
SECRET_PATTERNS = (
    re.compile(r"\b\d+\|[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|password|activation[_-]?code|cookie|secret|token)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"\b(?:gh[oprsu]_[A-Za-z0-9_]{12,}|sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
    if normalized in SAFE_KEY_EXCEPTIONS:
        return False
    if normalized in FORBIDDEN_KEYS:
        return True
    parts = {part for part in normalized.split("_") if part}
    return bool(parts & SENSITIVE_KEY_PARTS)


def sanitize_data(value: Any, *, reject_keys: bool = True, path: str = "output") -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            child_path = f"{path}.{key}"
            identifier_map = path.endswith(".checks") or path.endswith(".results")
            if is_sensitive_key(key) and not identifier_map:
                if reject_keys:
                    raise SensitiveOutputError(f"Sensitive field is not allowed in public output: {child_path}")
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_data(item, reject_keys=reject_keys, path=child_path)
        return sanitized
    if isinstance(value, list):
        return [sanitize_data(item, reject_keys=reject_keys, path=f"{path}[]") for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_data(item, reject_keys=reject_keys, path=f"{path}[]") for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
