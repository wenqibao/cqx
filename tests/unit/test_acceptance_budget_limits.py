"""验收脚本 P2 回归：预算上限可配置、默认 5 次触发 / 16 次 HTTP、旧账本自动补齐。"""
from __future__ import annotations

import json

import pytest

from scripts.deepseek_acceptance_server import AcceptanceBudget


def test_default_limits(workdir, monkeypatch):
    monkeypatch.delenv("ACCEPTANCE_TRIGGER_LIMIT", raising=False)
    monkeypatch.delenv("ACCEPTANCE_REQUEST_LIMIT", raising=False)
    budget = AcceptanceBudget(workdir / "ledger.json")
    assert budget.data["trigger_limit"] == 5
    assert budget.data["request_limit"] == 16


def test_env_overrides_limits(workdir, monkeypatch):
    monkeypatch.setenv("ACCEPTANCE_TRIGGER_LIMIT", "2")
    monkeypatch.setenv("ACCEPTANCE_REQUEST_LIMIT", "4")
    budget = AcceptanceBudget(workdir / "ledger.json")
    assert budget.data["trigger_limit"] == 2
    assert budget.data["request_limit"] == 4


def test_trigger_limit_is_enforced(workdir, monkeypatch):
    monkeypatch.setenv("ACCEPTANCE_TRIGGER_LIMIT", "2")
    budget = AcceptanceBudget(workdir / "ledger.json")
    budget.reserve_trigger("R01", "DS-R01", "user_request")
    budget.reserve_trigger("R02", "DS-R02", "record_created")
    with pytest.raises(RuntimeError):
        budget.reserve_trigger("R03", "DS-R03", "user_request")


def test_old_ledger_without_limits_gets_defaults(workdir, monkeypatch):
    monkeypatch.setenv("ACCEPTANCE_TRIGGER_LIMIT", "5")
    monkeypatch.setenv("ACCEPTANCE_REQUEST_LIMIT", "16")
    path = workdir / "ledger.json"
    path.write_text(json.dumps({"triggers": [], "requests": []}), encoding="utf-8")
    budget = AcceptanceBudget(path)
    assert budget.data["trigger_limit"] == 5
    assert budget.data["request_limit"] == 16
