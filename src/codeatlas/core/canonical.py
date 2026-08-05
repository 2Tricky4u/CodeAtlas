"""Canonical JSON serialization and hashing (ADR-0007 determinism rules).

Canonical form: UTF-8 bytes, recursively sorted object keys, compact separators
(no insignificant whitespace, therefore no CR/LF inside), unicode unescaped.
Timestamps must be excluded from hashed payloads by the *callers* that own them;
this module is a pure serializer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Serialize `value` to canonical JSON bytes.

    Raises TypeError for non-string dict keys (silent key coercion would make
    hashes depend on Python's str() behavior) and ValueError for NaN/Infinity
    (not representable in interoperable JSON).
    """
    _reject_non_string_keys(value)
    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Prefixed hex digest of the canonical serialization: `sha256:<64 hex>`."""
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Prefixed hex digest of raw bytes (for artifacts, stdout captures, files)."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _reject_non_string_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical JSON requires string keys, got {type(key).__name__}")
            _reject_non_string_keys(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_non_string_keys(item)
