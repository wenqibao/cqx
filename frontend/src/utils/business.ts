import type { Run, Trace } from "../api/types";
import { array, name, obj } from "./format";

export const toolDescriptions: Record<string, string> = {
  search_knowledge: "检索知识依据",
  ask_user: "向患者补充提问",
  create_task: "安排健康管理任务",
  update_task: "调整管理任务",
  complete_task: "记录任务完成",
  query_history: "查阅健康记录",
  schedule_review: "安排后续复评",
  create_notification: "发送站内提醒",
  request_human_review: "请求医护人员复核",
  save_preference: "保存已确认偏好",
  get_preferences: "查阅患者偏好",
  list_tasks: "查阅管理任务",
  parse_constraint: "理解时间安排",
  respond: "给出管理说明",
};

// 只转换展示文字；原对象仍完整保存在技术详情中。未知字段明确提示，避免猜测业务含义。
export function businessText(
  value: unknown,
  fallback = "未提供业务说明",
): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  return value
    .replace(/\b(?:RUN|EVT|TSK|Q|KD|REV|EVD|NTF|PREF)-[\w.-]+/g, "关联记录")
    .replace(
      /\b[A-Za-z][A-Za-z0-9_]*\b/g,
      (token) =>
        toolDescriptions[token] ||
        (name(token) !== token
          ? name(token)
          : token.includes("_") || /^[A-Z]{3,}$/.test(token)
            ? "未映射业务字段（见技术详情）"
            : token),
    );
}
export function businessName(value: unknown): string {
  if (typeof value !== "string" || !value) return "未提供";
  return (
    toolDescriptions[value] ||
    (name(value) !== value
      ? name(value)
      : /^[\w.-]+$/.test(value)
        ? "未映射业务字段（见技术详情）"
        : businessText(value))
  );
}

export function actionSummary(
  tool: string | null,
  payload: Record<string, unknown>,
  status: string,
) {
  const result = obj(payload.result),
    check = obj(payload.post_check);
  if (
    ["failed", "rejected", "blocked"].includes(status) ||
    result.ok === false ||
    check.ok === false
  )
    return businessText(
      check.message || result.error,
      "动作未成功，请人工核查；未将其计为完成",
    );
  if (status !== "ok" && result.ok !== true)
    return "尚无足够执行结果，不能确认成功";
  const task = obj(result.task),
    question = obj(result.question);
  if (task.title || question.question)
    return businessText(task.title || question.question);
  if (typeof result.question === "string") return businessText(result.question);
  if (result.text) return businessText(result.text);
  if (tool === "search_knowledge")
    return result.found === false
      ? "未检索到匹配依据"
      : array(result.hits).length
        ? `返回 ${array(result.hits).length} 条知识片段`
        : "检索已返回，依据详见知识证据";
  if (result.task_id) return "已返回关联管理任务，具体内容请查看任务列表";
  if (result.review_id) return "已返回复核或复评记录，请跟进处理";
  if (result.notification_id) return "已返回站内提醒记录";
  return "动作已返回成功；具体保存对象及核对结果见技术详情";
}

// 模板摘要依据已返回结果生成，不额外调用模型，不把计划动作视为已执行。
export function runNarrative(run: Run, trace?: Trace) {
  const output = obj(run.output);
  const actions = trace
    ? trace.steps
        .filter((s) => s.kind === "tool_result")
        .map((s) => ({
          tool: s.tool_name || "",
          ok:
            s.status === "ok" &&
            obj(s.payload.result).ok !== false &&
            obj(s.payload.post_check).ok !== false,
        }))
    : array(output.actions).map((a) => ({
        tool: String(obj(a).tool || ""),
        ok:
          obj(a).ok === true &&
          obj(obj(a).post_check).ok !== false &&
          obj(obj(a).result).ok !== false,
      }));
  const successful = [
    ...new Set(actions.filter((a) => a.ok).map((a) => businessName(a.tool))),
  ];
  const failures = actions.filter((a) => !a.ok).length;
  const rejected =
    array(output.rejections).length > 0 ||
    !!trace?.steps.some((s) => ["failed", "rejected"].includes(s.status));
  const incomplete =
    ["failed", "blocked"].includes(run.status) || failures > 0 || rejected;
  const context = trace?.steps.find((s) => s.phase === "perceive")?.payload;
  const events = array(context?.open_events).map(businessName);
  const message = obj(run.input).message;
  const reason = events.length
    ? events.join("；")
    : typeof message === "string" && message.trim()
      ? businessText(message)
      : businessName(run.trigger_type) + "；后端未提供更具体的触发说明";
  const uncertain =
    run.trigger_type === "answer_received" &&
    typeof message === "string" &&
    /记不清|不确定|不知道/.test(message);
  const title = incomplete
    ? `${businessName(run.trigger_type)}：${run.status === "blocked" ? "请求已拦截" : "处理未全部完成"}`
    : uncertain && actions.some((a) => a.ok && a.tool === "ask_user")
      ? "患者回答不确定，已继续追问核实"
      : uncertain && actions.some((a) => a.ok && a.tool === "create_task")
        ? "患者回答不确定，已安排记录核实任务"
        : run.status === "waiting_user"
          ? "已发起随访，等待患者补充信息"
          : successful.length
            ? successful.slice(0, 2).join("、")
            : `${businessName(run.trigger_type)}：${businessName(run.status)}`;
  const human = trace?.reviews?.some(
    (r) => r.branch === "HUMAN_REVIEW" && r.status === "pending_human",
  );
  const next = human
    ? "请医护人员查看待复核事项并记录处理结果。"
    : incomplete
      ? "请人工核查失败或拦截原因及已保存对象；不要据此确认整次业务完成。"
      : run.status === "waiting_user"
        ? "请补充随访答复；不确定的信息保持未知。"
        : trace?.tasks.some((t) => ["pending", "missed"].includes(t.status))
          ? "请跟进待完成任务及截止时间。"
          : "请查看实际管理说明；未返回新的人工待办。";
  return {
    title,
    reason,
    next,
    incomplete,
    summary: `${successful.length ? `已返回成功的动作：${successful.join("、")}` : "尚未返回可确认成功的动作"}；${incomplete ? "存在失败或拦截，处理未全部完成。" : businessName(run.status) + "。"}`,
  };
}
