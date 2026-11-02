"""全局配置与路径解析。

所有路径以仓库根目录为基准：backend/app/config.py -> parents[2]。
环境变量优先，其次 .env，最后为默认值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DEMO_DIR = DATA_DIR / "demo_patients"
KNOWLEDGE_DIR = ROOT / "knowledge"
RUNTIME_DIR = DATA_DIR / "runtime"
EVAL_SCENARIO_DIR = ROOT / "evaluation" / "scenarios"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _read_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    db_path: Path = field(default_factory=lambda: _default_db_path())
    llm_mode: str = field(default_factory=lambda: (_env("AGENT_LLM_MODE", "mock") or "mock").lower())
    llm_base_url: str = field(default_factory=lambda: _env("AGENT_LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("AGENT_LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("AGENT_LLM_MODEL"))
    frontend_origin: str = field(default_factory=lambda: _env("FRONTEND_ORIGIN", "http://127.0.0.1:5173"))
    automation_poll_seconds: int = field(
        default_factory=lambda: int(_env("AUTOMATION_POLL_SECONDS", "30") or 0)
    )


def _default_db_path() -> Path:
    raw = os.environ.get("DIABETES_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return RUNTIME_DIR / "diabetes_agent.db"


@lru_cache(maxsize=1)
def settings() -> Settings:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


@lru_cache(maxsize=1)
def safety_rules() -> dict[str, Any]:
    return _read_yaml("safety_rules.yaml")


@lru_cache(maxsize=1)
def event_rules() -> dict[str, Any]:
    return _read_yaml("event_rules.yaml")


@lru_cache(maxsize=1)
def task_rules() -> dict[str, Any]:
    return _read_yaml("task_rules.yaml")


@lru_cache(maxsize=1)
def review_rules() -> dict[str, Any]:
    return _read_yaml("review_rules.yaml")


def reload_config() -> None:
    """测试与演示重置后刷新配置缓存。"""
    safety_rules.cache_clear()
    event_rules.cache_clear()
    task_rules.cache_clear()
    review_rules.cache_clear()
    settings.cache_clear()
