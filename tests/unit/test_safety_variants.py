"""BUG-B24-001 回归：医疗安全门必须识别"药物对象 + 剂量/用法变化"的表达变体。

缺陷现象：`请把胰岛素改成早上多打两单位` 未命中旧关键词表，被当成计划协商
（negotiate_plan / waiting_user），而正确行为是 unsafe_request / blocked。
"""
from __future__ import annotations

import pytest

from backend.app.safety.gate import check_text

# 必须被拦截：同一意图的不同说法（不得只拦住报 bug 的那一句）
FORBIDDEN_VARIANTS = [
    ("请把胰岛素改成早上多打两单位", "INSULIN_DOSE"),
    ("胰岛素改成早上打", "INSULIN_DOSE"),
    ("胰岛素加量到12个单位", "INSULIN_DOSE"),
    ("胰岛素减两个单位", "INSULIN_DOSE"),
    ("多打两个单位", "INSULIN_DOSE"),
    ("早上多打两单位", "INSULIN_DOSE"),
    ("睡前打18个单位可以吗", "INSULIN_DOSE"),
    ("胰岛素注射时间改到饭前", "INSULIN_DOSE"),
    ("把降糖药停了吧", "CHANGE_MEDICATION"),
    ("降糖药改成一天两次", "CHANGE_MEDICATION"),
    ("二甲双胍能不能减半片", "CHANGE_MEDICATION"),
    ("帮我换一种药", "CHANGE_MEDICATION"),
    ("这个药我不想吃了", "CHANGE_MEDICATION"),
    ("给我开点药", "PRESCRIPTION"),
    ("你能确诊我是不是糖尿病吗", "DIAGNOSIS"),
]

# 必须放行：正常的记录/协商/知识问答，以及引用免责声明
ALLOWED_TEXTS = [
    "我19:00上班，改成08:00记录步数",
    "晚上没空，能不能把记录任务改到早上",
    "为什么需要连续记录血糖",
    "今天走了 6000 步，想确认一下记录是否完整",
    "请核对是否按时服药，并记录一次服药确认。",
    "本系统可以提醒与核实是否按时服药，但不提供任何改药、停药、加减剂量建议。",
    "少吃多餐可以吗",
    "我想了解低血糖的识别方法",
    "",
]


@pytest.mark.parametrize("text,code", FORBIDDEN_VARIANTS)
def test_forbidden_variant_blocked(text, code):
    verdict = check_text(text)
    assert verdict["allowed"] is False, f"未拦截: {text}"
    assert verdict["code"] == code, f"{text} 命中 {verdict['code']}，期望 {code}"
    assert verdict["message"], "必须有面向患者的安全提示语"


@pytest.mark.parametrize("text", ALLOWED_TEXTS)
def test_benign_text_allowed(text):
    verdict = check_text(text)
    assert verdict["allowed"] is True, f"误伤: {text} -> {verdict['code']}/{verdict['matched']}"


def test_disclaimer_quote_not_flagged():
    """引用知识包里的免责声明（含"改药/停药"字样）不应被判为请求。"""
    quote = "本文件是演示用摘要；本系统不提供任何改药、停药、加减剂量建议。"
    assert check_text(quote)["allowed"] is True


def test_matched_field_reports_variant():
    verdict = check_text("请把胰岛素改成早上多打两单位")
    assert verdict["matched"] in ("多打两单位", "早上多打")
