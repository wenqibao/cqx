"""厂商请求预算守卫（发送层唯一计数责任）。

服务端在真正发出 DeepSeek HTTP 请求前调用 reserve()：
- 与验收脚本共用同一账本文件（AGENT_VENDOR_LEDGER）；
- 失败/超时同样计数（预占发生在发送前）；
- 未配置该环境变量时整体 no-op，不影响普通运行与测试；
- 账本存在但结构非法（缺字段/版本不符/负数）时拒绝，不静默恢复为 0。
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_MAX_ATTEMPTS = 16
LOCK_STALE_SECONDS = 600


class VendorBudgetError(RuntimeError):
    pass


def ledger_path() -> Path | None:
    raw = os.environ.get("AGENT_VENDOR_LEDGER", "").strip()
    return Path(raw) if raw else None


def max_attempts() -> int:
    try:
        return int(os.environ.get("AGENT_VENDOR_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))
    except ValueError as exc:
        raise VendorBudgetError("AGENT_VENDOR_MAX_ATTEMPTS 不是整数") from exc


def default_ledger() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "business_triggers": {"pending": {}, "done": {}, "uncertain": {}},
        "vendor_http_attempts": {"count": 0},
        "collection_reads": 0,
    }


def validate_ledger(data: dict) -> None:
    if not isinstance(data, dict):
        raise VendorBudgetError("账本不是 JSON 对象")
    if data.get("version") != SCHEMA_VERSION:
        raise VendorBudgetError(f"账本版本不支持: {data.get('version')!r}")
    triggers = data.get("business_triggers")
    if not isinstance(triggers, dict) or not all(
        isinstance(triggers.get(key), dict) for key in ("pending", "done", "uncertain")
    ):
        raise VendorBudgetError("账本缺少 business_triggers 结构")
    attempts = data.get("vendor_http_attempts")
    if not isinstance(attempts, dict) or not isinstance(attempts.get("count"), int):
        raise VendorBudgetError("账本缺少 vendor_http_attempts.count")
    if attempts["count"] < 0:
        raise VendorBudgetError("厂商请求计数为负数")
    if not isinstance(data.get("collection_reads"), int) or data["collection_reads"] < 0:
        raise VendorBudgetError("collection_reads 非法")


@contextlib.contextmanager
def _lock(path: Path):
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
        lock.unlink(missing_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise VendorBudgetError("厂商账本正被占用，拒绝并发计数") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    if not path.exists():
        return default_ledger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VendorBudgetError(f"账本 JSON 损坏: {exc}") from exc
    validate_ledger(data)
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def reserve() -> int | None:
    """发送前预占一次厂商额度；返回已用次数（未启用时返回 None）。"""
    path = ledger_path()
    if path is None:
        return None
    with _lock(path):
        data = _read(path)
        used = data["vendor_http_attempts"]["count"]
        limit = max_attempts()
        if used >= limit:
            raise VendorBudgetError(f"厂商请求预算已用尽（{limit}），发送前阻断")
        data["vendor_http_attempts"]["count"] = used + 1
        _write(path, data)
        return used + 1


def snapshot() -> dict:
    path = ledger_path()
    if path is None:
        return {"enabled": False, "path": None, "used": 0, "limit": max_attempts()}
    data = _read(path)
    return {"enabled": True, "path": str(path), "used": data["vendor_http_attempts"]["count"],
            "limit": max_attempts()}
