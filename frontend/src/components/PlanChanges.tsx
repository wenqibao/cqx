import { Table, Tag } from "antd";
import { Link } from "react-router-dom";
import type { PlanChange } from "../api/types";
import { businessName, businessText } from "../utils/business";
import { link, when } from "../utils/format";

const fields: Record<string, string> = {
  due_at: "执行时间",
  title: "任务标题",
  description: "任务说明",
  status: "任务状态",
  priority: "优先级",
  task_type: "任务类型",
};

function displayValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "未设置";
  if (field === "due_at") return when(value);
  if (field === "status" || field === "task_type") return businessName(value);
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  return businessText(value, "详情见运行日志");
}

export function PlanChanges({
  changes,
  patientId,
}: {
  changes: PlanChange[];
  patientId: string;
}) {
  const saved = changes
    .filter((change) => change.result === "saved")
    .map((change) => ({
      change,
      rows: Object.entries(change.changed_fields)
        .filter(
          ([, value]) =>
            JSON.stringify(value.before) !== JSON.stringify(value.after),
        )
        .map(([field, value]) => ({
          field,
          before: value.before,
          after: value.after,
        })),
    }))
    .filter(({ rows }) => rows.length > 0);
  if (!saved.length) return null;

  return (
    <section aria-label="本次计划变化">
      <h3>计划调整前后</h3>
      {saved.map(({ change, rows }, index) => (
        <article key={`${change.task_id}:${change.version_after}:${index}`}>
          <p>
            <Link to={link("/tasks", patientId, { task: change.task_id })}>
              {businessText(change.title, "健康管理任务")}
            </Link>{" "}
            <Tag color="success">已保存</Tag>
          </p>
          <p className="muted">
            {change.version_before === null
              ? "首次保存"
              : `版本 ${change.version_before}`}
            {change.version_after !== null && ` → 版本 ${change.version_after}`}
          </p>
          <Table
            rowKey="field"
            size="small"
            pagination={false}
            dataSource={rows}
            scroll={{ x: 540 }}
            columns={[
              {
                title: "变更项",
                dataIndex: "field",
                render: (field: string) => fields[field] || businessName(field),
              },
              {
                title: "调整前",
                render: (_, row) => displayValue(row.field, row.before),
              },
              {
                title: "调整后",
                render: (_, row) => displayValue(row.field, row.after),
              },
            ]}
          />
          <p>调整原因：{businessText(change.reason, "后端未提供调整原因")}</p>
        </article>
      ))}
    </section>
  );
}
