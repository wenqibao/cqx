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
  Tag,
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
  Debug,
  ErrorBox,
  Heading,
  RunLink,
  Status,
  WriteResult,
} from "../../components/common";
import { array, link, name, obj, text, when } from "../../utils/format";
export const toolDescriptions: Record<string, string> = {
  search_knowledge: "检索有限知识包并返回出处",
  ask_user: "提出具体问题并等待模拟反馈",
  create_task: "创建非医疗管理任务",
  update_task: "调整管理任务并保存版本",
  complete_task: "完成任务并进入后续流程",
  query_history: "读取健康记录历史",
  schedule_review: "安排到期复评",
  create_notification: "创建站内提醒",
  request_human_review: "升级人工专业复核",
  save_preference: "保存明确确认的偏好",
  get_preferences: "读取生效偏好",
  list_tasks: "读取任务列表",
  parse_constraint: "解析时间安排约束",
  respond: "输出可追溯说明",
};
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
                      aria-label="查询 run_id"
                      placeholder="通过 run_id 查询实际轨迹"
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
                            title: "运行标识",
                            dataIndex: "id",
                            render: (v) => (
                              <Button
                                type="link"
                                className="mono"
                                onClick={() => set({ run: v })}
                              >
                                {v}
                              </Button>
                            ),
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
                            render: text,
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
                  title="此处是工具能力说明，不表示某次运行调用过全部工具。实际调用以对应 run_id 的轨迹为准。"
                />
                <Table
                  rowKey="tool"
                  pagination={false}
                  dataSource={Object.entries(toolDescriptions).map(
                    ([tool, description]) => ({ tool, description }),
                  )}
                  columns={[
                    { title: "工具名称", dataIndex: "tool" },
                    { title: "中文说明", dataIndex: "description" },
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
  const run = t.run;
  const plan = obj(run.plan);
  const output = obj(run.output);
  const pid = run.patient_id;
  const rejected = t.steps.filter(
    (s) =>
      s.kind === "rejection" ||
      s.status === "failed" ||
      s.status === "rejected",
  );
  const results = t.steps.filter((s) => s.kind === "tool_result");
  const native = t.steps.filter(
    (s) => s.kind === "llm_response" && array(s.payload.tool_calls).length > 0,
  );
  const safety =
    run.intent === "unsafe_request" ||
    t.steps.some((s) => s.code === "INSULIN_DOSE");
  const origin = safety
    ? "后端安全门处理；不据此宣称模型主动拒绝"
    : run.llm_mode === "mock"
      ? "后端确定性 Mock 规划器；工具与数据库实际执行"
      : native.length
        ? "轨迹包含原生模型工具响应"
        : "后端记录 real 模式；未返回足以核验原生调用来源的响应元数据";
  return (
    <>
      <div className="run-overview">
        <div>
          <h2>
            <Status value={run.status} /> {run.model_name || "模型未返回"}
          </h2>
          <span className="mono">{run.id}</span>
        </div>
        <Tag>{name(run.trigger_type)}</Tag>
      </div>
      <Alert
        type={
          rejected.length || array(output.rejections).length
            ? "warning"
            : "info"
        }
        title={origin}
        description={
          rejected.length
            ? "存在拒绝或失败步骤，不能把整体展示为全部执行成功。"
            : undefined
        }
      />
      <Descriptions
        column={2}
        size="small"
        items={[
          { key: "patient", label: "患者", children: pid },
          { key: "mode", label: "模式", children: run.llm_mode },
          { key: "start", label: "开始", children: when(run.started_at) },
          { key: "finish", label: "结束", children: when(run.finished_at) },
          {
            key: "trigger",
            label: "触发关联",
            children: text(run.trigger_ref),
          },
          { key: "intent", label: "业务意图", children: text(run.intent) },
        ]}
      />
      {run.error && <Alert type="error" title={run.error} />}
      {array(output.rejections).map((rejection, index) => {
        const r = obj(rejection);
        return (
          <Alert
            key={index}
            type="warning"
            showIcon
            title={text(r.code) + " · " + text(r.message)}
            description={
              r.tool
                ? "关联工具：" + text(r.tool)
                : "后端运行核对结果；不能将工具读取成功等同于业务完成。"
            }
          />
        );
      })}
      <Card title="触发原因与患者上下文">
        <p>{text(obj(run.input).message) || "无人工请求文本"}</p>
        <p>事件来源：{text(obj(run.input).event_ids)}</p>
        <Debug
          value={t.steps.find((s) => s.phase === "perceive")?.payload}
          label="实际感知状态"
        />
        {Array.isArray(plan.priority_order) ? (
          <p>后端 priority_order：{text(plan.priority_order)}</p>
        ) : (
          <p className="muted">此运行未返回事件优先序列，不推测模型排序。</p>
        )}
      </Card>
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
            label: `工具动作 ${results.length}`,
            children: (
              <>
                <Card title="实际工具执行">
                  <Table
                    rowKey="step_no"
                    size="small"
                    dataSource={results}
                    pagination={false}
                    scroll={{ x: 650 }}
                    columns={[
                      { title: "顺序", dataIndex: "step_no", width: 65 },
                      {
                        title: "工具与行为",
                        render: (_, s) => (
                          <>
                            <strong>
                              {toolDescriptions[s.tool_name || ""] ||
                                s.tool_name}
                            </strong>
                            <small className="block mono muted">
                              {s.tool_name} · tool_result
                            </small>
                          </>
                        ),
                      },
                      {
                        title: "状态",
                        dataIndex: "status",
                        render: (v) => <Status value={v} />,
                      },
                      {
                        title: "返回摘要",
                        render: (_, s) => {
                          const result = obj(s.payload.result);
                          return text(
                            result.error ||
                              result.text ||
                              result.task_id ||
                              result.question_id ||
                              result.review_id ||
                              result.notification_id ||
                              (result.found !== undefined
                                ? `检索命中：${result.found}`
                                : result.ok === true
                                  ? "工具返回 ok；详见参数、结果及核对"
                                  : "未返回摘要"),
                          );
                        },
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
                          <>
                            <h3>执行参数</h3>
                            {call ? (
                              <Descriptions
                                column={1}
                                items={Object.entries(
                                  obj(call.payload.args),
                                ).map(([k, v]) => ({
                                  key: k,
                                  label: k,
                                  children: text(v),
                                }))}
                              />
                            ) : (
                              <Alert
                                type="warning"
                                title="此工具缺少对应 tool_call 轨迹，不能编造执行参数。"
                              />
                            )}
                            <p>
                              执行后核对：{text(obj(s.payload.post_check).ok)} ·{" "}
                              {text(obj(s.payload.post_check).message)}
                            </p>
                            <Debug
                              value={s.payload}
                              label="真实工具返回与核对详情"
                            />
                          </>
                        );
                      },
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
                            {v.title}
                          </Link>
                          <Status value={v.status} />
                        </List.Item>
                      )}
                    />
                  </Card>
                  <Card title="问题与复评变化">
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
                          {text(q.question)}
                        </Link>
                      </p>
                    ))}
                    {t.reviews?.map((r, i) => (
                      <p key={i}>
                        {text(r.id)} · <Status value={String(r.branch)} />
                      </p>
                    ))}
                  </Card>
                </div>
              </>
            ),
          },
          {
            key: "timeline",
            label: "决策步骤",
            children: (
              <Timeline
                items={t.steps.map((s) => ({
                  color:
                    s.status === "failed" || s.status === "rejected"
                      ? "red"
                      : "#087f8c",
                  children: (
                    <>
                      <strong>
                        {s.step_no}. {name(s.phase)} · {name(s.kind)}
                      </strong>
                      <p className="muted">
                        {s.tool_name && `${s.tool_name} · `}
                        {when(s.created_at)} · {name(s.status)}{" "}
                        {s.code && <Tag color="error">{s.code}</Tag>}
                      </p>
                      <Debug value={s.payload} label="查看实际步骤数据" />
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
                <Card key={i} title={text(e.title || e.doc_id)}>
                  <p className="muted">
                    {text(e.publisher)} · 版本 {text(e.version)} ·{" "}
                    {text(e.doc_id)} / {text(e.chunk_id)} / {text(e.anchor)}
                  </p>
                  <blockquote className="evidence-quote">
                    {text(e.quote)}
                  </blockquote>
                  <p>引用：{text(e.citation)}</p>
                  {typeof e.source_url === "string" &&
                    e.source_url.startsWith("https://") && (
                      <a href={e.source_url} target="_blank" rel="noreferrer">
                        查看原始来源
                      </a>
                    )}
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
                  title="仅展示后端执行前校验、拒绝码与执行后核对，不在前端重做医学判断。"
                />
                {rejected.map((s) => (
                  <Card
                    key={s.step_no}
                    title={
                      <>
                        <Status value={s.status} /> {s.code || "校验未通过"}
                      </>
                    }
                  >
                    <p>{s.tool_name || name(s.phase)}</p>
                    <Debug value={s.payload} label="拒绝与失败原因" />
                  </Card>
                ))}
                {!rejected.length && (
                  <p>未返回失败或拒绝步骤；这不等于系统已覆盖全部安全语义。</p>
                )}
                <Debug value={output.rejections} label="运行输出中的拒绝项" />
              </>
            ),
          },
          {
            key: "json",
            label: "完整运行信息",
            children: <Debug value={t} label="完整 JSON 调试视图" />,
          },
        ]}
      />
    </>
  );
}
