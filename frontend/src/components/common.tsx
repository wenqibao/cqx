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
  Popconfirm,
} from "antd";
import { Link } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { RunConversation } from "./RunConversation";
import { ApiError } from "../api/httpAdapter";
import { useWorkbench } from "../app/WorkbenchContext";
import {
  businessName,
  businessText,
  runHasFailure,
  resolvedWarnings,
} from "../utils/business";
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
            <p>
              {error.code === "HTTP_422"
                ? "请核对输入和当前状态，修正后再提交。"
                : error.code === "HTTP_409"
                  ? "请先查看现有资源，避免重复创建。"
                  : ""}
            </p>
          )}
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
export function OperationFeedback() {
  const { busy, recovery, checkRecovery, clearRecovery } = useWorkbench();
  const [elapsed, setElapsed] = useState(0);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    setElapsed(0);
    if (!busy) return;
    const started = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [busy]);
  if (busy)
    return (
      <Alert
        role="status"
        type="info"
        showIcon
        title={`正在处理，已等待 ${elapsed} 秒`}
        description={
          elapsed >= 15
            ? "处理时间较长，正在等待后端结果，请勿重复提交。连接状态仍会定期检查。"
            : "正在等待后端保存与处理结果。"
        }
      />
    );
  if (!recovery) return null;
  return (
    <Card title="上次操作结果待核对" data-testid="operation-recovery">
      <p>
        请求未返回完整结果，部分内容可能已保存。请先查询记录、运行、任务和随访问题，再决定下一步。
      </p>
      <Button
        loading={checking}
        onClick={async () => {
          setChecking(true);
          try {
            await checkRecovery();
          } finally {
            setChecking(false);
          }
        }}
      >
        查询已保存结果
      </Button>
      {recovery.error !== undefined && <ErrorBox error={recovery.error} />}
      {recovery.checked && (
        <>
          <p>已重新读取。请检查原请求是否仍在处理，以及是否已有对应结果。</p>
          <div className="toolbar">
            <Link to={link("/monitoring", recovery.patientId)}>
              查看健康记录
            </Link>
            <Link to={link("/agent", recovery.patientId)}>查看处理记录</Link>
            <Link to={link("/tasks", recovery.patientId)}>查看任务</Link>
            <Link to={link("/followups", recovery.patientId)}>
              查看随访答复
            </Link>
            <TechnicalLog value={recovery.data} label="核对结果日志" />
          </div>
          <Popconfirm
            title="确认已核对原请求及保存结果？"
            description="查询本身不能证明原请求已停止，请确认后再进行新的操作。"
            onConfirm={clearRecovery}
          >
            <Button>已核对，解除提交保护</Button>
          </Popconfirm>
        </>
      )}
    </Card>
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
    ...(obj(root.run).run_id ? [root.run] : []),
    ...(resume.run_id ? [resume] : []),
    ...(obj(resume.run).run_id ? [resume.run] : []),
    ...array(resume.runs),
  ].map(obj);
  const hasFailure = runs.some(runHasFailure);
  const record = obj(root.record),
    task = obj(root.task);
  return (
    <Card title="本次处理结果" className="result" data-testid="write-result">
      {root.partial_success === true && (
        <Alert
          type="warning"
          showIcon
          title="已保存，后续处理待补偿"
          description="业务数据已保存，自动化处理暂未完成。后端调度将尝试补偿，请查看最新记录和处理状态，无需再次提交。"
        />
      )}
      {root.already_done === true && (
        <Alert type="info" title="任务此前已完成，本次未重复执行复评或 Agent" />
      )}
      {root.already_resolved === true && (
        <Alert type="info" title="此复核已结案，保留首次处理决定" />
      )}
      {!!root.preference && (
        <p>偏好已保存：{businessText(obj(root.preference).value)}</p>
      )}
      {root.question !== undefined && (
        <p>
          答复状态：
          <Status value={String(obj(root.question).status)} />
        </p>
      )}
      {resume.uncertain === true && (
        <p>患者表示不确定，未据此补记确定的健康事实。</p>
      )}
      {!!obj(resume.recorded).id && (
        <p>回答已保存为健康记录 · {businessName(obj(resume.recorded).kind)}</p>
      )}
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
      {root.automation != null && (
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
          {resolvedWarnings(r).length > 0 && (
            <p>先前校验问题已纠正，原始经过保留在日志中。</p>
          )}
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
