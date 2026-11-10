import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Drawer,
  Form,
  Input,
  List,
  Table,
  Tabs,
  Tag,
  Collapse,
} from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { client } from "../../api/client";
import { api } from "../../api/workbench";
import type { Trace } from "../../api/types";
import { useWorkbench } from "../../app/WorkbenchContext";
import { useResource } from "../../hooks/useResource";
import {
  CostNotice,
  DataView,
  ErrorBox,
  Heading,
  Status,
  WriteResult,
  TechnicalLog,
} from "../../components/common";
import { RunConversation } from "../../components/RunConversation";
import { array, link, name, obj, text, when } from "../../utils/format";
import {
  toolDescriptions,
  businessName,
  businessText,
  runNarrative,
  actionSummary,
  relatedQuestions,
  runResponses,
  unresolvedRejections,
  resolvedWarnings,
  actionWasCorrected,
} from "../../utils/business";
export { toolDescriptions } from "../../utils/business";
export default function Agent() {
  const { patientId, patient, busy, perform } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const selected = params.get("run") || "";
  const tab = params.get("tab") || "runs";
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState<unknown>();
  const resource = useResource("runs:" + patientId, (s) =>
    client.runs(patientId, s),
  );
  const pendingResource = useResource("agent-questions:" + patientId, (s) =>
    api.questions(patientId, s),
  );
  const set = (values: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(values).forEach(([k, v]) =>
      v ? next.set(k, v) : next.delete(k),
    );
    setParams(next);
  };
  async function run(message: string) {
    setError(undefined);
    setResult(undefined);
    try {
      const r = await perform(() => api.run(patientId, message));
      setResult(r);
      resource.reload();
      pendingResource.reload();
    } catch (e) {
      setError(e);
    }
  }
  return (
    <>
      <Heading
        title="Agent 决策中心"
        description={`${patient?.name} · 健康管理沟通与处理记录`}
        extra={
          <>
            <Link to={link("/agent/knowledge", patientId)}>
              <Button>知识依据</Button>
            </Link>
            <TechnicalLog
              value={{
                runs: resource.data,
                questions: pendingResource.data,
                last_result: result,
              }}
              label="运行记录日志"
              onFindRun={(runId) => set({ run: runId })}
            />
          </>
        }
      />
      {error && <ErrorBox error={error} />}
      {result !== undefined && (
        <WriteResult value={result} patientId={patientId} />
      )}
      <Tabs
        activeKey={tab}
        onChange={(v) => set({ tab: v })}
        items={[
          {
            key: "runs",
            label: "运行与决策",
            children: (
              <>
                <Card title="发起一次健康管理请求">
                  <CostNotice />
                  <Form layout="vertical" onFinish={(v) => run(v.message)}>
                    <Form.Item
                      label="健康管理请求"
                      name="message"
                      rules={[{ required: true, whitespace: true }]}
                    >
                      <Input.TextArea
                        rows={3}
                        maxLength={1500}
                        placeholder="例如：请核实当前记录缺少哪些信息，必要时先提问；或请检索知识库说明连续记录的依据。"
                      />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={busy}>
                      运行一次 Agent
                    </Button>
                  </Form>
                </Card>
                <Card title="实际运行记录">
                  <div className="toolbar">
                    <Button
                      onClick={() => {
                        resource.reload();
                        pendingResource.reload();
                      }}
                    >
                      刷新运行状态
                    </Button>
                  </div>
                  <DataView resource={resource}>
                    {(runs) => (
                      <Table
                        rowKey="id"
                        dataSource={runs}
                        scroll={{ x: 950 }}
                        columns={[
                          {
                            title: "本次处理",
                            render: (_, r) => {
                              const narrative = runNarrative(r);
                              const pending =
                                r.status === "waiting_user"
                                  ? relatedQuestions(
                                      r,
                                      pendingResource.data || [],
                                    ).find((q) => q.status === "waiting")
                                  : undefined;
                              return (
                                <>
                                  <Button
                                    type="link"
                                    onClick={() => set({ run: r.id })}
                                  >
                                    {narrative.title}
                                  </Button>
                                  <p className="business-summary">
                                    {array(obj(r.output).responses)
                                      .map((v) => businessText(v))
                                      .join(" ") || narrative.summary}
                                  </p>
                                  <small className="block muted">
                                    触发原因：{narrative.reason}
                                  </small>
                                  {pending && (
                                    <Link
                                      to={link("/followups", patientId, {
                                        question: String(pending.id),
                                      })}
                                    >
                                      <Button size="small" type="primary">
                                        去回答
                                      </Button>
                                    </Link>
                                  )}
                                </>
                              );
                            },
                          },
                          {
                            title: "触发来源",
                            dataIndex: "trigger_type",
                            render: name,
                          },
                          {
                            title: "执行状态",
                            dataIndex: "status",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "开始时间",
                            dataIndex: "started_at",
                            render: when,
                          },
                          {
                            title: "失败原因",
                            dataIndex: "error",
                            render: (v) => businessText(v, "未返回失败原因"),
                          },
                        ]}
                      />
                    )}
                  </DataView>
                </Card>
              </>
            ),
          },
          {
            key: "negotiate",
            label: "计划协商",
            children: (
              <Card title="协商任务时间">
                <CostNotice />
                <Form layout="vertical" onFinish={(v) => run(v.message)}>
                  <Form.Item
                    name="message"
                    label="模拟患者的时间安排"
                    rules={[{ required: true, whitespace: true }]}
                  >
                    <Input.TextArea
                      rows={3}
                      placeholder="例如：我19:00上班，可以把记录步数的任务改到08:00吗？仅调整普通管理任务。"
                    />
                  </Form.Item>
                  <Form.Item
                    name="simulated"
                    valuePropName="checked"
                    rules={[
                      {
                        validator: (_, v) =>
                          v
                            ? Promise.resolve()
                            : Promise.reject(
                                new Error("请确认合成病例模拟输入与费用提示"),
                              ),
                      },
                    ]}
                  >
                    <Checkbox>
                      这是合成患者的模拟请求；已了解真实模式可能收费
                    </Checkbox>
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={busy}>
                    发起一次 Agent 协商
                  </Button>{" "}
                  <Link to={link("/tasks", patientId)}>
                    工作人员直接改期及版本查询 →
                  </Link>
                </Form>
              </Card>
            ),
          },
          {
            key: "tools",
            label: "14 项工具说明",
            children: (
              <Card title="现有工具白名单说明">
                <p className="muted">
                  可用能力说明。具体执行记录可在运行日志中查看。
                </p>
                <Table
                  rowKey="tool"
                  pagination={false}
                  dataSource={Object.entries(toolDescriptions).map(
                    ([tool, description]) => ({ tool, description }),
                  )}
                  columns={[{ title: "业务行为", dataIndex: "description" }]}
                />
              </Card>
            ),
          },
        ]}
      />
      <Drawer
        title="Agent 执行轨迹"
        open={!!selected}
        width={1050}
        onClose={() => set({ run: "" })}
        destroyOnHidden
      >
        {selected && <TraceDetail runId={selected} patientId={patientId} />}
      </Drawer>
    </>
  );
}
export function TraceDetail({
  runId,
  patientId,
}: {
  runId: string;
  patientId: string;
}) {
  const resource = useResource("trace:" + runId + ":" + patientId, (s) =>
    client.trace(runId, s).then((t) => {
      if (t.run.patient_id !== patientId)
        throw new Error(
          "此运行属于其他患者，拒绝混用患者上下文；请使用带正确 patient 参数的深链接。",
        );
      return t;
    }),
  );
  return (
    <DataView resource={resource}>{(t) => <TraceView trace={t} />}</DataView>
  );
}
export function TraceView({ trace: t }: { trace: Trace }) {
  const run = t.run,
    output = obj(run.output),
    pid = run.patient_id;
  const narrative = runNarrative(run, t);
  const results = t.steps.filter((s) => s.kind === "tool_result");
  const responses = runResponses(run);
  const reasons = unresolvedRejections(run).map((r) =>
    businessText(obj(r).message, businessName(obj(r).code)),
  );
  return (
    <>
      <div className="run-overview">
        <div>
          <h2>{narrative.title}</h2>
          {narrative.incomplete ? (
            <Tag color="error">
              {run.status === "blocked" ? "请求已拦截" : "部分处理未完成"}
            </Tag>
          ) : (
            <Status value={run.status} />
          )}
        </div>
        <TechnicalLog value={t} label="运行日志" />
      </div>
      <Card title="Agent 的回复与下一步" className="business-overview">
        <p className="next-action">
          <strong>接下来：</strong>
          {narrative.next}
        </p>
        <RunConversation run={run} patientId={pid} questions={t.questions} />
        <p className="muted">
          触发原因：{narrative.reason} · {when(run.started_at)}
        </p>
      </Card>
      {narrative.incomplete && (
        <Alert
          showIcon
          type={run.status === "failed" ? "error" : "warning"}
          title={run.status === "blocked" ? "请求已拦截" : "部分处理未完成"}
          description={
            reasons.join("；") || businessText(run.error, narrative.summary)
          }
        />
      )}
      {resolvedWarnings(run).length > 0 && (
        <Alert type="info" title="先前校验问题已纠正，完整经过见运行日志" />
      )}
      <Card title="本次处理">
        <List
          dataSource={results}
          locale={{ emptyText: "本次没有返回动作结果" }}
          renderItem={(s) => (
            <List.Item>
              <List.Item.Meta
                title={businessName(s.tool_name)}
                description={
                  s.status === "failed" &&
                  actionWasCorrected(
                    run,
                    s.tool_name,
                    obj(s.payload.post_check).ok === false
                      ? obj(s.payload.post_check)
                      : obj(s.payload.result),
                  )
                    ? "首次尝试未完成，后续已纠正；原始原因见运行日志。"
                    : actionSummary(s.tool_name, s.payload, s.status, responses)
                }
              />
              <Status
                value={
                  obj(s.payload.post_check).ok === false ||
                  obj(s.payload.result).ok === false
                    ? "failed"
                    : s.status
                }
              />
            </List.Item>
          )}
        />
      </Card>
      {t.tasks.length > 0 || t.reviews?.length ? (
        <Card title="后续安排">
          {t.tasks.map((task) => (
            <p key={task.id}>
              <Link to={link("/tasks", pid, { task: task.id })}>
                {businessText(task.title)}
              </Link>{" "}
              · <Status value={task.status} />
            </p>
          ))}
          {t.reviews?.map((r, i) => (
            <p key={i}>
              <Link
                to={link("/tasks", pid, {
                  tab: "reviews",
                  review: String(r.id),
                })}
              >
                {businessName(r.branch)}
              </Link>{" "}
              · {businessText(r.reason, "查看复评记录")}
            </p>
          ))}
        </Card>
      ) : null}
      <Collapse
        items={[
          {
            key: "sources",
            label: t.evidence.length
              ? `查看知识依据（${t.evidence.length}条）`
              : "知识依据：本次未返回",
            children: t.evidence.length ? (
              t.evidence.map((e, i) => (
                <article key={i}>
                  <h3>{businessText(e.title, "知识依据片段")}</h3>
                  <p className="muted">
                    {text(e.publisher)} · {text(e.version)}
                  </p>
                  <blockquote className="evidence-quote">
                    {text(e.quote)}
                  </blockquote>
                  {typeof e.source_url === "string" &&
                    e.source_url.startsWith("https://") && (
                      <a href={e.source_url} target="_blank" rel="noreferrer">
                        查看来源
                      </a>
                    )}
                </article>
              ))
            ) : (
              <p>本次未返回知识引用。</p>
            ),
          },
        ]}
      />
    </>
  );
}
