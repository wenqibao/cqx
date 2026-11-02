"""通用小工具：ID、哈希、字段归一化。"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

PREFIXES = {
    "patient": "P",
    "event": "EVT",
    "run": "RUN",
    "task": "TSK",
    "question": "Q",
    "review": "REV",
    "pref": "PREF",
    "notification": "NTF",
    "job": "JOB",
    "evidence": "EVD",
    "step": "STP",
}


def new_id(kind: str) -> str:
    prefix = PREFIXES.get(kind, kind.upper())
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def short_hash(*parts: Any, length: int = 16) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:length]


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def normalize_kind(kind: str) -> str:
    return (kind or "").strip().lower().replace("-", "_").replace(" ", "_")


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
