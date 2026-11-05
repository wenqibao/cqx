import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Spin,
  Tag,
  Typography,
} from "antd";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { ApiError } from "../api/httpAdapter";
import { useWorkbench } from "../app/WorkbenchContext";
import { businessName, businessText } from "../utils/business";
import { array, link, obj, text } from "../utils/format";
export function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
export function Debug({
  value,
  label = "技术详情：完整原始 JSON",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <Collapse
      size="small"
      items={[
        {
          key: "json",
          label,
          children: (
            <>
              <Typography.Paragraph
                copyable={{ text: JSON.stringify(value, null, 2) || "null" }}
              >
                复制完整原始 JSON
              </Typography.Paragraph>
              <Json value={value} />
            </>
          ),
        },
      ]}
    />
  );
}
export function Status({ value }: { value: string }) {
  return (
    <Tag
      color={
        ["failed", "blocked", "rejected", "FAIL"].includes(value)
          ? "error"
          : [
                "waiting_user",
                "pending",
                "waiting",
                "pending_human",
                "MISSING_DATA",
                "BLOCKED",
              ].includes(value)
            ? "gold"
            : ["completed", "done", "CLOSED", "PASS"].includes(value)
              ? "success"
              : "default"
      }
    >
      {businessName(value)}
    </Tag>
  );
}
export function ErrorBox({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <Alert
      role="alert"
      showIcon
      type="error"
      title={error instanceof Error ? error.message : "请求失败"}
      description={
        <>
          {error instanceof ApiError && (
            <>
              <code>{error.code}</code>
              <Debug value={error.detail} label="错误详情" />
            </>
          )}
          {retry && <Button onClick={retry}>重新读取</Button>}
        </>
      }
    />
  );
}
export function DataView<T>({
  resource,
  children,
}: {
  resource: { data?: T; loading: boolean; error?: unknown; reload: () => void };
  children: (data: T) => ReactNode;
}) {
  if (resource.loading)
    return (
      <div className="loading" role="status">
        <Spin />
        <span>正在读取实际业务数据…</span>
      </div>
    );
  if (resource.error)
    return <ErrorBox error={resource.error} retry={resource.reload} />;
  if (resource.data === undefined) return <Empty description="暂无数据" />;
  return <>{children(resource.data)}</>;
}
export function Heading({
  title,
  description,
  extra,
}: {
  title: string;
  description: string;
  extra?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {extra && <div className="heading-actions">{extra}</div>}
    </div>
  );
}
export function PatientScope({ children }: { children: ReactNode }) {
  const { patientId, patient, boot } = useWorkbench();
  if (!patientId) return <Empty description="暂无合成患者，请先新建患者" />;
  if (boot && !patient)
    return (
      <Alert
        type="error"
        title={"患者不存在：" + patientId}
        description="深链接没有匹配患者，未自动替换为其他患者。"
      />
    );
  if (patient && !patient.is_synthetic)
    return <Alert type="error" title="此工作台仅支持合成患者演示" />;
  return <div key={patientId}>{children}</div>;
}
export function TechnicalDetails({
  value,
  ids = {},
  children,
}: {
  value: unknown;
  ids?: Record<string, unknown>;
  children?: ReactNode;
}) {
  return (
    <details className="technical-details">
      <summary>技术详情（编号、参数与原始数据）</summary>
      {Object.entries(ids).map(([label, id]) =>
        id ? (
          <p key={label}>
            {label}：
            <Typography.Text className="mono" copyable={{ text: String(id) }}>
              {String(id)}
            </Typography.Text>
          </p>
        ) : null,
      )}
      {children}
      <Debug value={value} />
    </details>
  );
}
export function RunLink({ id, patient }: { id: unknown; patient: string }) {
  return typeof id === "string" && id ? (
    <span className="run-reference">
      <Link to={link("/agent", patient, { run: id })}>查看处理经过</Link>
      <small className="block muted">
        <Typography.Text className="technical-id" copyable={{ text: id }}>
          {id}
        </Typography.Text>
      </small>
    </span>
  ) : (
    <span className="muted">无关联运行</span>
  );
}
export function CostNotice() {
  const { boot } = useWorkbench();
  return boot?.mode.llm_mode === "real" ? (
    <Alert
      type="warning"
      showIcon
      title="真实模型模式：触发 Agent 或恢复答复可能产生 DeepSeek API 费用。一次操作可能包含多轮厂商请求，请勿重复提交。"
    />
  ) : (
    <Alert
      type="info"
      title="后端确定性 Mock 规划器：工具与数据库真实执行，不调用厂商模型。"
    />
  );
}
export function WriteResult({
  value,
  patientId,
}: {
  value: unknown;
  patientId: string;
}) {
  const root = obj(value),
    automation = obj(root.automation),
    resume = obj(root.resume);
  const runs = [
    ...array(automation.runs),
    ...(root.run_id ? [root] : []),
    ...(resume.run_id ? [resume] : []),
    ...(obj(resume.run).run_id ? [resume.run] : []),
    ...array(resume.runs),
  ].map(obj);
  const hasFailure =
    runs.some((r) => ["failed", "blocked"].includes(String(r.status))) ||
    array(root.rejections).length > 0;
  const record = obj(root.record),
    task = obj(root.task);
  return (
    <Card
      title="后端实际返回结果"
      className="result"
      data-testid="write-result"
    >
      <Alert
        type={hasFailure ? "warning" : "info"}
        title={
          hasFailure
            ? "业务请求已返回；Agent 存在失败或拦截，请核查详情"
            : "接口已返回，请以保存对象与重新读取结果为准"
        }
      />
      {record.id !== undefined && (
        <p>
          记录 ID：<strong>{text(record.id)}</strong> ·{" "}
          {record.duplicate ? "后端判定为重复记录" : "已保存记录"} · 患者{" "}
          {text(record.patient_id)}
        </p>
      )}
      {!!task.id && (
        <p>
          任务：{businessText(task.title, "健康管理任务")} ·{" "}
          <Status value={String(task.status)} /> · 版本 {text(task.version)}
        </p>
      )}
      {root.imported !== undefined && (
        <p>
          新增 {text(root.imported)} 行 · 重复 {text(root.duplicates)} 行 · 失败{" "}
          {text(root.failed)} 行
        </p>
      )}
      {array(root.errors).map((e, i) => (
        <Alert
          key={i}
          type="error"
          title={"第 " + text(obj(e).row) + " 行：" + text(obj(e).error)}
        />
      ))}
      {root.automation !== undefined && (
        <p>
          自动检测：
          {array(automation.events_created).length
            ? `新增 ${array(automation.events_created).length} 个事件`
            : "未产生新事件"}
          ；自动运行 {runs.length} 次；作业 {array(automation.jobs).length} 项。
        </p>
      )}
      {runs.map((r, i) => (
        <p key={i}>
          <RunLink id={r.run_id} patient={patientId} />{" "}
          {!!r.status && <Status value={String(r.status)} />}
        </p>
      ))}
      {array(root.reviews).map((r, i) => (
        <p key={i}>
          复评结果 · <Status value={String(obj(r).branch)} />
        </p>
      ))}
      <TechnicalDetails value={value} ids={{ 任务编号: task.id }} />
    </Card>
  );
}
