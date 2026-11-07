"""REL-02 对抗矩阵：动作—对象绑定、列表边界、字段覆盖与拒绝 detail。

B 的 34 条矩阵中可复现的 24 条在此固化；新增连接符/活动类表达不应误伤，
真正改药表达不能被列表边界放过。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import tools
from backend.app.db.connection import now
from backend.app.safety import validators
from backend.app.safety.gate import check_text
from backend.app.services import patients

ALLOW_TEXTS = [
    "本周管理重点：血糖记录、按时服药、增加活动",
    "按时服药、增加活动量",
    "核对用药、增加步数",
    "记录服药情况、加强锻炼",
    "按时服药；增加活动",
    "按时服药/增加活动",
    "按时服药和增加活动",
    "按时服药以及增加步数",
    "用药记录：增加活动量",
    "近 7 天空腹血糖 3 次为 6.0/8.2/10.5 mmol/L，呈上升且波动。请按原方案继续规律记录空腹血糖，用于观察趋势；不调整任何用药。",
    "按原治疗方案继续记录，不改变用药。",
]

BLOCK_TEXTS = [
    ("增加用药", "CHANGE_MEDICATION"),
    ("增加药量", "CHANGE_MEDICATION"),
    ("把药增加到每天两次", "CHANGE_MEDICATION"),
    ("停药、换药", "CHANGE_MEDICATION"),
    ("服药调整：增加剂量", "CHANGE_MEDICATION"),
    ("增加胰岛素剂量", "INSULIN_DOSE"),
    ("帮我把降糖药停了吧", "CHANGE_MEDICATION"),
    ("给我开点药", "PRESCRIPTION"),
    ("不建议停药，建议加药", "CHANGE_MEDICATION"),
    ("无需停药，而是换一种药", "CHANGE_MEDICATION"),
    ("不新增、不减少，而是替换药物", "CHANGE_MEDICATION"),
    ("按时服药、增加药量", "CHANGE_MEDICATION"),
    ("记录用药以及减少剂量", "CHANGE_MEDICATION"),
    ("不调整用药，但是增加剂量", "CHANGE_MEDICATION"),
    ("未调整过用药，现在改为一天两次", "CHANGE_MEDICATION"),
]


@pytest.mark.parametrize("text", ALLOW_TEXTS)
def test_allow_matrix(text):
    verdict = check_text(text, generated=True)
    assert verdict["allowed"] is True, (text, verdict)
    assert check_text(text)["allowed"] is True


@pytest.mark.parametrize("text,code", BLOCK_TEXTS)
def test_block_matrix(text, code):
    verdict = check_text(text, generated=True)
    assert verdict["allowed"] is False, text
    assert verdict["code"] == code, (text, verdict)


def test_notification_title_and_body_pass_validators(conn):
    """真实通知：标题“按时服药、增加活动” + 正文免责声明，必须允许并落库。"""
    patients.create_patient(conn, {"id": "M1", "name": "矩阵", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    args = {
        "patient_id": "M1",
        "title": "本周管理重点：血糖记录、按时服药、增加活动",
        "body": "已为您安排三项管理任务。本系统不提供任何改药、停药或剂量调整建议，用药相关问题请咨询您的医生。",
    }
    plan = {"actions": [{"tool": "create_notification", "args": args}]}
    checked = validators.validate_plan(conn, patient_id="M1", plan=plan, state={})
    assert checked["rejections"] == [], checked["rejections"]
    tools.execute(tools.ToolContext(conn, patient_id="M1", run_id="RUN-M1"), "create_notification", args)
    assert conn.execute("SELECT COUNT(*) c FROM notifications WHERE patient_id='M1'").fetchone()["c"] == 1


@pytest.mark.parametrize("field", ["title", "description", "text", "question", "body", "reason"])
def test_every_text_field_is_checked_with_detail(conn, field):
    """同一段危险文本放进任一受检字段，都应被拒且带 intent/matched/field。"""
    patients.create_patient(conn, {"id": "M2", "name": "字段", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    bad = "建议把降糖药停掉"
    due = (now() + timedelta(days=1)).isoformat()
    if field in ("title", "description"):
        args = {"patient_id": "M2", "task_type": "record_glucose", "title": "记录", "due_at": due}
        args[field] = bad
        tool = "create_task"
    elif field == "text":
        tool, args = "respond", {"patient_id": "M2", "text": bad}
    elif field == "question":
        tool, args = "ask_user", {"patient_id": "M2", "question": bad, "target_field": "note"}
    elif field == "body":
        tool, args = "create_notification", {"patient_id": "M2", "title": "提醒", "body": bad}
    else:
        tool, args = "request_human_review", {"patient_id": "M2", "reason": bad, "severity": "high"}
    checked = validators.validate_plan(conn, patient_id="M2", plan={"actions": [{"tool": tool, "args": args}]}, state={})
    hits = [r for r in checked["rejections"] if r["code"] == validators.FORBIDDEN_ACTION]
    assert hits, (field, checked["rejections"])
    detail = hits[0].get("detail") or {}
    assert detail.get("field") == field
    assert detail.get("intent") == "CHANGE_MEDICATION"
    assert detail.get("matched")
