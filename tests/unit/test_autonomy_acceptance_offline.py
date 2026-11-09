"""离线验收脚本测试：预检、业务预算、中断恢复、采集语义；零真实网络/模型。"""
from __future__ import annotations

import importlib.util
import json
import json as _json
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
    _Client.ledger_path = workdir / "ledger.json"
    return module


class _Resp:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Client:
    mode = {"llm_mode": "real", "model": "deepseek-chat", "ok": True}
    budget = {"ok": True, "enabled": True, "used": 0, "limit": 16}
    fail_all: Exception | None = None
    fail_run: Exception | None = None
    skip_count = False
    ledger_path: Path | None = None

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
            if not _Client.skip_count:
                data = _json.loads(_Client.ledger_path.read_text(encoding="utf-8"))
                data["vendor_http_attempts"]["count"] += 1
                _Client.ledger_path.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
            if _Client.fail_run:
                raise _Client.fail_run
            return _Resp({"run_id": "RUN-T", "status": "completed"})
        if path == "/system/mode":
            return _Resp(dict(_Client.mode))
        if path == "/system/vendor-budget":
            return _Resp(dict(_Client.budget))
        if path.endswith("/runs"):
            return _Resp({"items": [{"id": "RUN-T"}]})
        if path.startswith("/runs/"):
            return _Resp({"id": "RUN-T"})
        return _Resp({"items": []})


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    _Client.fail_all = None
    _Client.fail_run = None
    _Client.skip_count = False
    _Client.mode = {"llm_mode": "real", "model": "deepseek-chat", "ok": True}
    _Client.budget = {"ok": True, "enabled": True, "used": 0, "limit": 16}
    monkeypatch.setattr(httpx, "Client", _Client)


def test_preflight_accepts_real_mode_with_enabled_budget(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mode = mod.preflight()
    assert mode["llm_mode"] == "real"
    assert mode["vendor_budget"]["enabled"] is True


def test_preflight_rejects_mock(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.mode = {"llm_mode": "mock", "model": "mock", "ok": True}
    with pytest.raises(mod.BudgetError, match="real"):
        mod.preflight()


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


def test_preflight_rejects_disabled_vendor_budget(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.budget = {"ok": True, "enabled": False, "used": 0, "limit": 16}
    with pytest.raises(mod.BudgetError, match="AGENT_VENDOR_LEDGER"):
        mod.preflight()


def test_preflight_rejects_exhausted_vendor_budget(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.budget = {"ok": True, "enabled": True, "used": 16, "limit": 16}
    with pytest.raises(mod.BudgetError, match="已用尽"):
        mod.preflight()


def test_preflight_network_failure_has_no_side_effect(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.fail_all = httpx.ConnectError("boom")
    with pytest.raises(httpx.ConnectError):
        mod.preflight()
    assert mod.read_ledger()["business_triggers"]["done"] == {}


def test_run_rejects_when_server_did_not_count_vendor_request(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    _Client.skip_count = True
    with pytest.raises(mod.BudgetError, match="发送层没有记录"):
        mod.run("R07")


def test_business_cap_counts_uncertain_and_pending(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.reserve_business_trigger("R07")
    mod.mark_uncertain("R07", "timeout")
    for case in ("R08", "R09", "R10"):
        mod.reserve_business_trigger(case)
        mod.finish_business_trigger(case, "RUN", "completed")
    mod.reserve_business_trigger("R11")
    with pytest.raises(mod.BudgetError, match="预算已用尽"):
        mod.reserve_business_trigger("R99")


def test_duplicate_scenario_is_blocked(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.reserve_business_trigger("R07")
    mod.finish_business_trigger("R07", "RUN-1", "completed")
    with pytest.raises(mod.BudgetError, match="已完成"):
        mod.reserve_business_trigger("R07")


def test_corrupt_ledger_missing_fields_is_rejected(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    (workdir / "ledger.json").write_text("{}", encoding="utf-8")
    with pytest.raises(mod.BudgetError, match="版本"):
        mod.read_ledger()
    with pytest.raises(mod.BudgetError):
        mod.reserve_business_trigger("R07")


def test_corrupt_ledger_negative_count_is_rejected(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    data = mod._default_ledger()
    data["vendor_http_attempts"]["count"] = -1
    (workdir / "ledger.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(mod.BudgetError, match="负数"):
        mod.read_ledger()


def test_get_collection_does_not_count_vendor(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.write_ledger(mod._default_ledger())
    mod.request("GET", "/patients/AUTO-R07/tasks", collection=True)
    assert mod.read_ledger()["vendor_http_attempts"]["count"] == 0
    assert mod.read_ledger()["collection_reads"] == 1


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
    for case in mod.CASES:
        assert (workdir / "reports" / f"autonomy_{case}_response.json").exists()
        assert (workdir / "reports" / f"autonomy_{case}_snapshot.json").exists()


def test_repeated_collect_is_read_only_and_does_not_overwrite(monkeypatch, workdir):
    mod = load(monkeypatch, workdir)
    mod.write_ledger(mod._default_ledger())
    mod.collect("R07")
    mod.collect("R07")
    assert (workdir / "reports" / "autonomy_R07_snapshot.json").exists()
    assert (workdir / "reports" / "autonomy_R07_snapshot_recheck_1.json").exists()
    assert mod.read_ledger()["vendor_http_attempts"]["count"] == 0
