import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Popconfirm,
  Select,
  Table,
  Tabs,
} from "antd";
import { useSearchParams } from "react-router-dom";
import { api, type Question } from "../../api/workbench";
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
import { businessName, businessText } from "../../utils/business";
import { name, when } from "../../utils/format";
export default function Followups() {
  const { patientId, patient, busy, perform } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "questions";
  const [error, setError] = useState<unknown>();
  const [result, setResult] = useState<unknown>();
  const resource = useResource("followups:" + patientId, async (s) => ({
    questions: await api.questions(patientId, s),
    preferences: await api.preferences(patientId, s),
  }));
  useEffect(() => {
    const id = params.get("question");
    if (!id || !resource.data?.questions.some((q) => q.id === id)) return;
    const el = document.getElementById(id);
    el?.scrollIntoView({ block: "center", behavior: "auto" });
    el?.querySelector<HTMLTextAreaElement>("textarea")?.focus({
      preventScroll: true,
    });
  }, [params, resource.data]);
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
  return (
    <>
      <Heading
        title="智能随访"
        description={`${patient?.name} · 回答随访问题，跟进健康管理安排`}
        extra={
          <>
            <Button onClick={resource.reload}>刷新随访</Button>
            <TechnicalLog
              value={{ ...resource.data, last_result: result }}
              label="随访日志"
            />
          </>
        }
      />
      <Tabs
        activeKey={tab}
        onChange={(key) => {
          const n = new URLSearchParams(params);
          n.set("tab", key);
          setParams(n);
        }}
        items={[
          {
            key: "questions",
            label: "主动提问与答复",
            children: (
              <>
                <p className="action-note">当前以工作人员身份模拟患者答复。</p>
                <CostNotice />
                <DataView resource={resource}>
                  {(d) =>
                    d.questions.length ? (
                      [...d.questions]
                        .sort(
                          (a, b) =>
                            Number(b.id === params.get("question")) -
                            Number(a.id === params.get("question")),
                        )
                        .map((q) => (
                          <Card
                            title={
                              <>
                                <Status value={q.status} />{" "}
                                {q.target_field
                                  ? name(q.target_field)
                                  : "随访问题"}
                              </>
                            }
                            key={q.id}
                            id={q.id}
                            className={
                              params.get("question") === q.id
                                ? "focused-object"
                                : ""
                            }
                          >
                            <div className="conversation-message agent-message">
                              <span className="message-speaker">
                                Agent 提问
                              </span>
                              <h3>{businessText(q.question)}</h3>
                            </div>
                            <p className="muted">
                              {when(q.created_at)} · 来源{" "}
                              <RunLink id={q.run_id} patient={patientId} />
                            </p>
                            {q.status === "waiting" ? (
                              <AnswerForm
                                question={q}
                                busy={busy}
                                submit={(answer) =>
                                  act(() => api.answer(q.id, answer))
                                }
                              />
                            ) : (
                              <>
                                <p className="conversation-message patient-message">
                                  患者答复：{q.answer_text || "未提供文本"}{" "}
                                  {q.answer &&
                                  typeof q.answer === "object" &&
                                  "uncertain" in q.answer &&
                                  q.answer.uncertain === true
                                    ? "（尚不确定）"
                                    : ""}
                                </p>
                              </>
                            )}
                          </Card>
                        ))
                    ) : (
                      <Card>
                        <p className="muted">
                          暂无随访问题；前往 Agent
                          决策中心发起一次健康记录缺项核实。
                        </p>
                      </Card>
                    )
                  }
                </DataView>
              </>
            ),
          },
          {
            key: "preferences",
            label: "长期偏好与历史",
            children: (
              <>
                <div className="two-columns">
                  <Card title="保存模拟患者偏好">
                    <Form
                      layout="vertical"
                      initialValues={{
                        kind: "preferred_time_window",
                        source: "patient_input",
                      }}
                      onFinish={(v) =>
                        act(() =>
                          api.savePreference(
                            patientId,
                            v.kind,
                            v.value,
                            v.source,
                          ),
                        )
                      }
                    >
                      <Form.Item
                        label="偏好类型"
                        name="kind"
                        rules={[{ required: true }]}
                      >
                        <Select
                          options={[
                            "preferred_time_window",
                            "task_obstacle",
                            "contact_window",
                            "reminder_channel",
                            "note",
                          ].map((value) => ({ value, label: name(value) }))}
                        />
                      </Form.Item>
                      <Form.Item
                        label="偏好内容"
                        name="value"
                        rules={[{ required: true, whitespace: true }]}
                      >
                        <Input placeholder="例如 08:00" maxLength={300} />
                      </Form.Item>
                      <Form.Item label="后端来源" name="source">
                        <Select
                          options={[
                            {
                              value: "patient_input",
                              label: "模拟患者输入",
                            },
                            {
                              value: "patient_confirmed",
                              label: "模拟患者明确确认",
                            },
                            { value: "import", label: "合成资料导入" },
                          ]}
                        />
                      </Form.Item>
                      <Form.Item
                        name="confirmed"
                        valuePropName="checked"
                        rules={[
                          {
                            validator: (_, v) =>
                              v
                                ? Promise.resolve()
                                : Promise.reject(
                                    new Error(
                                      "请确认这是合成患者的模拟反馈，不是工作人员推测",
                                    ),
                                  ),
                          },
                        ]}
                      >
                        <Checkbox>
                          确认是合成患者的模拟反馈，非工作人员推断
                        </Checkbox>
                      </Form.Item>
                      <Button type="primary" htmlType="submit" loading={busy}>
                        保存并读取实际生效偏好
                      </Button>
                    </Form>
                  </Card>
                  <Card title="当前生效偏好">
                    <DataView resource={resource}>
                      {(d) => (
                        <Table
                          rowKey="id"
                          dataSource={d.preferences.filter(
                            (p) => p.status === "active",
                          )}
                          pagination={false}
                          columns={[
                            { title: "类型", dataIndex: "kind", render: name },
                            { title: "内容", dataIndex: "value" },
                            {
                              title: "操作",
                              render: (_, p) => (
                                <Popconfirm
                                  title="确认清除此偏好？将调用后端并保留历史。"
                                  onConfirm={() =>
                                    act(() =>
                                      api.clearPreference(patientId, p.kind),
                                    )
                                  }
                                >
                                  <Button size="small" disabled={busy}>
                                    清除偏好
                                  </Button>
                                </Popconfirm>
                              ),
                            },
                          ]}
                        />
                      )}
                    </DataView>
                  </Card>
                </div>
                <Card title="偏好覆盖与清除历史">
                  <DataView resource={resource}>
                    {(d) => (
                      <Table
                        rowKey="id"
                        dataSource={d.preferences}
                        scroll={{ x: 850 }}
                        columns={[
                          { title: "类型", dataIndex: "kind", render: name },
                          { title: "内容", dataIndex: "value" },
                          {
                            title: "来源",
                            dataIndex: "source",
                            render: businessName,
                          },
                          {
                            title: "状态",
                            dataIndex: "status",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "生效时间",
                            dataIndex: "valid_from",
                            render: when,
                          },
                          {
                            title: "失效时间",
                            dataIndex: "valid_to",
                            render: when,
                          },
                        ]}
                      />
                    )}
                  </DataView>
                </Card>
              </>
            ),
          },
        ]}
      />
      {error && <ErrorBox error={error} />}
      {result !== undefined && (
        <WriteResult value={result} patientId={patientId} />
      )}
    </>
  );
}
function AnswerForm({
  question,
  busy,
  submit,
}: {
  question: Question;
  busy: boolean;
  submit: (v: string) => Promise<void>;
}) {
  return (
    <Form layout="vertical" onFinish={(v) => submit(v.answer)}>
      <Form.Item
        label="模拟患者答复"
        name="answer"
        rules={[{ required: true, whitespace: true }]}
      >
        <Input.TextArea
          rows={2}
          placeholder="请输入答复，如：记不清"
          maxLength={500}
        />
      </Form.Item>
      <p className="action-note">
        可参考：
        {question.options.length
          ? question.options.join(" / ")
          : "无预设选项，可使用文字答复"}
      </p>
      <Form.Item
        name="simulated"
        valuePropName="checked"
        rules={[
          {
            validator: (_, v) =>
              v
                ? Promise.resolve()
                : Promise.reject(new Error("请确认模拟答复来源")),
          },
        ]}
      >
        <Checkbox>这是合成患者的模拟答复</Checkbox>
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={busy}>
        提交模拟答复并恢复 Agent
      </Button>
    </Form>
  );
}
