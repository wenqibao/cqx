import { Alert, Button } from "antd";
import { Link } from "react-router-dom";
import type { RunSummary } from "../api/types";
import { businessName, businessText, toolDescriptions } from "../utils/business";
import { link } from "../utils/format";

const owners: Record<string, string> = {
  patient: "患者",
  clinician: "医护人员",
  agent: "Agent",
  system: "系统",
};

export function RunOutcome({
  summary,
  patientId,
}: {
  summary: RunSummary;
  patientId: string;
}) {
  const { waiting, next_owner: next } = summary;
  return (
    <section className="run-outcome" aria-label="本次业务结果">
      <p>
        <strong>本次目标</strong> {businessText(summary.goal, "未提供本次目标")}
      </p>
      <p className="muted">
        触发原因：{businessText(summary.trigger.label, "未提供触发原因")}
        {summary.trigger.reason && ` · ${businessText(summary.trigger.reason)}`}
      </p>
      {summary.partial_success && (
        <Alert type="warning" showIcon title="部分处理未完成" />
      )}
      <section aria-label="已完成动作">
        <h3>已完成</h3>
        {summary.completed.length ? (
          <ul>
            {summary.completed.map((action, index) => (
              <li key={index}>
                {toolDescriptions[action.tool] || businessText(action.label)}
                {action.detail && ` · ${businessText(action.detail)}`}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">本次暂无已确认完成的业务动作</p>
        )}
      </section>
      {summary.unfinished.length > 0 && (
        <section aria-label="未完成事项">
          <h3>未完成事项</h3>
          <ul>
            {summary.unfinished.map((item, index) => (
              <li key={index}>
                {item.tool && `${businessName(item.tool)} · `}
                {businessText(
                  item.message,
                  item.code
                    ? businessName(item.code)
                    : "未提供具体原因，请查看运行日志",
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {waiting && (
        <section aria-label="当前等待事项">
          <h3>当前等待</h3>
          <p>
            {businessText(
              waiting.text,
              waiting.kind === "human_review"
                ? "等待医护人员复核"
                : "等待后续处理",
            )}
          </p>
          {waiting.target_field && (
            <p className="muted">
              待补充：{businessName(waiting.target_field)}
            </p>
          )}
          {waiting.kind === "question" && waiting.id && (
            <Link
              to={link("/followups", patientId, {
                tab: "questions",
                question: waiting.id,
              })}
            >
              <Button type="primary">去回答</Button>
            </Link>
          )}
        </section>
      )}
      <p className="next-action">
        <strong>接下来</strong>{" "}
        {next
          ? `${owners[next.role] || businessName(next.role)} · ${businessText(next.action)}`
          : "后端未指定下一步处理人"}
      </p>
    </section>
  );
}
