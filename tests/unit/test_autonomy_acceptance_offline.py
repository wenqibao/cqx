"""离线验收脚本测试：预算分离、fail-closed、无真实网络/模型调用。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deepseek_autonomy_acceptance.py"


def load(monkeypatch, workdir):
    spec = importlib.util.spec_from_file_location("autonomy_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LEDGER", workdir / "ledger.json")
    monkeypatch.setattr(module, "LOCK", workdir / "ledger.lock")
    monkeypatch.setattr(module, "REPORT", workdir / "reports")
    monkeypatch.setattr(module, "FIXTURES", workdir / "fixtures.json")
    (workdir / "fixtures.json").write_text(
        json.dumps({"patients": {case: "AUTO-" + case for case in module.CASES}}), encoding="utf-8"
    )
    return module


class _Resp:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Client:
    mode = {"llm_mode": "real", "model": "deepseek-chat", "ok": True}
    fail_all: Exception | None = None
    fail_run: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, url, json=None):
        if _Client.fail_all:
            raise _Client.fail_all
        path = url.split("/api", 1)[1]
        if path.endswith("/agent/runs"):
            if _Client.fail_run:
                raise _Client.fail_run
            return _Resp({"run_id": "RUN-T", "status": "completed"})
        if path == "/system/mode":
            return _Resp(dict(_Client.mode))
        if path.endswith("/runs"):
            return _Resp({"items": [{"id": "RUN-T"}]})
        if path.startswith("/runs/"):
            return _Resp({"id": "RUN-T"})
        return _Resp({"items": []})


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    _Client.fail_all = None
    _Client.fail_run = None
    _Client.mode = {"llm_mode": "real", "model": "deepseek-chat", "ok": True}
    monkeypatch.setattr(httpx, "Client", _Client)


def test_preflight_accepts_real_mode(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    assert mod.preflight()["llm_mode"] == "real"
    assert mod.read_ledger()["business_triggers"]["pending"] == {}


def test_preflight_rejects_mock_without_trigger(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.mode = {"llm_mode": "mock", "model": "mock", "ok": True}
    with pytest.raises(mod.BudgetError, match="real"):
        mod.preflight()
    assert mod.read_ledger()["vendor_http_attempts"]["count"] == 0


def test_preflight_rejects_ok_false(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.mode = {"llm_mode": "real", "model": "deepseek-chat", "ok": False, "error": "no key"}
    with pytest.raises(mod.BudgetError, match="未就绪"):
        mod.preflight()


def test_preflight_rejects_missing_model(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.mode = {"llm_mode": "real", "model": "", "ok": True}
    with pytest.raises(mod.BudgetError, match="模型名称"):
        mod.preflight()


def test_preflight_network_failure_has_no_side_effect(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.fail_all = httpx.ConnectError("boom")
    with pytest.raises(httpx.ConnectError):
        mod.preflight()
    ledger = mod.read_ledger()
    assert ledger["vendor_http_attempts"]["count"] == 0
    assert ledger["business_triggers"]["done"] == {}


def test_vendor_attempt_cap_blocks_before_17th(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    ledger = mod.read_ledger()
    ledger["vendor_http_attempts"]["count"] = 15
    mod.write_ledger(ledger)
    assert mod.reserve_vendor_attempt() == 16
    with pytest.raises(mod.BudgetError, match="预算已用尽"):
        mod.reserve_vendor_attempt()


def test_business_trigger_cap_blocks_sixth(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    ledger = mod.read_ledger()
    ledger["business_triggers"]["done"] = {case: {"run_id": "R"} for case in mod.CASES[:4]}
    ledger["business_triggers"]["pending"] = {"R11": "2026-01-01T00:00:00Z"}
    mod.write_ledger(ledger)
    with pytest.raises(mod.BudgetError, match="预算已用尽"):
        mod.reserve_business_trigger("R99")


def test_duplicate_scenario_is_blocked(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.reserve_business_trigger("R07")
    mod.finish_business_trigger("R07", "RUN-1", "completed")
    with pytest.raises(mod.BudgetError, match="已完成"):
        mod.reserve_business_trigger("R07")


def test_get_collection_does_not_count_vendor(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.request("GET", "/patients/AUTO-R07/tasks", collection=True)
    ledger = mod.read_ledger()
    assert ledger["vendor_http_attempts"]["count"] == 0
    assert ledger["collection_reads"] == 1


def test_timeout_marks_uncertain_and_blocks_resend(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.fail_run = httpx.ReadTimeout("slow")
    with pytest.raises(mod.BudgetError, match="禁止自动重发"):
        mod.run("R07")
    ledger = mod.read_ledger()
    assert "R07" in ledger["business_triggers"]["uncertain"]
    assert ledger["vendor_http_attempts"]["count"] == 1, "失败尝试也必须计数"
    with pytest.raises(mod.BudgetError, match="禁止自动重发"):
        mod.run("R07")


def test_all_five_scenarios_complete_offline(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    for case in mod.CASES:
        mod.run(case)
    ledger = mod.read_ledger()
    assert set(ledger["business_triggers"]["done"]) == set(mod.CASES)
    assert ledger["vendor_http_attempts"]["count"] == 5
    assert ledger["collection_reads"] > 0
    for case in mod.CASES:
        assert (workdir / "reports" / f"autonomy_{case}_response.json").exists()
        assert (workdir / "reports" / f"autonomy_{case}_snapshot.json").exists()


def test_repeated_collect_is_read_only_and_does_not_overwrite(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.collect("R07")
    vendor_before = mod.read_ledger()["vendor_http_attempts"]["count"]
    mod.collect("R07")
    assert (workdir / "reports" / "autonomy_R07_snapshot.json").exists()
    assert (workdir / "reports" / "autonomy_R07_snapshot_recheck_1.json").exists()
    assert mod.read_ledger()["vendor_http_attempts"]["count"] == vendor_before == 0
