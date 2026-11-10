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
  ErrorBox,
  Heading,
  RunLink,
  Status,
  WriteResult,
  TechnicalLog,
} from "../../components/common";
import { businessText, businessName } from "../../utils/business";
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
        description={`${patient?.name} · 跟进任务、调整时间和查看复评`}
        extra={
          <>
            <Button onClick={resource.reload}>刷新任务与复评</Button>
            <TechnicalLog
              value={{ ...resource.data, last_result: result }}
              label="任务与复评日志"
            />
          </>
        }
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
                                {businessText(t.title)}
                              </Button>
                              <small className="block mono muted">
                                {businessName(t.task_type)}
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
                              title="确认任务已完成？"
                              description="完成后将发起复评。"
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
                              创建原因：
                              {businessText(
                                t.description,
                                "后端未提供具体说明",
                              )}
                            </p>
                            <p>
                              关联事件：
                              {d.events.find((e) => e.id === t.event_id)
                                ?.message || "未返回关联事件说明"}
                            </p>

                            <p>
                              已确认偏好：
                              {d.preferences
                                .filter((p) => p.status === "active")
                                .map((p) => `${name(p.kind)}：${p.value}`)
                                .join("；") || "无生效偏好"}
                              （当前生效偏好）
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
          <p>{businessText(d.task.description)}</p>
          <TechnicalLog value={d} label="任务日志" />

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
                      版本 {v.version} · {businessName(v.change_kind)}
                    </strong>
                    <p>
                      {when(v.created_at)} · {name(v.changed_by)}
                    </p>
                    <p>
                      截止：{when(v.snapshot.due_at)} ·{" "}
                      {name(v.snapshot.status)}
                    </p>
                    <p>{businessText(v.reason)}</p>

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
      <p>{businessText(r.reason)}</p>
      <p>
        当前待办：
        {r.branch === "HUMAN_REVIEW" && r.status === "pending_human"
          ? "请医护人员核查依据并记录复核结论。"
          : r.branch === "MISSING_DATA"
            ? "请补充缺失记录后跟进复评。"
            : "请查看复评结果与任务状态。"}
      </p>
      <p className="muted">
        计划复评 {when(r.scheduled_for)} · 结案 {when(r.resolved_at)}
      </p>
      <p>
        关联任务：
        {r.task_id ? (
          <Link to={link("/tasks", patientId, { task: r.task_id })}>
            查看关联管理任务
          </Link>
        ) : (
          "无"
        )}{" "}
        · <RunLink id={r.run_id} patient={patientId} />
      </p>

      {r.branch === "HUMAN_REVIEW" && r.status === "pending_human" && (
        <Form
          layout="vertical"
          onFinish={(v) => resolve(v.decision, v.note)}
          style={{ marginTop: 18 }}
        >
          <Alert type="warning" title="请核查相关记录后填写复核结论。" />
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
