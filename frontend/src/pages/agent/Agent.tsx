import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Drawer,
  Form,
  Input,
  List,
  Table,
  Tabs,
  Timeline,
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
  TechnicalDetails,
} from "../../components/common";
import { array, link, name, obj, text, when } from "../../utils/format";
import {
  toolDescriptions,
  businessName,
  businessText,
  runNarrative,
  actionSummary,
} from "../../utils/business";
export { toolDescriptions } from "../../utils/business";
export default function Agent() {
  const { patientId, patient, busy, perform, boot } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const selected = params.get("run") || "";
  const tab = params.get("tab") || "runs";
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState<unknown>();
  const resource = useResource("runs:" + patientId, (s) =>
    client.runs(patientId, s),
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
    } catch (e) {
      setError(e);
    }
  }
  return (
    <>
      <Heading
        title="Agent 决策中心"
        description={`${patient?.name} · ${patientId}；监督实际动作、工具结果与证据，不展示虚构的模型内心推理。`}
        extra={
          <Link to={link("/agent/knowledge", patientId)}>
            <Button>知识依据 →</Button>
          </Link>
        }
      />
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
                    {boot?.mode.llm_mode === "real" && (
                      <Form.Item
                        name="cost"
                        valuePropName="checked"
                        rules={[
                          {
                            validator: (_, v) =>
                              v
                                ? Promise.resolve()
                                : Promise.reject(
                                    new Error("请确认真实模型费用"),
                                  ),
                          },
                        ]}
                      >
                        <Checkbox>确认本次可能产生模型 API 费用</Checkbox>
                      </Form.Item>
                    )}
                    <Button type="primary" htmlType="submit" loading={busy}>
                      运行一次 Agent
                    </Button>
                    <p className="action-note">
                      这是人工发起请求；记录保存后的自动触发在健康监测页核验。等待超时不会自动重试。
                    </p>
                  </Form>
                </Card>
                <Card title="实际运行记录">
                  <div className="toolbar">
                    <Button onClick={resource.reload}>刷新运行状态</Button>
                    <Input.Search
                      aria-label="查询运行编号"
                      placeholder="按运行编号查询（技术验收）"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onSearch={(v) => v.trim() && set({ run: v.trim() })}
                    />
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
                              return (
                                <>
                                  <Button
                                    type="link"
                                    onClick={() => set({ run: r.id })}
                                  >
                                    {narrative.title}
                                  </Button>
                                  <p className="business-summary">
                                    {narrative.summary}
                                  </p>
                                  <small className="block muted">
                                    触发原因：{narrative.reason}
                                  </small>
                                  <TechnicalDetails
                                    value={r}
                                    ids={{ 运行编号: r.id }}
                                  />
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
                            title: "模型模式",
                            render: (_, r) => (
                              <>
                                {name(r.llm_mode)}
                                <small className="block muted">
                                  {r.model_name || "模型未返回"}
                                </small>
                              </>
                            ),
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
              <Card title="由 Agent 理解模拟患者的时间约束">
                <Alert
                  type="warning"
                  title="模拟患者提出约束；由 Agent 决定调整或追问。与工作人员直接改期属于不同来源。"
                />
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
                <Alert
                  type="info"
                  title="此处是工具能力说明，不表示某次运行调用过全部工具。实际调用以对应运行的处理经过为准。"
                />
                <Table
                  rowKey="tool"
                  pagination={false}
                  dataSource={Object.entries(toolDescriptions).map(
                    ([tool, description]) => ({ tool, description }),
                  )}
                  columns={[
                    { title: "业务行为", dataIndex: "description" },
                    {
                      title: "技术详情",
                      render: (_, r) => (
                        <TechnicalDetails
                          value={r}
                          ids={{ 工具名称: r.tool }}
                        />
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />
      {error && <ErrorBox error={error} />}
      {result !== undefined && (
        <WriteResult value={result} patientId={patientId} />
      )}
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
  const rejected = t.steps.filter(
    (s) => s.kind === "rejection" || ["failed", "rejected"].includes(s.status),
  );
  const native = t.steps.some(
    (s) => s.kind === "llm_response" && array(s.payload.tool_calls).length > 0,
  );
  const safety =
    run.intent === "unsafe_request" ||
    t.steps.some((s) => s.code === "INSULIN_DOSE");
  const origin = safety
    ? "后端安全门处理；不据此宣称模型主动拒绝"
    : run.llm_mode === "mock"
      ? "后端确定性 Mock 规划器；工具与数据库实际执行"
      : native
        ? "轨迹包含原生模型工具响应"
        : "后端配置为真实模型模式；未返回足以核验原生调用来源的响应元数据";
  return (
    <>
      <div className="run-overview">
        <div>
          <h2>{narrative.title}</h2>
          <p>{narrative.summary}</p>
        </div>
        <Status value={run.status} />
      </div>
      <Card title="发生了什么，接下来做什么" className="business-overview">
        <Descriptions
          column={1}
          items={[
            { key: "reason", label: "为什么触发", children: narrative.reason },
            { key: "actions", label: "处理结果", children: narrative.summary },
            { key: "next", label: "当前人工待办", children: narrative.next },
            {
              key: "boundary",
              label: "安全边界",
              children:
                "不诊断、不开处方、不改药或胰岛素剂量；需关注的事项交由医护人员复核。",
            },
            {
              key: "evidence",
              label: "知识依据",
              children: t.evidence.length
                ? `返回 ${t.evidence.length} 条证据，可在知识证据页签查看原文与出处。`
                : "未返回知识证据，不能据此给出有依据的医学结论。",
            },
            { key: "time", label: "处理时间", children: when(run.started_at) },
          ]}
        />
      </Card>
      <Alert
        type={narrative.incomplete ? "warning" : "info"}
        title={origin}
        description={
          narrative.incomplete
            ? "存在拒绝或失败，不能把整体展示为全部执行成功。"
            : undefined
        }
      />
      {run.error && <Alert type="error" title={businessText(run.error)} />}
      {array(output.rejections).map((value, i) => {
        const r = obj(value);
        return (
          <Alert
            key={i}
            type="warning"
            showIcon
            title={businessName(r.code)}
            description={businessText(
              r.message,
              "请核查拒绝原因，未将此项计为成功。精确拒绝码见技术详情。证据读取成功不等于业务完成。",
            )}
          />
        );
      })}
      <div className="phase-list">
        {["perceive", "plan", "validate", "act", "observe"].map((phase) => {
          const count = t.steps.filter((s) => s.phase === phase).length;
          return (
            <div
              className={"phase-chip " + (count ? "present" : "absent")}
              key={phase}
            >
              {name(phase)} · {count ? `${count} 条实际记录` : "未返回记录"}
            </div>
          );
        })}
      </div>
      <Tabs
        items={[
          {
            key: "actions",
            label: `处理动作 ${results.length}`,
            children: (
              <>
                <Card title="Agent 实际做了什么">
                  <Table
                    rowKey="step_no"
                    size="small"
                    dataSource={results}
                    pagination={false}
                    columns={[
                      {
                        title: "业务行为",
                        render: (_, s) => (
                          <strong>{businessName(s.tool_name)}</strong>
                        ),
                      },
                      {
                        title: "动作结果",
                        render: (_, s) => (
                          <>
                            <Status
                              value={
                                obj(s.payload.post_check).ok === false ||
                                obj(s.payload.result).ok === false
                                  ? "failed"
                                  : s.status
                              }
                            />
                            <p>
                              {actionSummary(s.tool_name, s.payload, s.status)}
                            </p>
                          </>
                        ),
                      },
                    ]}
                    expandable={{
                      expandedRowRender: (s) => {
                        const call = [...t.steps]
                          .reverse()
                          .find(
                            (c) =>
                              c.kind === "tool_call" &&
                              c.tool_name === s.tool_name &&
                              c.step_no < s.step_no,
                          );
                        return (
                          <TechnicalDetails
                            value={{ tool_call: call || null, tool_result: s }}
                            ids={{
                              运行编号: run.id,
                              工具名称: s.tool_name,
                              拒绝码: s.code,
                            }}
                          >
                            {!call && (
                              <Alert
                                type="warning"
                                title="此工具缺少对应 tool_call 轨迹，不能编造执行参数。"
                              />
                            )}
                          </TechnicalDetails>
                        );
                      },
                      columnTitle: "技术详情",
                    }}
                    locale={{
                      emptyText: "没有实际工具返回记录；不显示工具执行成功",
                    }}
                  />
                </Card>
                <div className="two-columns">
                  <Card title="关联管理任务">
                    <List
                      dataSource={t.tasks}
                      locale={{ emptyText: "未返回关联任务" }}
                      renderItem={(v) => (
                        <List.Item>
                          <Link to={link("/tasks", pid, { task: v.id })}>
                            {businessText(v.title)}
                          </Link>
                          <Status value={v.status} />
                        </List.Item>
                      )}
                    />
                  </Card>
                  <Card title="随访与复评">
                    <p>
                      实际关联问题 {t.questions?.length || 0} 项 · 复评{" "}
                      {t.reviews?.length || 0} 项
                    </p>
                    {t.questions?.map((q, i) => (
                      <p key={i}>
                        <Link
                          to={link("/followups", pid, {
                            question: String(q.id),
                          })}
                        >
                          {businessText(q.question)}
                        </Link>{" "}
                        · {businessName(q.status)}
                      </p>
                    ))}
                    {t.reviews?.map((r, i) => (
                      <p key={i}>
                        <Status value={String(r.branch)} />{" "}
                        {businessText(r.reason, "具体依据见复评记录")}
                      </p>
                    ))}
                  </Card>
                </div>
                {array(output.responses).map((response, i) => (
                  <Card key={i} title="实际返回的管理说明">
                    <p>{businessText(response)}</p>
                  </Card>
                ))}
              </>
            ),
          },
          {
            key: "timeline",
            label: "决策步骤",
            children: (
              <Timeline
                items={t.steps.map((s) => ({
                  color: ["failed", "rejected"].includes(s.status)
                    ? "red"
                    : "#087f8c",
                  children: (
                    <>
                      <strong>
                        {name(s.phase)} ·{" "}
                        {s.tool_name
                          ? businessName(s.tool_name)
                          : businessName(s.kind)}
                      </strong>
                      <p>
                        <Status value={s.status} />{" "}
                        {s.code && businessName(s.code)} · {when(s.created_at)}
                      </p>
                      <TechnicalDetails
                        value={s}
                        ids={{
                          步骤: s.step_no,
                          工具名称: s.tool_name,
                          拒绝码: s.code,
                        }}
                      />
                    </>
                  ),
                }))}
              />
            ),
          },
          {
            key: "evidence",
            label: `知识证据 ${t.evidence.length}`,
            children: t.evidence.length ? (
              t.evidence.map((e, i) => (
                <Card key={i} title={businessText(e.title, "知识依据片段")}>
                  <p className="muted">
                    {text(e.publisher)} · 版本 {text(e.version)}
                  </p>
                  <blockquote className="evidence-quote">
                    {text(e.quote)}
                  </blockquote>
                  <p>引用：{businessText(e.citation, "来源标记见技术详情")}</p>
                  {typeof e.source_url === "string" &&
                    e.source_url.startsWith("https://") && (
                      <a href={e.source_url} target="_blank" rel="noreferrer">
                        查看原始来源
                      </a>
                    )}
                  <TechnicalDetails
                    value={e}
                    ids={{
                      知识编号: e.doc_id,
                      片段编号: e.chunk_id,
                      段落锚点: e.anchor,
                    }}
                  />
                </Card>
              ))
            ) : (
              <Alert
                type="info"
                title="此运行未返回知识证据，不显示为有依据回答。"
              />
            ),
          },
          {
            key: "checks",
            label: "自检与拒绝",
            children: (
              <>
                <Alert
                  type="info"
                  title="仅展示后端执行前校验与执行后核对，不在前端重做医学判断。"
                />
                {rejected.map((s) => (
                  <Card
                    key={s.step_no}
                    title={
                      <>
                        <Status value={s.status} />{" "}
                        {businessName(s.code || s.phase)}
                      </>
                    }
                  >
                    <p>
                      {businessText(
                        s.payload.message || obj(s.payload.result).error,
                        "未通过的具体原因见技术详情；不作为已完成动作。",
                      )}
                    </p>
                    <TechnicalDetails
                      value={s}
                      ids={{ 拒绝码: s.code, 工具名称: s.tool_name }}
                    />
                  </Card>
                ))}
                {!rejected.length && (
                  <p>未返回失败或拒绝步骤；这不等于系统已覆盖全部安全语义。</p>
                )}
                <TechnicalDetails value={output.rejections} />
              </>
            ),
          },
          {
            key: "json",
            label: "技术详情",
            children: (
              <TechnicalDetails
                value={t}
                ids={{
                  运行编号: run.id,
                  触发关联编号: run.trigger_ref,
                  患者编号: pid,
                  模型名称: run.model_name,
                  原始状态: run.status,
                }}
              />
            ),
          },
        ]}
      />
      <TechnicalDetails
        value={t}
        ids={{ 运行编号: run.id, 触发关联编号: run.trigger_ref }}
      />
    </>
  );
}
