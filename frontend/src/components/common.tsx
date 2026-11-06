import {
  Alert,
  Button,
  Card,
  Collapse,
  Drawer,
  Input,
  Empty,
  Spin,
  Tag,
  Typography,
} from "antd";
import { Link } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { RunConversation } from "./RunConversation";
import { ApiError } from "../api/httpAdapter";
import { useWorkbench } from "../app/WorkbenchContext";
import { businessName, businessText, runHasFailure } from "../utils/business";
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
      title={
        error instanceof SyntaxError
          ? "无法解析 JSON"
          : error instanceof Error
            ? businessText(error.message, "请求失败")
            : "请求失败"
      }
      description={
        <>
          {error instanceof ApiError && (
            <TechnicalLog
              value={{
                code: error.code,
                message: error.message,
                detail: error.detail,
              }}
              label="错误日志"
            />
          )}
          {error instanceof SyntaxError && (
            <TechnicalLog value={{ message: error.message }} label="错误日志" />
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
export function TechnicalLog({
  value,
  label = "查看日志",
  onFindRun,
}: {
  value: unknown;
  label?: string;
  onFindRun?: (runId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const raw = JSON.stringify(value, null, 2) || "null";
  function download() {
    const url = URL.createObjectURL(
      new Blob([raw], { type: "application/json;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "agent-log.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Drawer
        title="技术日志"
        open={open}
        onClose={() => setOpen(false)}
        width={860}
        destroyOnHidden
      >
        <div className="toolbar">
          <Typography.Text copyable={{ text: raw }}>
            复制完整原始 JSON
          </Typography.Text>
          <Button onClick={download}>下载日志 JSON</Button>
        </div>
        {onFindRun && (
          <Input.Search
            aria-label="查询运行编号"
            placeholder="输入运行编号"
            onSearch={(id) => {
              if (!id.trim()) return;
              setOpen(false);
              onFindRun(id.trim());
            }}
          />
        )}
        <Json value={value} />
      </Drawer>
    </>
  );
}
export function RunLink({ id, patient }: { id: unknown; patient: string }) {
  return typeof id === "string" && id ? (
    <Link to={link("/agent", patient, { run: id })}>查看处理经过</Link>
  ) : (
    <span className="muted">无关联运行</span>
  );
}
export function CostNotice() {
  const { boot } = useWorkbench();
  return boot?.mode.llm_mode === "real" ? (
    <p className="action-note">
      本次操作可能产生 DeepSeek API 费用，请确认后提交。
    </p>
  ) : null;
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
    runs.some(runHasFailure) || array(root.rejections).length > 0;
  const record = obj(root.record),
    task = obj(root.task);
  return (
    <Card title="本次处理结果" className="result" data-testid="write-result">
      {hasFailure && (
        <Alert type="warning" title="部分处理未完成，请查看原因" />
      )}
      {record.id !== undefined && (
        <p>
          {record.duplicate ? "后端判定为重复记录" : "已保存记录"} ·{" "}
          {businessName(record.kind)}
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
          title={
            "第 " +
            text(obj(e).row) +
            " 行：" +
            businessText(obj(e).error, "请核查记录内容")
          }
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
        <section key={i} className="run-result">
          <div className="toolbar">
            {runHasFailure(r) ? (
              <Tag color="error">部分处理未完成</Tag>
            ) : (
              <Status value={String(r.status)} />
            )}
            <RunLink id={r.run_id} patient={patientId} />
          </div>
          <RunConversation run={r} patientId={patientId} />
        </section>
      ))}
      {array(root.reviews).map((r, i) => (
        <p key={i}>
          复评结果 · <Status value={String(obj(r).branch)} />
        </p>
      ))}
      <TechnicalLog value={value} label="查看本次操作日志" />
    </Card>
  );
}
