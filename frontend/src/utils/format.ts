export const text = (v: unknown): string =>
  v === null || v === undefined || v === ""
    ? "未提供"
    : typeof v === "object"
      ? JSON.stringify(v)
      : String(v);
export const obj = (v: unknown): Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
export const array = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
export const when = (v: unknown) =>
  typeof v === "string" && !Number.isNaN(Date.parse(v))
    ? new Date(v).toLocaleString("zh-CN", { hour12: false })
    : text(v);
export const label: Record<string, string> = {
  block_forbidden_intent: "拦截越权请求",
  escalate_red_flag: "需关注信号转交人工复核",
  plan_rejected: "计划未通过执行前校验",
  LOW_GLUCOSE: "低血糖范围记录，转交人工复核",
  HIGH_GLUCOSE: "显著高血糖记录，转交人工复核",
  allow: "允许执行",
  reject: "已拦截",
  escalate: "转交人工复核",
  event_response: "处理健康事件",
  check_in: "日常健康核实",
  knowledge_question: "查询知识依据",
  negotiate_plan: "协商管理计划",
  unsafe_request: "超出允许范围的请求",
  patient_request: "患者管理请求",
  escalation: "升级人工复核",
  request_human_review: "请求医护人员复核",
  answer_received: "患者已回答",
  FORBIDDEN_ACTION: "操作超出系统允许范围，已拦截",
  NO_EVIDENCE: "缺少知识依据，不能给出结论",
  TOOL_NOT_ALLOWED: "操作不在允许范围内",
  TOO_MANY_ACTIONS: "本次计划动作过多",
  INVALID_TASK_TYPE: "任务类型不受支持",
  INVALID_DUE: "任务截止时间不符合要求",
  DUPLICATE_TASK: "发现重复任务",
  MISSING_REQUIRED_DATA: "缺少必要信息",
  TASK_NOT_FOUND: "未找到对应任务",
  TOOL_EXECUTION_FAILED: "业务动作执行失败",
  POSTCHECK_MISMATCH: "执行结果与实际保存状态不一致，未确认完成",
  UNSAFE_CLAIM: "说明超出安全范围",
  UNKNOWN_TOOL: "无法识别的操作，未执行",
  DIAGNOSIS: "诊断请求已拦截",
  PRESCRIPTION: "开具处方请求已拦截",
  CHANGE_MEDICATION: "更改用药请求已拦截",
  INSULIN_DOSE: "调整胰岛素剂量请求已拦截",
  STOP_TREATMENT: "终止治疗请求已拦截",
  RED_FLAG_SYMPTOM: "需关注的症状，转交人工复核",
  GLUCOSE_VARIABILITY: "血糖记录波动增大",
  HYPOGLYCEMIA_RECORD: "低血糖范围记录",
  HYPERGLYCEMIA_RECORD: "显著高血糖记录",
  LOW_ACTIVITY: "活动记录减少",
  MEDICATION_NONADHERENCE: "多次未确认服药",
  WEIGHT_GAIN: "体重记录上升",
  REVIEW_DUE: "健康复评到期",
  patient_input: "模拟患者输入",
  patient_confirmed: "模拟患者明确确认",
  import: "合成资料导入",
  confirm_medication: "核实服药记录",
  record_glucose: "补充血糖记录",
  record_activity: "补充活动记录",
  record_weight: "复测体重",
  record_bp: "补充血压记录",
  record_symptom: "补充症状记录",
  review_hypoglycemia: "复核低血糖记录",
  review_hyperglycemia: "复核显著高血糖记录",
  review_followup: "健康复评",
  created: "创建计划",
  rescheduled: "调整截止时间",
  updated: "调整计划",
  complete: "完成任务",
  create: "创建计划",
  reschedule: "调整截止时间",
  llm_response: "模型返回",
  llm_request: "请求模型",
  final: "运行结论",
  success: "成功",
  error: "失败",
  pending: "待完成",
  missed: "已逾期",
  done: "已完成",
  completed: "已完成",
  failed: "执行失败",
  blocked: "已阻止",
  waiting_user: "等待患者补充信息",
  running: "运行中",
  waiting: "待答复",
  answered: "已答复",
  open: "待处理",
  handled: "已处理",
  high: "规则级别：高",
  medium: "规则级别：中",
  low: "规则级别：低",
  scheduled: "待复评",
  pending_human: "待人工复核",
  CLOSED: "正常关闭",
  MISSING_DATA: "缺少数据",
  HUMAN_REVIEW: "人工复核",
  PENDING: "待评估",
  active: "生效中",
  superseded: "已覆盖",
  cleared: "已清除",
  unread: "未读",
  read: "已读",
  event_detected: "系统事件触发",
  user_request: "人工发起请求",
  task_completed: "任务完成触发",
  perceive: "感知状态",
  plan: "生成计划",
  validate: "执行前校验",
  act: "调用工具",
  observe: "执行后核对",
  tool_call: "调用工具",
  tool_result: "工具返回",
  validation: "安全校验",
  rejection: "拒绝记录",
  decision: "决策记录",
  ok: "通过",
  rejected: "已拒绝",
  staff_demo: "医护演示工作人员",
  patient: "患者来源（后端记录）",
  agent: "Agent",
  system: "系统规则",
  mock: "确定性 Mock 规划器",
  real: "真实模型配置",
  fasting_glucose: "空腹血糖",
  postprandial_glucose: "餐后血糖",
  steps: "活动步数",
  weight: "体重",
  medication_taken: "是否按时服药",
  symptom: "症状记录",
  meal: "饮食记录",
  bp: "血压",
  preferred_time_window: "任务时间窗口",
  task_obstacle: "任务障碍",
  contact_window: "联系时间",
  reminder_channel: "提醒渠道",
  note: "补充偏好",
  GLUCOSE_RISING: "血糖记录呈上升趋势",
  ACTIVITY_DROP: "活动记录减少",
  ADHERENCE_DROP: "服药执行记录变化",
};
export const name = (v: string) => (Object.hasOwn(label, v) ? label[v] : v);
export function link(
  path: string,
  patient: string,
  params: Record<string, string> = {},
) {
  return path + "?" + new URLSearchParams({ patient, ...params }).toString();
}
export function noticeLink(n: {
  patient_id: string;
  ref_type: string | null;
  ref_id: string | null;
}) {
  const p = n.patient_id,
    id = n.ref_id || "";
  return n.ref_type === "task"
    ? link("/tasks", p, { task: id })
    : n.ref_type === "question"
      ? link("/followups", p, { question: id })
      : n.ref_type === "review"
        ? link("/tasks", p, { tab: "reviews", review: id })
        : n.ref_type === "run"
          ? link("/agent", p, { run: id })
          : link("/patients/" + encodeURIComponent(p), p);
}
export function importRows(raw: string): Record<string, unknown>[] {
  const parsed: unknown = JSON.parse(raw.replace(/^\uFEFF/, ""));
  if (
    !Array.isArray(parsed) ||
    parsed.length === 0 ||
    parsed.length > 1000 ||
    parsed.some((r) => r === null || typeof r !== "object" || Array.isArray(r))
  )
    throw new Error("JSON需为1–1000条记录对象的数组");
  return parsed.map((r) => ({ ...obj(r), ...obj(obj(r).payload) }));
}

export function recordContent(record: {
  kind: string;
  value: number | null;
  unit: string;
  payload?: unknown;
}) {
  const payload = obj(record.payload);
  if (record.kind === "medication_taken") {
    if (record.value === 1) return "已确认服药";
    if (record.value === 0) return "未服药";
  }
  if (record.kind === "bp") {
    const [systolic, diastolic] = [payload.systolic, payload.diastolic].map(
      (value) =>
        typeof value === "number" || (typeof value === "string" && value.trim())
          ? Number(value)
          : NaN,
    );
    if (Number.isFinite(systolic) && Number.isFinite(diastolic)) {
      return `${systolic}/${diastolic} mmHg`;
    }
  }
  if (record.value !== null) return `${record.value} ${record.unit}`.trim();
  return typeof payload.text === "string" && payload.text.trim()
    ? payload.text
    : "未填写";
}
