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
  pending: "待完成",
  missed: "已逾期",
  done: "已完成",
  completed: "已完成",
  failed: "执行失败",
  blocked: "已阻止",
  waiting_user: "等待模拟患者答复",
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
  answer_received: "模拟答复恢复",
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
  medication_taken: "服药确认",
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
export const name = (v: string) => label[v] || v;
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
