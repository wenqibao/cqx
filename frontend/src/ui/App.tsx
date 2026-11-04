import { useCallback, useEffect, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useSearchParams,
} from "react-router-dom";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Timeline,
} from "antd";
import {
  DashboardOutlined,
  HeartOutlined,
  LineChartOutlined,
  ProfileOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { client } from "../api/client";
import { ApiError } from "../api/httpAdapter";
import { recordKinds } from "../api/types";
import type {
  Health,
  Patient,
  State,
  Task,
  Run,
  HealthRecord,
  RecordCreate,
  Trace,
  RecordResult,
  CompleteResult,
} from "../api/types";
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
const labels: Record<string, string> = {
  fasting_glucose: "空腹血糖",
  postprandial_glucose: "餐后血糖",
  steps: "活动步数",
  weight: "体重",
  medication_taken: "服药确认",
  symptom: "症状记录",
  meal: "饮食记录",
  bp: "血压",
  pending: "待完成",
  done: "已完成",
  missed: "未完成",
  cancelled: "已取消",
  running: "运行中",
  completed: "执行完成",
  waiting_user: "等待用户回答",
  blocked: "已阻止",
  failed: "执行失败",
};
const show = (v: unknown) =>
  v === null || v === undefined
    ? "未提供"
    : typeof v === "object"
      ? JSON.stringify(v)
      : String(v);
function Json({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}
function Status({ value }: { value: string }) {
  return (
    <Tag
      color={
        ["failed", "blocked"].includes(value)
          ? "error"
          : ["waiting_user", "pending"].includes(value)
            ? "gold"
            : ["done", "completed"].includes(value)
              ? "success"
              : "default"
      }
    >
      {labels[value] || value} · {value}
    </Tag>
  );
}
function ErrorBox({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <Alert
      role="alert"
      type="error"
      showIcon
      title={error instanceof Error ? error.message : "请求失败"}
      description={
        <>
          {error instanceof ApiError && (
            <>
              <code>{error.code}</code>
              <Json value={error.detail} />
            </>
          )}
          <Button onClick={retry}>重试读取</Button>
        </>
      }
    />
  );
}
function Chart({ records, until }: { records: HealthRecord[]; until: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const points = records
      .filter((r) => r.kind === "fasting_glucose")
      .sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
    chart.setOption({
      color: ["#0f766e"],
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: unknown) => `${v} mmol/L`,
      },
      grid: { left: 48, right: 20, top: 25, bottom: 45 },
      xAxis: { type: "time", name: "记录时间" },
      yAxis: { type: "value", name: "mmol/L", min: 0 },
      series: [
        {
          name: "空腹血糖",
          type: "line",
          smooth: false,
          connectNulls: false,
          symbolSize: 7,
          data: points.map((r) => [r.recorded_at, r.value]),
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [records]);
  return (
    <>
      <div
        ref={ref}
        role="img"
        aria-label="近七天空腹血糖趋势，单位mmol/L"
        style={{ height: 285, width: "100%" }}
      />
      <p className="muted">
        后端近 7 天记录 · 截至 {until}
        ；仅连接实际观测点，未补齐缺失值、未设置医学目标。
      </p>
    </>
  );
}
type Bundle = {
  state: State;
  records: HealthRecord[];
  tasks: Task[];
  runs: Run[];
};
export default function App() {
  const [health, setHealth] = useState<Health>();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [id, setId] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const boot = useCallback(async (signal?: AbortSignal) => {
    try {
      const [h, p] = await Promise.all([
        client.health(signal),
        client.patients(signal),
      ]);
      if (signal?.aborted) return;
      setHealth(h);
      setPatients(p);
      setId((old) => (p.some((v) => v.id === old) ? old : p[0]?.id || ""));
      setError(undefined);
    } catch (e) {
      if (!signal?.aborted) {
        setHealth(undefined);
        setError(e);
      }
    }
  }, []);
  useEffect(() => {
    const c = new AbortController();
    void boot(c.signal);
    const t = setInterval(() => void boot(c.signal), 15000);
    return () => {
      c.abort();
      clearInterval(t);
    };
  }, [boot]);
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <HeartOutlined />
          糖衡智管<small>健康管理 · 单 Agent</small>
        </div>
        <nav aria-label="主要导航">
          {[
            ["/", "健康总览", <DashboardOutlined />],
            ["/records", "健康数据", <HeartOutlined />],
            ["/tasks", "健康任务", <ProfileOutlined />],
            ["/runs", "Agent 轨迹", <LineChartOutlined />],
          ].map(([path, label, icon]) => (
            <NavLink end to={String(path)} key={String(path)}>
              <span aria-hidden="true">{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>
        <p className="side-note">
          参赛演示作品
          <br />
          不用于诊断或治疗
        </p>
      </aside>
      <div className="workspace">
        <header>
          <span>我的健康空间</span>
          <Space wrap>
            <Tag color={client.mode === "http" ? "cyan" : "orange"}>
              {client.mode === "http" ? "真实 HTTP API" : "前端模拟数据"}
            </Tag>
            <Tag
              color={
                health?.status === "ok" && health.database.ok
                  ? "success"
                  : "error"
              }
            >
              {health?.status === "ok" && health.database.ok
                ? "后端已连接"
                : "后端连接失败"}
            </Tag>
            <span>llm_mode：{health?.llm_mode || "未知"}</span>
            <Select
              aria-label="当前演示患者"
              value={id || undefined}
              disabled={busy}
              placeholder="患者尚未同步"
              options={patients.map((p) => ({
                value: p.id,
                label: `${p.name} · ${p.id}`,
              }))}
              onChange={setId}
              style={{ minWidth: 210 }}
            />
          </Space>
        </header>
        <div className="disclosure">
          合成演示数据 ·{" "}
          {client.mode === "mock"
            ? "前端模拟 HTTP，未连接后端"
            : health?.llm_mode === "mock"
              ? "真实后端使用确定性规划器（未调用模型）；工具和数据库实际运行"
              : health?.llm_mode === "real"
                ? "后端返回 real 模式，请以每次运行结果为准"
                : "等待后端返回运行模式"}
        </div>
        <main>
          {error ? (
            <ErrorBox error={error} retry={() => void boot()} />
          ) : id ? (
            <PatientPanel key={id} id={id} busy={busy} setBusy={setBusy} />
          ) : (
            <Empty description={health ? "尚无演示患者" : "正在连接后端…"} />
          )}
        </main>
      </div>
    </div>
  );
}
function PatientPanel({
  id,
  busy,
  setBusy,
}: {
  id: string;
  busy: boolean;
  setBusy: (b: boolean) => void;
}) {
  const [bundle, setBundle] = useState<Bundle>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [writeResult, setWriteResult] = useState<
    RecordResult | CompleteResult
  >();
  const { message } = AntApp.useApp();
  const generation = useRef(0);
  const lock = useRef(false);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const ticket = ++generation.current;
      setLoading(true);
      try {
        const [state, records, tasks, runs] = await Promise.all([
          client.state(id, signal),
          client.records(id, signal),
          client.tasks(id, signal),
          client.runs(id, signal),
        ]);
        if (signal?.aborted || ticket !== generation.current) return false;
        if ([...records, ...tasks, ...runs].some((r) => r.patient_id !== id))
          throw new ApiError(
            "PATIENT_MISMATCH",
            "接口包含其他患者的数据，已拒绝展示",
          );
        setBundle({ state, records, tasks, runs });
        setError(undefined);
        return true;
      } catch (e) {
        if (!signal?.aborted && ticket === generation.current) {
          setBundle(undefined);
          setError(e);
        }
        return false;
      } finally {
        if (!signal?.aborted && ticket === generation.current)
          setLoading(false);
      }
    },
    [id],
  );
  useEffect(() => {
    const c = new AbortController();
    void refresh(c.signal);
    return () => c.abort();
  }, [refresh]);
  async function mutate(work: () => Promise<RecordResult | CompleteResult>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const result = await work();
      setWriteResult(result);
      const synced = await refresh();
      message[synced ? "success" : "warning"](
        synced
          ? "接口操作完成，已重新读取状态"
          : "写入响应已收到，状态尚未同步；请刷新核对",
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : "操作失败");
      setWriteResult(undefined);
      setError(e);
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">HEALTH MANAGEMENT</span>
          <h1>{bundle?.state.patient.name || id}的健康管理</h1>
          <p className="muted">记录、行动与执行证据，在同一个空间查看</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void refresh()}
          disabled={busy || loading}
        >
          刷新状态
        </Button>
      </div>
      {writeResult && (
        <Card
          title={
            "record" in writeResult
              ? "本次保存与自动触发响应"
              : "任务完成与复评响应"
          }
          className="result"
          data-testid="write-result"
        >
          <Json value={writeResult} />
          {"automation" in writeResult &&
            Array.isArray(writeResult.automation?.runs) &&
            (writeResult.automation.runs as { run_id: string }[]).map((r) => (
              <Link
                key={r.run_id}
                to={`/runs?run=${encodeURIComponent(r.run_id)}`}
              >
                查看运行 {r.run_id}　
              </Link>
            ))}
        </Card>
      )}
      {error && <ErrorBox error={error} retry={() => void refresh()} />}
      <Spin spinning={loading}>
        {bundle && (
          <Routes>
            <Route path="/" element={<Overview bundle={bundle} />} />
            <Route
              path="/records"
              element={
                <Records
                  records={bundle.records}
                  busy={busy}
                  submit={(v) => mutate(() => client.addRecord(id, v))}
                />
              }
            />
            <Route
              path="/tasks"
              element={
                <Tasks
                  tasks={bundle.tasks}
                  busy={busy}
                  complete={(t) => mutate(() => client.complete(t))}
                />
              }
            />
            <Route
              path="/runs"
              element={<Runs runs={bundle.runs} patientId={id} />}
            />
            <Route
              path="*"
              element={<Empty description="页面不存在，请使用侧边导航" />}
            />
          </Routes>
        )}
      </Spin>
    </>
  );
}
function Overview({ bundle: b }: { bundle: Bundle }) {
  const s = b.state;
  return (
    <>
      <section className="hero">
        <h2>每一次记录，让管理持续发生</h2>
        <p>当前只呈现后端提供的状态、事件与任务，不生成医学判断。</p>
        <Link to="/records">记录健康数据 →</Link>
      </section>
      <div className="metrics">
        {["fasting_glucose", "steps"].map((k) => (
          <Card key={k}>
            <Statistic
              title={`最近${labels[k]}`}
              value={s.latest[k]?.value ?? "未记录"}
              suffix={s.latest[k]?.unit}
            />
            <small>{s.latest[k]?.recorded_at || "尚无同步数据"}</small>
          </Card>
        ))}
        <Card>
          <Statistic title="未完成任务" value={s.open_tasks.length} />
          <Link to="/tasks">查看任务 →</Link>
        </Card>
      </div>
      <div className="grid">
        <Card title="近期血糖记录">
          <Chart records={b.records} until={s.generated_at} />
        </Card>
        <Card title="已确认的患者资料">
          <Descriptions
            column={1}
            items={[
              { key: "id", label: "患者", children: s.patient.id },
              { key: "age", label: "年龄", children: show(s.patient.age) },
              {
                key: "years",
                label: "病程（年）",
                children: show(s.patient.duration_years),
              },
              {
                key: "goals",
                label: "管理目标",
                children: s.patient.goals.join("；") || "未提供",
              },
              {
                key: "constraints",
                label: "约束",
                children: s.patient.constraints.join("；") || "未提供",
              },
            ]}
          />
          <p>缺失字段：{s.missing_fields.join("、") || "后端未报告缺失字段"}</p>
          <p>后端趋势：{show(s.trend)}</p>
        </Card>
      </div>
      <div className="grid">
        <Card title="当前事件">
          {s.open_events.length ? (
            s.open_events.map((e) => (
              <div className="list-row" key={show(e.id)}>
                <strong>{show(e.code)}</strong>
                <Tag>{show(e.severity)}</Tag>
                <p>{show(e.message)}</p>
              </div>
            ))
          ) : (
            <Empty description="暂无当前事件" />
          )}
        </Card>
        <Card title="待回答问题">
          {s.pending_questions.length ? (
            s.pending_questions.map((q) => (
              <div className="list-row" key={show(q.id)}>
                <p>{show(q.question)}</p>
                <code>
                  {show(q.id)} · {show(q.status)}
                </code>
                <p className="muted">主动回答与恢复操作将在第二阶段接入。</p>
              </div>
            ))
          ) : (
            <Empty description="暂无待回答问题" />
          )}
        </Card>
      </div>
    </>
  );
}
function Records({
  records,
  busy,
  submit,
}: {
  records: HealthRecord[];
  busy: boolean;
  submit: (v: RecordCreate) => Promise<void>;
}) {
  const [form] = Form.useForm();
  const kind = Form.useWatch("kind", form) || "fasting_glucose";
  const [error, setError] = useState("");
  return (
    <>
      <Card title="录入健康数据" extra="按 RecordCreate 模型提交">
        <Form
          form={form}
          layout="vertical"
          initialValues={{ kind: "fasting_glucose", payload: "{}" }}
          onFinish={async (values) => {
            setError("");
            try {
              const payload: unknown = JSON.parse(values.payload || "{}");
              if (
                !payload ||
                typeof payload !== "object" ||
                Array.isArray(payload)
              )
                throw new Error("扩展字段需要 JSON 对象");
              const record: RecordCreate = {
                kind: values.kind,
                value: values.value ?? null,
                payload: payload as Record<string, unknown>,
                trigger_agent: true,
              };
              if (values.recorded_at)
                record.recorded_at = new Date(values.recorded_at).toISOString();
              if (values.unit) record.unit = values.unit;
              if (values.note) record.note = values.note;
              await submit(record);
            } catch (e) {
              setError(e instanceof Error ? e.message : "字段错误");
            }
          }}
        >
          <div className="form-grid">
            <Form.Item
              name="kind"
              label="记录类型"
              rules={[{ required: true }]}
            >
              <Select
                onChange={() =>
                  form.setFieldsValue({
                    value: undefined,
                    unit: undefined,
                    payload: "{}",
                  })
                }
                options={recordKinds.map((k) => ({
                  value: k,
                  label: labels[k],
                }))}
              />
            </Form.Item>
            <Form.Item
              name="value"
              label={
                kind === "medication_taken"
                  ? "服药确认（按原处方）"
                  : "记录数值"
              }
              rules={[
                {
                  required: !["bp", "meal", "symptom"].includes(kind),
                  message: "请填写记录数值",
                },
              ]}
            >
              {kind === "medication_taken" ? (
                <Select
                  options={[
                    { value: 1, label: "已按原处方服药" },
                    { value: 0, label: "未服药" },
                  ]}
                />
              ) : (
                <InputNumber style={{ width: "100%" }} />
              )}
            </Form.Item>
            <Form.Item
              name="recorded_at"
              label="记录时间（本地时间，留空使用后端演示时钟）"
            >
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item name="unit" label="单位（留空使用后端默认单位）">
              <Input placeholder="如 mmol/L、步、kg" />
            </Form.Item>
          </div>
          <Form.Item name="note" label="备注">
            <Input.TextArea maxLength={500} />
          </Form.Item>
          <Form.Item
            name="payload"
            label="扩展字段 JSON"
            help="症状：text；血压：systolic、diastolic；其他类型可留空对象"
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          {error && <Alert type="error" title={error} />}
          <Button
            type="primary"
            icon={<SaveOutlined />}
            htmlType="submit"
            loading={busy}
          >
            保存并查看自动触发结果
          </Button>
          <p className="muted">
            仅调用记录接口。是否触发事件与 Agent 完全由后端决定，无额外运行
            Agent 请求。
          </p>
        </Form>
      </Card>
      <Card title="近 7 天健康记录">
        <Table
          rowKey="id"
          dataSource={records}
          scroll={{ x: 650 }}
          columns={[
            { title: "记录时间（UTC）", dataIndex: "recorded_at" },
            { title: "类型", dataIndex: "kind", render: (v) => labels[v] || v },
            { title: "数值", dataIndex: "value", render: show },
            { title: "单位", dataIndex: "unit" },
            { title: "记录 ID", dataIndex: "id" },
          ]}
        />
      </Card>
    </>
  );
}
function Tasks({
  tasks,
  busy,
  complete,
}: {
  tasks: Task[];
  busy: boolean;
  complete: (id: string) => Promise<void>;
}) {
  return (
    <Card title="健康任务" extra="状态与优先级来自后端">
      <Table
        rowKey="id"
        dataSource={tasks}
        scroll={{ x: 960 }}
        expandable={{ expandedRowRender: (t) => <Json value={t} /> }}
        columns={[
          { title: "任务", dataIndex: "title" },
          {
            title: "状态",
            dataIndex: "status",
            render: (v) => <Status value={v} />,
          },
          { title: "优先级", dataIndex: "priority" },
          { title: "截止时间", dataIndex: "due_at", render: show },
          {
            title: "来源运行",
            dataIndex: "source_run_id",
            render: (v) =>
              v ? (
                <Link to={`/runs?run=${encodeURIComponent(v)}`}>{v}</Link>
              ) : (
                "未提供"
              ),
          },
          {
            title: "操作",
            render: (_, t) => (
              <Popconfirm
                title="确认此管理任务已完成？"
                onConfirm={() => complete(t.id)}
                disabled={busy || !["pending", "missed"].includes(t.status)}
              >
                <Button
                  disabled={busy || !["pending", "missed"].includes(t.status)}
                >
                  标记完成
                </Button>
              </Popconfirm>
            ),
          },
        ]}
        locale={{ emptyText: "暂无健康任务" }}
      />
    </Card>
  );
}
function Runs({ runs, patientId }: { runs: Run[]; patientId: string }) {
  const [retryVersion, setRetryVersion] = useState(0);
  const [params, setParams] = useSearchParams();
  const selected = params.get("run") || "";
  const [query, setQuery] = useState("");
  const [trace, setTrace] = useState<Trace>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setTrace(undefined);
    setError(undefined);
    if (!selected) return;
    const c = new AbortController();
    setLoading(true);
    client
      .trace(selected, c.signal)
      .then((t) => {
        if (c.signal.aborted) return;
        if (t.run.patient_id !== patientId)
          throw new ApiError(
            "PATIENT_MISMATCH",
            "此运行属于其他患者，已拒绝展示",
          );
        setTrace(t);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(e);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [selected, patientId, retryVersion]);
  return (
    <>
      <Card
        title="Agent 运行轨迹"
        extra={
          <Input.Search
            aria-label="查询 run_id"
            placeholder="输入 run_id 查询"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onSearch={(v) => setParams({ run: v.trim() })}
          />
        }
      >
        <Table
          rowKey="id"
          dataSource={runs}
          scroll={{ x: 850 }}
          columns={[
            {
              title: "运行标识",
              dataIndex: "id",
              render: (v) => (
                <Button type="link" onClick={() => setParams({ run: v })}>
                  {v}
                </Button>
              ),
            },
            { title: "触发来源", dataIndex: "trigger_type" },
            {
              title: "状态",
              dataIndex: "status",
              render: (v) => <Status value={v} />,
            },
            { title: "后端模式", dataIndex: "llm_mode" },
            { title: "开始时间", dataIndex: "started_at" },
          ]}
          locale={{ emptyText: "尚无 Agent 运行记录" }}
        />
      </Card>
      <Drawer
        title={`运行证据 · ${selected}`}
        open={!!selected}
        onClose={() => setParams({})}
        size="large"
      >
        <Spin spinning={loading}>
          {error ? (
            <ErrorBox
              error={error}
              retry={() => {
                setRetryVersion((v) => v + 1);
              }}
            />
          ) : (
            trace && (
              <>
                <Status value={trace.run.status} />
                <p>
                  触发来源：{trace.run.trigger_type} · llm_mode：
                  {trace.run.llm_mode}
                </p>
                <h3>执行阶段与真实工具返回</h3>
                <Timeline
                  items={trace.steps.map((s) => ({
                    color:
                      s.status === "failed" || s.status === "rejected"
                        ? "red"
                        : "green",
                    content: (
                      <>
                        <strong>
                          {s.step_no} · {s.phase} / {s.kind} /{" "}
                          {s.tool_name || "—"}
                        </strong>
                        <p>
                          {s.status} · {s.code || "无拒绝码"}
                        </p>
                        <details>
                          <summary>输入 / 返回详情</summary>
                          <Json value={s.payload} />
                        </details>
                      </>
                    ),
                  }))}
                />
                <h3>实际引用的证据</h3>
                {trace.evidence.length ? (
                  trace.evidence.map((e, i) => <Json key={i} value={e} />)
                ) : (
                  <Empty description="本次运行没有返回引用证据" />
                )}
                <h3>关联任务</h3>
                <Json value={trace.tasks} />
                <h3>执行结果、拒绝原因与原始运行</h3>
                <Json value={trace.run} />
              </>
            )
          )}
        </Spin>
      </Drawer>
    </>
  );
}
