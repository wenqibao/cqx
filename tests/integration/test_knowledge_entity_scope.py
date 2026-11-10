"""C-REG-KQ-01：Mock 知识问答不能引用与实际检索不一致的通用片段。"""
from __future__ import annotations

import pytest

from backend.app.agent import orchestrator
from backend.app.services import patients


def _patient(conn, pid="KQ2"):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})


def test_mock_knowledge_question_with_unknown_entity_has_no_citation(conn):
    _patient(conn)
    result = orchestrator.run_agent(conn, "KQ2", trigger_type="user_request",
                                    message="XQZ-999 生物标志物是什么")
    assert result["evidence"] == [], "实体不匹配时不得把通用片段当证据"
    assert any(r["code"] == "NO_EVIDENCE" for r in result["rejections"]), result["rejections"]
    joined = " ".join(result["responses"])
    assert "KD-001" not in joined, joined
    assert "没有足够" in joined or "不足" in joined, joined


def test_mock_knowledge_question_with_known_topic_still_cites(conn):
    _patient(conn)
    result = orchestrator.run_agent(conn, "KQ2", trigger_type="user_request",
                                    message="为什么需要连续记录血糖")
    assert result["evidence"], "正常知识问题仍应有证据"
    assert result["responses"] and "记录" in result["responses"][0], result["responses"]

@pytest.mark.parametrize("message", [
    "XQZ-999 生物标志物是什么",
    "XQZ-999 生物标志物在稳定期2型糖尿病中的特异性是多少",
])
def test_unknown_entity_leaves_no_persisted_evidence(conn, message):
    _patient(conn)
    result = orchestrator.run_agent(conn, "KQ2", trigger_type="user_request", message=message)
    rows = conn.execute("SELECT COUNT(*) c FROM evidence_items WHERE run_id=?", (result["run_id"],)).fetchone()["c"]
    assert rows == 0, "未知实体不得持久化任何证据"
    assert result["evidence"] == []
    assert any(r["code"] == "NO_EVIDENCE" for r in result["rejections"])

@pytest.mark.parametrize("message", [
    "XQZ-999 生物标志物是什么",
    "XQZ-999 生物标志物在稳定期2型糖尿病中的特异性是多少",
    "为什么需要 ZXQNOEVIDENCE897654 气泡律？",
])
def test_no_evidence_contract_fails_run_without_side_effects(conn, message):
    _patient(conn, "KQ3")
    result = orchestrator.run_agent(conn, "KQ3", trigger_type="user_request", message=message)
    assert result["status"] == "failed", result
    assert result["evidence"] == []
    assert any(r["code"] == "NO_EVIDENCE" for r in result["rejections"])
    assert result["responses"] and "没有足够" in result["responses"][0]
    assert conn.execute("SELECT COUNT(*) c FROM evidence_items WHERE run_id=?", (result["run_id"],)).fetchone()["c"] == 0
    for table in ("tasks", "questions", "reviews", "notifications"):
        assert conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE patient_id='KQ3'").fetchone()["c"] == 0
    steps = conn.execute("SELECT kind, code FROM agent_steps WHERE run_id=?", (result["run_id"],)).fetchall()
    assert any(row["code"] == "NO_EVIDENCE" for row in steps)


def test_normal_knowledge_question_completes_with_evidence(conn):
    _patient(conn, "KQ4")
    result = orchestrator.run_agent(conn, "KQ4", trigger_type="user_request",
                                    message="为什么需要连续记录血糖")
    assert result["status"] == "completed", result
    assert result["evidence"]
    assert all(t not in {e["tool"] for e in result["actions"]} for t in ("create_task", "request_human_review"))
