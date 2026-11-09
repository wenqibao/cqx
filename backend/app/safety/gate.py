"""F13 安全门：禁止医疗动作拦截、工具白名单、红旗信号升级、审计写入。"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from backend.app.config import safety_rules
from backend.app.db.connection import dumps, iso, now

# 免责声明上下文：命中的词如果落在这类短语之后，说明是在"我们不提供…"，属于引用而非请求
DISCLAIMER_MARKERS = ("不提供", "不做", "不给出", "不包含", "不含", "不包括", "不涉及", "不负责", "不得", "禁止", "无需", "无须", "不承诺", "不制定", "不设置", "不设", "不开具", "不开展", "不建议", "不需要", "不予", "未提供", "未给出", "未包含", "未做", "未进行", "未调整", "并未", "未曾",
                   "不自行", "不要自行", "勿自行", "不可自行", "避免自行", "不要随意",
                   "不要", "不用", "不必", "勿", "不可以", "不新增", "不减少", "不替换", "不更换", "不改变", "不变更")
DISCLAIMER_WINDOW = 24
# 免责声明后若出现转折或指令引导，说明否定只覆盖前半句，后半句是真实指令（A-REAL-02）
CONTRAST_CUES = ("而是", "只是", "反而", "不过", "却", "仍然", "还是")
INSTRUCTION_LEADIN = re.compile(r"(?:建议|请|应|需要|可以|要|立即|马上|尽快|务必|宜)\s*$")
# 转介豁免（B-REAL-02）：疑问/条件/泛指语气 + 命中词后紧跟医生或"转由医生/转人工复核"等转介语
LEFT_CUES = re.compile(r"(?:是否|能否|可否|需不需要|要不要|该不该|如需|如果需要|若需|如果|如若|倘若|若|任何|如有|需求|提出|考虑|想|一旦)[^，。；！？\n]{0,10}$")
IMPERATIVE_TAIL = re.compile(r"(?:建议|请|应|需要|立即|马上|尽快|务必|可以|推荐)[^，。；！？\n]{0,2}$")
REFERRAL_TARGETS = ("医生", "医师", "医疗机构", "医院", "专业人员", "内分泌科")
REFERRAL_ACTIONS = ("沟通", "咨询", "讨论", "就诊", "就医", "决定", "确认", "评估")
REFERRAL_PHRASES = ("转由医生", "转交医生", "转人工复核", "转诊", "请就医", "及时就医", "经医生评估", "由医生处理", "咨询医生", "与医生沟通", "人工复核")


class SafetyViolation(Exception):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _is_disclaimer(text: str, position: int, *, generated: bool = False) -> bool:
    window = text[max(0, position - DISCLAIMER_WINDOW) : position]
    # 否定只作用于当前分句，不能用前一句免责声明掩盖后一句越权指令。
    window = re.split(r"[，。；;！!？?\n]|但是|然而", window)[-1]
    if generated:
        # 输出中的否定边界说明/无具体剂量的转介，不等于患者提出执行医疗动作。
        if '能不能' not in window and re.search(r"(?:不构成|不作为|不会|不能|不应|不可)[^，。；]{0,10}$", window):
            return True
        right = re.split(r"[，。；;！!？?\n]", text[position:])[0]
        if re.fullmatch(r"(?:涉及|任何|关于|有关)?(?:用药|药物|胰岛素|诊断|处方)(?:方案|剂量|调整|问题|事项)*(?:请|应|需)(?:咨询|联系)(?:您?的)?(?:处方)?医生", window + right):
            return True
    covered = False
    for marker in DISCLAIMER_MARKERS:
        index = window.rfind(marker)
        if index < 0:
            continue
        tail = window[index + len(marker) :]
        # 免责后面紧跟"而是/只是…"或"建议/请…"→ 否定不覆盖本次命中，按真实指令处理
        if any(cue in tail for cue in CONTRAST_CUES) or INSTRUCTION_LEADIN.search(tail):
            continue
        covered = True
    return covered or bool(re.search(r"(?:不作|不进行|请勿)[^，。；]{0,8}$", window))


def _is_referral(text: str, start: int, end: int) -> bool:
    """B-REAL-02：'是否调整治疗方案请与医生沟通'、'改药需求转由医生处理' 都是转介，不是执行动作。

    允许的转介：左侧为疑问/条件/泛指语气（是否、如需、任何、患者提出、想…），
    且右侧出现医生/机构 + 沟通类动词，或"转由医生/转人工复核/请就医"等转介语。
    左侧紧邻指令语气（建议/请/应/可以…）时不豁免，避免"建议停药，请与医生沟通"被放过。
    """
    left = text[max(0, start - 12) : start]
    if IMPERATIVE_TAIL.search(left):
        return False
    right = text[end : end + 24]
    has_referral = any(phrase in right for phrase in REFERRAL_PHRASES) or (
        any(target in right for target in REFERRAL_TARGETS)
        and any(action in right for action in REFERRAL_ACTIONS)
    )
    if not has_referral:
        return False
    return bool(LEFT_CUES.search(left)) or any(cue in right for cue in ("需求", "不适", "想"))


# 问诊式询问（B #10 残余）："您最近有没有更改用药方案？"是在采集病史，不是执行/建议改药。
# 仅当整句是疑问、且命中词不涉及停药/加减量/剂量时豁免，避免"是否要停药？"被放过。
INQUIRY_CUES = re.compile(r"(?:是否|有没有|有无|曾否|是否曾)")
# "评估是否需要调整监测或治疗方案"属于请专业人员判断，不是系统执行改药
INQUIRY_CONDITIONAL = re.compile(r"(?:是否|有无)(?:需要|应|应当|要|需|必要)[^，。；！？\n]{0,6}$")
INQUIRY_PROTECTED = ("停", "加", "减", "多打", "少打", "剂量", "注射", "换药")
# 动词前直接否定："不调整用药""未改变方案""别换药"——否定词与动词同在一个词里，
# 左侧窗口取不到，需要看命中位置前 1-2 个字符。
DIRECT_NEGATION = ("不", "未", "别", "勿")
DIRECT_NEGATION_PAIRS = ("不再", "无需", "并未", "从没", "绝不", "均不")


def _is_directly_negated(text: str, start: int) -> bool:
    if start <= 0:
        return False
    if text[start - 1] in DIRECT_NEGATION:
        return True
    return text[max(0, start - 2) : start] in DIRECT_NEGATION_PAIRS


def _is_question_inquiry(text: str, start: int, end: int) -> bool:
    clause_start = max(text.rfind(mark, 0, start) for mark in "，。；！？\n") + 1
    left = text[clause_start:start]
    is_question = bool(re.match(r"^[？?]", text[end : end + 2])) and bool(INQUIRY_CUES.search(left))
    is_conditional = bool(INQUIRY_CONDITIONAL.search(left))
    if not (is_question or is_conditional):
        return False
    return not any(word in text[start:end] for word in INQUIRY_PROTECTED)


def _match_pattern(text: str, patterns: list[str], *, generated: bool = False) -> tuple[int, str] | None:
    for pattern in patterns:
        try:
            matches = list(re.finditer(pattern, text))
        except re.error:  # 配置写错不应让安全门整体失效
            continue
        for m in matches:
            if _is_disclaimer(text, m.start(), generated=generated):
                continue
            if _is_referral(text, m.start(), m.end()):
                continue
            if _is_conditional_referral(text, m.start(), m.end()):
                continue
            if _is_verification_or_explanation(text, m.start(), m.end(), generated=generated):
                continue
            if _is_question_inquiry(text, m.start(), m.end()):
                continue
            if _is_directly_negated(text, m.start()):
                continue
            return m.start(), m.group(0)
    return None


REFERRAL_CUES = ("就医", "就诊", "咨询医生", "联系医生", "复诊", "专业复核", "人工复核", "医生评估")
CONDITIONAL_CUES = ("遇到", "如", "若", "一旦", "当", "需要时", "必要时", "如果")
CHANGE_CUES = ("调整用药", "用药调整", "调整药物", "调整剂量", "更改用药", "更换药物", "停用药物")


SENTENCE_DELIMS = "。；;！!？?\n"
# 同一分句里出现"把/请/建议…+停/改/换/加减药"时，不再按转介豁免
INLINE_INSTRUCTION = __import__("re").compile(
    r"(把|将|请|建议|应|可以|帮我|给我|需要)[^，,。；;！!？?]{0,8}"
    r"(停|改|换|加|减|增加|减少|调整|停用|更换)[^，,。；;！!？?]{0,6}"
    r"(药|片|粒|剂量|单位)"
    r"|(把|将|请|建议|应|可以|帮我|给我)[^，,。；;！!？?]{0,8}"
    r"(药|片|粒|剂量|单位)[^，,。；;！!？?]{0,4}"
    r"(停|改|换|加|减|增加|减少|调整|停用|更换)"
)


def _clause_at(text: str, start: int, end: int) -> str:
    left = max((text.rfind(ch, 0, start) for ch in SENTENCE_DELIMS), default=-1) + 1
    rights = [pos for pos in (text.find(ch, end) for ch in SENTENCE_DELIMS) if pos != -1]
    right = min(rights) if rights else len(text)
    return text[left:right]


VERIFY_CUES = ("核实", "确认", "回顾", "过去", "近一周", "近7天", "近 7 天", "历史")
VERIFY_CUES_GENERATED = VERIFY_CUES + ("是否", "有无", "有没有")
SEGMENT_DELIMS = "，,。；;！!？?\n"
EDUCATIONAL_CUES = ("会", "可能", "容易", "导致", "影响", "风险", "趋势", "说明")
IMPERATIVE_CUES = ("请", "建议", "应该", "立即", "马上", "把", "将", "帮我", "给我")


def _segment_at(text: str, start: int, end: int) -> str:
    """逗号也作为边界：避免"核实…，停药"被整句放行（A-034-01）。"""
    left = max((text.rfind(ch, 0, start) for ch in SEGMENT_DELIMS), default=-1) + 1
    rights = [pos for pos in (text.find(ch, end) for ch in SEGMENT_DELIMS) if pos != -1]
    right = min(rights) if rights else len(text)
    return text[left:right]


def _is_verification_or_explanation(text: str, start: int, end: int, *, generated: bool = False) -> bool:
    """A-033/A-034：核实历史事实、说明风险、转介解释不是用药指令。"""
    segment = _segment_at(text, start, end)
    sentence = _clause_at(text, start, end)
    if INLINE_INSTRUCTION.search(sentence):
        return False
    if any(cue in segment for cue in VERIFY_CUES):
        return True
    # 逗号续接："核实…，有无漏服或自行停药" 的第二段仍属核实问句
    if segment.strip().startswith(("是否", "有无", "有没有")):
        left = text[:start].rstrip()
        left = left[:-1] if left.endswith(("，", ",")) else left
        prev = left[max(left.rfind(ch) for ch in "。；;！!？?\n") + 1:] if left else ""
        if any(cue in prev for cue in VERIFY_CUES):
            return True
    if any(cue in segment for cue in EDUCATIONAL_CUES) and not any(
        cue in segment for cue in IMPERATIVE_CUES
    ):
        return True
    import re as _re
    if generated:
        referral = (any(cue in sentence for cue in REFERRAL_CUES)
                    or ("咨询" in sentence and "医生" in sentence)
                    or ("联系" in sentence and "医生" in sentence))
        if referral and not _re.search(
            r"(请|建议|应|立即|马上|把|将)[^，,。；;！!？?]{0,4}"
            r"(调整|停|改|换|加|减|增|降|停用|更换)",
            sentence,
        ):
            return True
    return False


def _is_conditional_referral(text: str, start: int = 0, end: int | None = None) -> bool:
    """条件式转介：'遇到调整用药需求时引导就医' 不是改药指令。

    只看命中所在分句；同句混入独立越权指令时不豁免（B-032-01）。
    """
    clause = _clause_at(text, start, end if end is not None else start)
    if INLINE_INSTRUCTION.search(clause):
        return False
    return (any(cue in clause for cue in REFERRAL_CUES)
            and any(cue in clause for cue in CONDITIONAL_CUES)
            and any(cue in clause for cue in CHANGE_CUES))


def check_text(text: str, *, generated: bool = False) -> dict[str, Any]:
    """检查患者输入/模型输出中是否包含被禁止的医疗动作意图。

    两层识别：
    1) forbidden_intents.keywords —— 固定说法（"停药""开药"…）；
    2) intent_patterns —— "药物对象 + 剂量/用法变化"的表达变体
       （如"把胰岛素改成早上多打两单位"），避免只靠关键词漏拦。
    """
    cfg = safety_rules()
    # 规则自身的固定拒绝话术是可信的否定说明，不能再次按关键词误拦。
    refusal_texts = {r.get("message") for r in cfg.get("forbidden_intents", []) + cfg.get("intent_patterns", [])}
    if text.strip() in refusal_texts:
        return {"allowed": True, "code": None, "message": "", "matched": None}
    lowered = (text or "").lower()
    for rule in cfg.get("forbidden_intents", []):
        for kw in rule.get("keywords", []):
            for match in re.finditer(re.escape(kw.lower()), lowered):
                if _is_disclaimer(lowered, match.start(), generated=generated):
                    continue
                if _is_referral(lowered, match.start(), match.end()):
                    continue
                if _is_question_inquiry(lowered, match.start(), match.end()):
                    continue
                if _is_directly_negated(lowered, match.start()):
                    continue
                if _is_verification_or_explanation(lowered, match.start(), match.end(), generated=generated):
                    continue
                return {
                    "allowed": False,
                    "code": rule["code"],
                    "name": rule.get("name", rule["code"]),
                    "message": rule.get("message", ""),
                    "matched": kw,
                }
    for rule in cfg.get("intent_patterns", []):
        terms = [str(t).lower() for t in (rule.get("terms") or [])]
        if terms and not any(term in lowered for term in terms):
            continue
        hit = _match_pattern(lowered, [str(p) for p in (rule.get("patterns") or [])], generated=generated)
        if hit:
            return {
                "allowed": False,
                "code": rule["code"],
                "name": rule.get("name", rule["code"]),
                "message": rule.get("message", ""),
                "matched": hit[1],
            }
    return {"allowed": True, "code": None, "message": "", "matched": None}


def assert_safe(text: str) -> None:
    verdict = check_text(text)
    if not verdict["allowed"]:
        raise SafetyViolation(verdict["code"], verdict["message"], {"matched": verdict["matched"]})


def check_tool(tool_name: str) -> bool:
    return tool_name in set(safety_rules().get("allowed_tools", []))


def escalation_hits(state: dict[str, Any], conn: sqlite3.Connection | None = None, patient_id: str | None = None) -> list[dict[str, Any]]:
    """扫描红旗信号（低血糖、显著高血糖、危险症状）。

    有数据库连接时扫描最近 3 天的原始记录，避免"最新一条刚好正常"而漏掉近期的低血糖；
    没有连接时退化为只看最新一条（纯函数用途）。
    """
    cfg = safety_rules()
    hits: list[dict[str, Any]] = []
    patient_id = patient_id or (state.get("patient") or {}).get("id")
    recent: list[tuple[str, float, dict[str, Any]]] = []
    if conn is not None and patient_id:
        from datetime import timedelta

        from backend.app.db.connection import iso, now

        since = iso(now(conn) - timedelta(days=3))
        rows = conn.execute(
            "SELECT kind, value, payload, recorded_at FROM health_records "
            "WHERE patient_id=? AND recorded_at>=? ORDER BY recorded_at DESC",
            (patient_id, since),
        ).fetchall()
        for r in rows:
            payload = {}
            try:
                import json

                payload = json.loads(r["payload"] or "{}")
            except Exception:
                payload = {}
            recent.append((r["kind"], r["value"], payload))
    latest = state.get("latest", {})
    if not recent:
        for key in ("fasting_glucose", "postprandial_glucose"):
            item = latest.get(key)
            if item:
                recent.append((key, item.get("value"), item.get("payload") or {}))
        for key in ("symptom",):
            item = latest.get(key)
            if item:
                recent.append((key, None, item.get("payload") or {}))

    for rule in cfg.get("escalation_rules", []):
        field = rule.get("field")
        if field == "glucose":
            op, threshold = rule.get("op"), float(rule.get("threshold", 0))
            for kind, value, _payload in recent:
                if kind not in ("fasting_glucose", "postprandial_glucose") or value is None:
                    continue
                if (op == "lte" and value <= threshold) or (op == "gte" and value >= threshold):
                    hits.append(
                        {
                            "code": rule["code"],
                            "severity": rule.get("severity", "high"),
                            "message": rule.get("message", ""),
                            "about": f"血糖记录 {value} mmol/L",
                        }
                    )
                    break
        if field == "symptom":
            for kind, _value, payload in recent:
                if kind != "symptom":
                    continue
                text = str(payload.get("text", ""))
                matched = next((kw for kw in rule.get("keywords", []) if kw and kw in text), None)
                if matched:
                    hits.append(
                        {
                            "code": rule["code"],
                            "severity": rule.get("severity", "high"),
                            "message": rule.get("message", ""),
                            "about": f"症状记录：{text}",
                        }
                    )
                    break
    return hits


def audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    decision: str,
    patient_id: str | None = None,
    run_id: str | None = None,
    code: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(ts,patient_id,run_id,actor,action,decision,code,detail) VALUES(?,?,?,?,?,?,?,?)",
        (iso(now(conn)), patient_id, run_id, actor, action, decision, code, dumps(detail or {})),
    )


def forbidden_action_count(conn: sqlite3.Connection) -> int:
    # reject 表示已阻止，不能当成执行。按成功工具轨迹核对实际输出/动作文本。
    rows = conn.execute("SELECT run_id,step_no,tool_name FROM agent_steps WHERE kind='tool_result' AND status='ok'").fetchall()
    from backend.app.db.connection import loads

    count = 0
    for row in rows:
        call = conn.execute("SELECT payload FROM agent_steps WHERE run_id=? AND kind='tool_call' AND tool_name=? AND step_no<? ORDER BY step_no DESC LIMIT 1",
                            (row['run_id'], row['tool_name'], row['step_no'])).fetchone()
        args = loads(call['payload'], {}).get('args', {}) if call else {}
        unsafe_text = any(not check_text(str(args.get(k) or ''), generated=True)['allowed']
                          for k in ('claim','title','description','text','question','body'))
        if not check_tool(row['tool_name']) or unsafe_text:
            count += 1
    return count
