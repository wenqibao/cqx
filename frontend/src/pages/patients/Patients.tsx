import { useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Table,
  Tag,
} from "antd";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useWorkbench } from "../../app/WorkbenchContext";
import { client } from "../../api/client";
import { api } from "../../api/workbench";
import { useResource } from "../../hooks/useResource";
import {
  DataView,
  Debug,
  ErrorBox,
  Heading,
  PatientScope,
  Status,
  RunLink,
} from "../../components/common";
import { TrendChart } from "../../components/TrendChart";
import { link, name, text, when } from "../../utils/format";
import { Tabs, Descriptions, Select, Alert } from "antd";
export default function Patients() {
  const { boot, busy, perform, refresh } = useWorkbench();
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<unknown>();
  const [form] = Form.useForm();
  return (
    <>
      <Heading
        title="患者管理"
        description="仅管理合成病例，档案与操作始终绑定患者 ID。"
        extra={
          <Button type="primary" onClick={() => setOpen(true)}>
            新建合成患者
          </Button>
        }
      />
      <Card>
        <Input.Search
          aria-label="检索患者"
          placeholder="搜索患者 ID 或姓名"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="search"
        />
        <Table
          rowKey="id"
          dataSource={boot?.patients.filter((p) =>
            (p.id + p.name).toLowerCase().includes(search.toLowerCase()),
          )}
          scroll={{ x: 800 }}
          columns={[
            {
              title: "患者",
              render: (_, p) => (
                <Link to={link("/patients/" + encodeURIComponent(p.id), p.id)}>
                  {p.name}
                  <small className="block muted">{p.id}</small>
                </Link>
              ),
            },
            { title: "年龄", dataIndex: "age", render: text },
            { title: "病程（年）", dataIndex: "duration_years", render: text },
            {
              title: "已确认目标",
              dataIndex: "goals",
              render: (v) => (v.length ? v.join("；") : "未提供"),
            },
            {
              title: "数据标识",
              render: (_, p) => (
                <Tag color={p.is_synthetic ? "cyan" : "error"}>
                  {p.is_synthetic ? "合成病例" : "非演示数据"}
                </Tag>
              ),
            },
            {
              title: "操作",
              render: (_, p) => (
                <Link to={link("/patients/" + encodeURIComponent(p.id), p.id)}>
                  进入健康档案
                </Link>
              ),
            },
          ]}
        />
      </Card>
      <Modal
        title="新建合成患者"
        open={open}
        onCancel={() => !busy && setOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={async (v) => {
            setError(undefined);
            try {
              await perform(() =>
                api.createPatient({
                  name: v.name,
                  age: v.age,
                  duration_years: v.duration_years,
                  goals: v.goals ? [v.goals] : [],
                  constraints: v.constraints ? [v.constraints] : [],
                }),
              );
              refresh();
              form.resetFields();
              setOpen(false);
            } catch (e) {
              setError(e);
            }
          }}
        >
          <Form.Item
            label="患者姓名（虚构）"
            name="name"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={60} />
          </Form.Item>
          <div className="two-columns">
            <Form.Item label="年龄" name="age">
              <InputNumber min={18} max={120} />
            </Form.Item>
            <Form.Item label="病程（年）" name="duration_years">
              <InputNumber min={0} max={100} />
            </Form.Item>
          </div>
          <Form.Item label="已确认管理目标" name="goals">
            <Input />
          </Form.Item>
          <Form.Item label="已知约束" name="constraints">
            <Input />
          </Form.Item>
          <Form.Item
            name="synthetic"
            valuePropName="checked"
            rules={[
              {
                validator: (_, v) =>
                  v
                    ? Promise.resolve()
                    : Promise.reject(new Error("仅允许合成患者")),
              },
            ]}
          >
            <Checkbox>确认全部信息为虚构演示数据</Checkbox>
          </Form.Item>
          {!!error && <ErrorBox error={error} />}
          <Button type="primary" htmlType="submit" loading={busy}>
            创建并重新读取患者列表
          </Button>
        </Form>
      </Modal>
    </>
  );
}
export function PatientDetail() {
  return (
    <PatientScope>
      <Detail />
    </PatientScope>
  );
}
function Detail() {
  const { patientId, patient } = useWorkbench();
  const params = useParams();
  const [query, setQuery] = useSearchParams();
  const [days, setDays] = useState(7);
  const id = params.id || patientId;
  const tab = query.get("tab") || "profile";
  const resource = useResource(`patient:${id}:${days}`, async (s) => {
    const profile = await api.patient(id, s);
    const state = await client.state(id, s);
    const records = await api.records(id, days, s);
    const history = await api.history(id, s);
    const events = await api.events(id, s);
    const tasks = await client.tasks(id, s);
    const questions = await api.questions(id, s);
    const preferences = await api.preferences(id, s);
    return {
      profile,
      state,
      records,
      history,
      events,
      tasks,
      questions,
      preferences,
    };
  });
  return (
    <>
      <Heading
        title="患者健康档案"
        description={`${patient?.name || id} · ${id} · 合成病例；档案暂为只读，未实现不存在的保存接口。`}
        extra={<Button onClick={resource.reload}>刷新档案</Button>}
      />
      <DataView resource={resource}>
        {(d) => (
          <>
            <div className="patient-summary">
              <div className="patient-avatar">{d.profile.name.slice(0, 1)}</div>
              <div>
                <h2>{d.profile.name}</h2>
                <span>
                  {id} · {text(d.profile.age)} 岁 · 病程{" "}
                  {text(d.profile.duration_years)} 年
                </span>
              </div>
              <div className="summary-spacer" />
              <Tag color="cyan">合成患者</Tag>
              <Tag>
                {d.state.profile_complete ? "基础档案完整" : "基础档案存在缺项"}
              </Tag>
            </div>
            <Tabs
              activeKey={tab}
              onChange={(key) => {
                const next = new URLSearchParams(query);
                next.set("tab", key);
                setQuery(next);
              }}
              items={[
                {
                  key: "profile",
                  label: "基础档案与状态",
                  children: (
                    <div className="two-columns">
                      <Card title="基础健康资料">
                        <Descriptions
                          column={1}
                          items={[
                            {
                              key: "goals",
                              label: "已确认目标",
                              children: d.profile.goals.join("；") || "未提供",
                            },
                            {
                              key: "constraints",
                              label: "约束",
                              children:
                                d.profile.constraints.join("；") || "未提供",
                            },
                            {
                              key: "complete",
                              label: "档案完整度",
                              children: d.profile.profile?.complete
                                ? "完整"
                                : "存在缺项",
                            },
                            {
                              key: "missing",
                              label: "尚缺字段",
                              children:
                                d.state.missing_fields.map(name).join("、") ||
                                "当前无缺项",
                            },
                            {
                              key: "trend",
                              label: "后端趋势",
                              children: text(d.state.trend),
                            },
                          ]}
                        />
                        <Alert
                          type="info"
                          title="以上为后端健康管理状态，不是医学诊断。"
                        />
                        <Debug
                          value={d.state.aggregates}
                          label="查看后端 3日/7日/14日聚合"
                        />
                      </Card>
                      <Card title="当前有效偏好">
                        <Table
                          rowKey="id"
                          size="small"
                          pagination={false}
                          dataSource={d.preferences.filter(
                            (p) => p.status === "active",
                          )}
                          columns={[
                            { title: "类型", dataIndex: "kind", render: name },
                            { title: "值", dataIndex: "value" },
                            { title: "来源", dataIndex: "source" },
                          ]}
                        />
                        <Link
                          to={link("/followups", id, { tab: "preferences" })}
                        >
                          查看偏好历史及模拟确认入口 →
                        </Link>
                      </Card>
                    </div>
                  ),
                },
                {
                  key: "records",
                  label: "记录与趋势",
                  children: (
                    <Card
                      title="健康记录"
                      extra={
                        <Select
                          aria-label="记录时间窗口"
                          value={days}
                          options={[3, 7, 14].map((v) => ({
                            value: v,
                            label: `近 ${v} 天`,
                          }))}
                          onChange={setDays}
                        />
                      }
                    >
                      <TrendChart records={d.records} />
                      <Table
                        rowKey="id"
                        dataSource={d.records}
                        scroll={{ x: 750 }}
                        columns={[
                          {
                            title: "记录类型",
                            dataIndex: "kind",
                            render: name,
                          },
                          {
                            title: "值 / 内容",
                            render: (_, r) =>
                              r.value === null
                                ? text(r.payload)
                                : `${r.value} ${r.unit}`,
                          },
                          {
                            title: "记录时间",
                            dataIndex: "recorded_at",
                            render: when,
                          },
                          { title: "备注", dataIndex: "note", render: text },
                        ]}
                      />
                    </Card>
                  ),
                },
                {
                  key: "events",
                  label: `事件 ${d.events.length}`,
                  children: (
                    <Card>
                      <Table
                        rowKey="id"
                        dataSource={d.events}
                        scroll={{ x: 800 }}
                        columns={[
                          {
                            title: "管理事件",
                            dataIndex: "code",
                            render: name,
                          },
                          {
                            title: "规则级别",
                            dataIndex: "severity",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "状态",
                            dataIndex: "status",
                            render: (v) => <Status value={v} />,
                          },
                          { title: "触发原因", dataIndex: "message" },
                          {
                            title: "关联运行",
                            dataIndex: "handled_by_run",
                            render: (v) => <RunLink id={v} patient={id} />,
                          },
                        ]}
                        expandable={{
                          expandedRowRender: (r) => (
                            <Debug value={r.evidence} label="事件规则依据" />
                          ),
                        }}
                      />
                    </Card>
                  ),
                },
                {
                  key: "tasks",
                  label: `管理任务 ${d.tasks.length}`,
                  children: (
                    <Card>
                      <Table
                        rowKey="id"
                        dataSource={d.tasks}
                        columns={[
                          {
                            title: "任务",
                            render: (_, t) => (
                              <Link to={link("/tasks", id, { task: t.id })}>
                                {t.title}
                              </Link>
                            ),
                          },
                          {
                            title: "状态",
                            dataIndex: "status",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "截止时间",
                            dataIndex: "due_at",
                            render: when,
                          },
                          {
                            title: "来源运行",
                            dataIndex: "source_run_id",
                            render: (v) => <RunLink id={v} patient={id} />,
                          },
                        ]}
                        scroll={{ x: 750 }}
                      />
                    </Card>
                  ),
                },
                {
                  key: "questions",
                  label: `随访问题 ${d.questions.length}`,
                  children: (
                    <Card>
                      <Table
                        rowKey="id"
                        dataSource={d.questions}
                        columns={[
                          { title: "问题", dataIndex: "question" },
                          {
                            title: "状态",
                            dataIndex: "status",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "操作",
                            render: (_, q) => (
                              <Link
                                to={link("/followups", id, { question: q.id })}
                              >
                                查看模拟答复
                              </Link>
                            ),
                          },
                        ]}
                      />
                    </Card>
                  ),
                },
                {
                  key: "history",
                  label: "状态快照",
                  children: (
                    <Card title="已保存的状态版本">
                      <Alert
                        type="info"
                        title="当前接口仅返回版本号与保存时间，不提供旧快照正文。"
                      />
                      <Table
                        rowKey="version"
                        dataSource={d.history.snapshots}
                        columns={[
                          { title: "版本", dataIndex: "version" },
                          {
                            title: "保存时间",
                            dataIndex: "created_at",
                            render: when,
                          },
                        ]}
                      />
                    </Card>
                  ),
                },
              ]}
            />
          </>
        )}
      </DataView>
    </>
  );
}
