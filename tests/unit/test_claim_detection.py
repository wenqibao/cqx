"""DS-02 回归：模型"声称已执行"但没有成功工具时必须判为未完成。

修复前只匹配固定短语（"已创建"/"已新建"），漏掉"已为你创建""已经帮你建好了"等自然变体，
导致 patient_request 等意图下出现"零任务却回复已创建"的虚假成功。
"""
from __future__ import annotations

import pytest

from backend.app.agent.orchestrator import _claimed_state_changes


CLAIMED = [
    ("已为你创建任务：明天早上记录空腹血糖。", "create_task"),
    ("已经帮你建好了任务，明天早上记录。", "create_task"),
    ("任务已创建，请按计划记录。", "create_task"),
    ("已把任务改到明天 8 点。", "update_task"),
    ("任务已完成。", "complete_task"),
    ("已保存偏好：早上 8 点。", "save_preference"),
]

NOT_CLAIMED = [
    "我不能创建任务，因为这属于医疗方案调整。",
    "未创建任何任务。",
    "没有创建任务，请先补录数据。",
    "建议你明天早上记录血糖。",
    "记录任务需要你确认时间。",
]


@pytest.mark.parametrize("text,tool", CLAIMED)
def test_claim_variants_detected(text, tool):
    assert tool in _claimed_state_changes(text), text


@pytest.mark.parametrize("text", NOT_CLAIMED)
def test_negations_and_suggestions_are_not_claims(text):
    assert _claimed_state_changes(text) == set(), text


def test_claim_without_tool_marks_run_failed(conn, monkeypatch):
    """端到端：模型只回复"已为你创建任务"，没有工具调用 → 运行失败且零任务。"""
    from backend.app.agent import llm as llm_module
    from backend.app.agent import orchestrator
    from backend.app.services import patients

    class FakeLLM:
        mode = "real"
        model_name = "fake-claim"

        def plan_actions(self, **kwargs):
            return llm_module.LLMResponse(content="已为你创建任务：明天早上记录空腹血糖。", tool_calls=[], raw={})

    patients.create_patient(conn, {"id": "CLAIM", "name": "声称", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    result = orchestrator.run_agent(
        conn, "CLAIM", trigger_type="user_request", message="帮我建一个明天记录血糖的任务", llm=FakeLLM()
    )
    assert result["status"] == "failed"
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"])
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
