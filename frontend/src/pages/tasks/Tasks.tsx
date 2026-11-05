import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Table,
  Tabs,
  Timeline,
} from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { client } from "../../api/client";
import { api, type Review } from "../../api/workbench";
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
import { link, name, text, when } from "../../utils/format";
export default function Tasks() {
  const { patientId, patient, busy, perform } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "tasks";
  const taskId = params.get("task") || "";
  const [error, setError] = useState<unknown>();
  const [result, setResult] = useState<unknown>();
  const resource = useResource("tasks:" + patientId, async (s) => ({
    tasks: await client.tasks(patientId, s),
    reviews: await api.reviews(patientId, s),
    events: await api.events(patientId, s),
    preferences: await api.preferences(patientId, s),
  }));
  async function act(action: () => Promise<unknown>) {
    setError(undefined);
    setResult(undefined);
    try {
      setResult(await perform(action));
      resource.reload();
    } catch (e) {
      setError(e);
    }
  }
  const set = (values: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(values).forEach(([k, v]) =>
      v ? next.set(k, v) : next.delete(k),
    );
    setParams(next);
  };
  return (
    <>
      <Heading
        title="任务与复评"
        description={`${patient?.name} · ${patientId}；任务依据、计划版本与后续复评均来自实际业务记录。`}
        extra={<Button onClick={resource.reload}>刷新任务与复评</Button>}
      />
      <Tabs
        activeKey={tab}
        onChange={(v) => set({ tab: v })}
        items={[
          {
            key: "tasks",
            label: "管理任务",
            children: (
              <Card title="健康管理计划">
                <DataView resource={resource}>
                  {(d) => (
                    <Table
                      rowKey="id"
                      dataSource={d.tasks}
                      scroll={{ x: 1100 }}
                      columns={[
                        {
                          title: "任务 / 类型",
                          render: (_, t) => (
                            <>
                              <Button
                                type="link"
                                onClick={() => set({ task: t.id })}
                              >
                                {t.title}
                              </Button>
                              <small className="block mono muted">
                                {t.task_type} · {t.id}
                              </small>
                            </>
                          ),
                        },
                        {
                          title: "状态",
                          dataIndex: "status",
                          render: (v) => <Status value={v} />,
                        },
                        { title: "优先级", dataIndex: "priority" },
                        {
                          title: "截止时间",
                          dataIndex: "due_at",
                          render: when,
                        },
                        { title: "版本", dataIndex: "version", render: text },
                        {
                          title: "来源运行",
                          dataIndex: "source_run_id",
                          render: (v) => <RunLink id={v} patient={patientId} />,
                        },
                        {
                          title: "操作",
                          render: (_, t) => (
                            <Popconfirm
                              title="医护演示工作人员确认此管理任务已完成？"
                              description="changed_by=staff_demo；执行规则复评，不额外运行模型。"
                              disabled={
                                busy ||
                                !["pending", "missed"].includes(t.status)
                              }
                              onConfirm={() => act(() => client.complete(t.id))}
                            >
                              <Button
                                disabled={
                                  busy ||
                                  !["pending", "missed"].includes(t.status)
                                }
                              >
                                标记完成
                              </Button>
                            </Popconfirm>
                          ),
                        },
                      ]}
                      expandable={{
                        expandedRowRender: (t) => (
                          <>
                            <p>
                              创建原因：{t.description || "后端未提供具体说明"}
                            </p>
                            <p>
                              关联事件：
                              {d.events.find((e) => e.id === t.event_id)
                                ?.message ||
                                t.event_id ||
                                "无关联事件"}
                            </p>
                            <p>元数据 / 合并来源：{text(t.meta)}</p>
                            <p>
                              已确认偏好：
                              {d.preferences
                                .filter((p) => p.status === "active")
                                .map((p) => `${name(p.kind)}：${p.value}`)
                                .join("；") || "无生效偏好"}
                              （展示当前上下文，不推断它们曾影响此任务）
                            </p>
                            <p>完成时间：{when(t.completed_at)}</p>
                            <Link
                              to={link("/agent", patientId, {
                                tab: "negotiate",
                              })}
                            >
                              由 Agent 协商改期 →
                            </Link>
                          </>
                        ),
                      }}
                    />
                  )}
                </DataView>
              </Card>
            ),
          },
          {
            key: "reviews",
            label: "动态复评与人工复核",
            children: (
              <>
                <Alert
                  type="info"
                  title="三分支 CLOSED / MISSING_DATA / HUMAN_REVIEW 仅在后端实际返回记录时展示。人工结案内容由工作人员填写，不由 Agent 代写。"
                />
                <DataView resource={resource}>
                  {(d) => (
                    <>
                      <div
                        className="stats-grid"
                        style={{
                          gridTemplateColumns: "repeat(3,minmax(0,1fr))",
                        }}
                      >
                        {["CLOSED", "MISSING_DATA", "HUMAN_REVIEW"].map(
                          (branch) => (
                            <div className="stat" key={branch}>
                              <span>{name(branch)}</span>
                              <strong>
                                {
                                  d.reviews.filter((r) => r.branch === branch)
                                    .length
                                }
                              </strong>
                              <small className="muted">
                                实际已返回复评记录
                              </small>
                            </div>
                          ),
                        )}
                      </div>
                      {d.reviews.length ? (
                        d.reviews.map((r) => (
                          <ReviewCard
                            key={r.id}
                            review={r}
                            patientId={patientId}
                            busy={busy}
                            resolve={(decision, note) =>
                              act(() => api.resolve(r.id, decision, note))
                            }
                          />
                        ))
                      ) : (
                        <Card>
                          <p className="muted">
                            暂无复评记录。完成任务或已有调度作业到期后再查询。
                          </p>
                        </Card>
                      )}
                    </>
                  )}
                </DataView>
              </>
            ),
          },
        ]}
      />
      {error && <ErrorBox error={error} />}
      {result !== undefined && (
        <WriteResult value={result} patientId={patientId} />
      )}
      <Drawer
        title="任务详情与计划版本"
        open={!!taskId}
        width={680}
        onClose={() => set({ task: "" })}
        destroyOnHidden
      >
        {taskId && (
          <TaskDetail
            id={taskId}
            patientId={patientId}
            busy={busy}
            reschedule={(due, reason) =>
              act(() => api.reschedule(taskId, due, reason))
            }
            revision={result}
          />
        )}
      </Drawer>
    </>
  );
}
function TaskDetail({
  id,
  patientId,
  busy,
  reschedule,
  revision,
}: {
  id: string;
  patientId: string;
  busy: boolean;
  reschedule: (due: string, reason: string) => Promise<void>;
  revision: unknown;
}) {
  const resource = useResource(`task:${id}:${JSON.stringify(revision)}`, (s) =>
    api.task(id, s).then((d) => {
      if (d.task.patient_id !== patientId)
        throw new Error("任务不属于当前患者，拒绝展示及操作");
      return d;
    }),
  );
  return (
    <DataView resource={resource}>
      {(d) => (
        <>
          <h2>{d.task.title}</h2>
          <p className="mono">{d.task.id}</p>
          <Descriptions
            column={1}
            items={[
              {
                key: "status",
                label: "状态",
                children: <Status value={d.task.status} />,
              },
              {
                key: "time",
                label: "当前截止时间",
                children: when(d.task.due_at),
              },
              {
                key: "run",
                label: "创建来源",
                children: (
                  <RunLink id={d.task.source_run_id} patient={patientId} />
                ),
              },
            ]}
          />
          <Card title="医护工作人员直接调整普通管理任务">
            <Alert
              type="info"
              title="人工操作 · staff_demo；此操作不是 DeepSeek 自主规划。"
            />
            <Form
              layout="vertical"
              onFinish={(v) =>
                reschedule(new Date(v.time).toISOString(), v.reason)
              }
            >
              <Form.Item
                label="新的截止时间（本地时间）"
                name="time"
                rules={[{ required: true }]}
              >
                <Input type="datetime-local" />
              </Form.Item>
              <Form.Item
                label="工作人员调整原因"
                name="reason"
                rules={[{ required: true, whitespace: true }]}
              >
                <Input maxLength={300} />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                disabled={
                  busy || !["pending", "missed"].includes(d.task.status)
                }
                loading={busy}
              >
                人工确认改期并保存版本
              </Button>
            </Form>
          </Card>
          <Card title="原计划与历次变更">
            <Timeline
              items={d.versions.map((v) => ({
                children: (
                  <>
                    <strong>
                      v{v.version} · {v.change_kind}
                    </strong>
                    <p>
                      {when(v.created_at)} · {name(v.changed_by)}
                    </p>
                    <p>
                      截止：{when(v.snapshot.due_at)} ·{" "}
                      {name(v.snapshot.status)}
                    </p>
                    <p>{v.reason}</p>
                    <RunLink id={v.run_id} patient={patientId} />
                  </>
                ),
              }))}
            />
          </Card>
        </>
      )}
    </DataView>
  );
}
export function ReviewCard({
  review: r,
  patientId,
  busy,
  resolve,
}: {
  review: Review;
  patientId: string;
  busy: boolean;
  resolve: (decision: string, note: string) => Promise<void>;
}) {
  return (
    <Card
      title={
        <>
          <Status value={r.branch} /> <Status value={r.status} />
        </>
      }
      id={r.id}
    >
      <p>{r.reason}</p>
      <p className="muted">
        {r.id} · 计划复评 {when(r.scheduled_for)} · 结案 {when(r.resolved_at)}
      </p>
      <p>
        关联任务：
        {r.task_id ? (
          <Link to={link("/tasks", patientId, { task: r.task_id })}>
            {r.task_id}
          </Link>
        ) : (
          "无"
        )}{" "}
        · <RunLink id={r.run_id} patient={patientId} />
      </p>
      <Debug value={r.detail} label="复评依据与人工处理记录" />
      {r.branch === "HUMAN_REVIEW" && r.status === "pending_human" && (
        <Form
          layout="vertical"
          onFinish={(v) => resolve(v.decision, v.note)}
          style={{ marginTop: 18 }}
        >
          <Alert
            type="warning"
            title="人工复核结案需工作人员确认。此记录不等于提供医疗处置，接口暂不含独立工作人员身份字段。"
          />
          <Form.Item
            label="人工复核结论"
            name="decision"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            label="人工处理备注"
            name="note"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>
            确认人工复核结案
          </Button>
        </Form>
      )}
    </Card>
  );
}
