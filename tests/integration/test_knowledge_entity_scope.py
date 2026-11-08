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
