import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Radio,
  Select,
  Table,
  Tabs,
  Tag,
} from "antd";
import { useSearchParams } from "react-router-dom";
import { client } from "../../api/client";
import { api } from "../../api/workbench";
import { recordKinds, type RecordCreate } from "../../api/types";
import { useWorkbench } from "../../app/WorkbenchContext";
import { useResource } from "../../hooks/useResource";
import {
  CostNotice,
  DataView,
  TechnicalLog,
  ErrorBox,
  Heading,
  RunLink,
  Status,
  WriteResult,
} from "../../components/common";
import { businessName, businessText } from "../../utils/business";
import {
  importRows,
  name,
  recordContent,
  text,
  when,
} from "../../utils/format";
export default function Monitoring() {
  const { patientId, patient, busy, perform } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "record";
  const [form] = Form.useForm();
  const kind = Form.useWatch("kind", form) || "fasting_glucose";
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState<unknown>();
  const [file, setFile] = useState<{
    name: string;
    content: string;
    format: string;
  }>();
  const [trigger, setTrigger] = useState(true);
  const resource = useResource("monitoring:" + patientId, async (s) => ({
    records: await api.records(patientId, 14, s),
    events: await api.events(patientId, s),
  }));
  async function act(action: () => Promise<unknown>) {
    setError(undefined);
    setResult(undefined);
    try {
      const r = await perform(action);
      setResult(r);
      resource.reload();
    } catch (e) {
      setError(e);
    }
  }
  const numeric = !["symptom", "meal", "bp", "medication_taken"].includes(kind);
  async function save(v: Record<string, unknown>) {
    const k = v.kind as RecordCreate["kind"];
    const payload =
      k === "bp"
        ? { systolic: v.systolic, diastolic: v.diastolic }
        : ["symptom", "meal"].includes(k)
          ? { text: v.text }
          : {};
    const data: RecordCreate = {
      kind: k,
      payload,
      trigger_agent: trigger,
      note: v.note ? String(v.note) : undefined,
    };
    if (!["symptom", "meal", "bp"].includes(k)) data.value = Number(v.value);
    if (v.time) data.recorded_at = new Date(String(v.time)).toISOString();
    await act(() => client.addRecord(patientId, data));
  }
  return (
    <>
      <Heading
        title="健康监测"
        description={`${patient?.name} · ${patientId}；新增记录由后端检测事件并按实际规则触发 Agent。`}
        extra={
          <>
            <Button onClick={resource.reload}>重新读取状态</Button>
            <TechnicalLog value={resource.data} label="监测日志" />
          </>
        }
      />
      <CostNotice />
      <Tabs
        activeKey={tab}
        onChange={(key) => {
          const n = new URLSearchParams(params);
          n.set("tab", key);
          setParams(n);
        }}
        items={[
          {
            key: "record",
            label: "健康数据录入",
            children: (
              <Card title="新增合成健康记录">
                <Form
                  form={form}
                  layout="vertical"
                  initialValues={{ kind: "fasting_glucose" }}
                  onValuesChange={(v) => {
                    if (v.kind)
                      form.resetFields([
                        "value",
                        "text",
                        "systolic",
                        "diastolic",
                      ]);
                  }}
                  onFinish={save}
                  className="operation-panel"
                >
                  <Form.Item
                    label="记录类型"
                    name="kind"
                    rules={[{ required: true }]}
                  >
                    <Select
                      options={recordKinds.map((value) => ({
                        value,
                        label: name(value),
                      }))}
                    />
                  </Form.Item>
                  {numeric && (
                    <Form.Item
                      name="value"
                      label="记录数值"
                      rules={[{ required: true, message: "请输入记录数值" }]}
                    >
                      <InputNumber
                        aria-label="记录数值"
                        precision={kind === "steps" ? 0 : undefined}
                        min={0}
                      />
                    </Form.Item>
                  )}
                  {kind === "medication_taken" && (
                    <Form.Item
                      name="value"
                      label="服药确认"
                      rules={[
                        {
                          required: true,
                          message:
                            "请选择实际反馈；不确定时使用随访答复，不补造事实",
                        },
                      ]}
                    >
                      <Radio.Group
                        options={[
                          { value: 1, label: "模拟确认已服药" },
                          { value: 0, label: "模拟确认未服药" },
                        ]}
                      />
                    </Form.Item>
                  )}
                  {["symptom", "meal"].includes(kind) && (
                    <Form.Item
                      name="text"
                      label={kind === "symptom" ? "症状描述" : "饮食描述"}
                      rules={[{ required: true, whitespace: true }]}
                    >
                      <Input.TextArea rows={3} maxLength={1000} />
                    </Form.Item>
                  )}
                  {kind === "bp" && (
                    <div className="two-columns">
                      <Form.Item
                        label="收缩压（mmHg）"
                        name="systolic"
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={1} />
                      </Form.Item>
                      <Form.Item
                        label="舒张压（mmHg）"
                        name="diastolic"
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={1} />
                      </Form.Item>
                    </div>
                  )}
                  <Form.Item
                    label="记录时间（本地时间，留空使用后端演示时钟）"
                    name="time"
                  >
                    <Input type="datetime-local" />
                  </Form.Item>
                  <Form.Item label="记录备注" name="note">
                    <Input maxLength={300} />
                  </Form.Item>
                  <p className="action-note">
                    单位由后端按记录类型保存；血压、症状和饮食字段自动组装为
                    payload，无需编写 JSON。
                  </p>
                  <Checkbox
                    checked={trigger}
                    disabled={busy}
                    onChange={(e) => setTrigger(e.target.checked)}
                  >
                    保存后由后端自动检测并按需触发 Agent
                  </Checkbox>
                  <div className="form-actions" style={{ marginTop: 18 }}>
                    <Button type="primary" htmlType="submit" loading={busy}>
                      保存并查看自动触发结果
                    </Button>
                    <span className="muted">不会额外调用“运行 Agent”接口</span>
                  </div>
                </Form>
              </Card>
            ),
          },
          {
            key: "import",
            label: "CSV / JSON 导入",
            children: (
              <Card title="导入合成健康记录">
                <Alert
                  type="info"
                  title="CSV使用kind,value,recorded_at,text,systolic,diastolic等列；JSON为记录对象数组。坏行和重复行以实际后端结果显示。"
                />
                <label>
                  选择 CSV 或 JSON 文件
                  <input
                    className="file-input"
                    type="file"
                    accept=".csv,.json"
                    aria-label="选择健康记录文件"
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      setError(undefined);
                      if (!f) return;
                      if (f.size > 1024 * 1024) {
                        setError(new Error("文件需小于1MB"));
                        return;
                      }
                      setFile({
                        name: f.name,
                        content: await f.text(),
                        format: f.name.toLowerCase().endsWith(".json")
                          ? "json"
                          : "csv",
                      });
                    }}
                  />
                </label>
                {file && (
                  <>
                    <p>
                      待导入文件：{file.name}
                      （内容仅在浏览器内读取，提交时发送到当前患者接口）
                    </p>
                    <Input.TextArea
                      aria-label="导入内容预览"
                      rows={6}
                      readOnly
                      value={file.content}
                    />
                    <Checkbox
                      checked={trigger}
                      onChange={(e) => setTrigger(e.target.checked)}
                    >
                      导入后自动检测并按需触发 Agent
                    </Checkbox>
                    <p>
                      <Button
                        type="primary"
                        loading={busy}
                        onClick={() =>
                          act(() =>
                            api.importRecords(patientId, {
                              ...(file.format === "csv"
                                ? { csv_text: file.content }
                                : { json_rows: importRows(file.content) }),
                              trigger_agent: trigger,
                            }),
                          )
                        }
                      >
                        确认导入当前患者
                      </Button>
                    </p>
                  </>
                )}
              </Card>
            ),
          },
          {
            key: "events",
            label: "事件中心",
            children: (
              <>
                <p className="action-note">事件级别来自健康管理规则。</p>
                <Card
                  title="事件与多事件协调"
                  extra={
                    <Popconfirm
                      title="扫描当前记录并更新管理事件？"
                      onConfirm={() => act(() => api.scan(patientId))}
                    >
                      <Button disabled={busy}>演示：手动扫描事件</Button>
                    </Popconfirm>
                  }
                >
                  <DataView resource={resource}>
                    {(d) => (
                      <Table
                        rowKey="id"
                        dataSource={d.events}
                        scroll={{ x: 1000 }}
                        columns={[
                          {
                            title: "事件名称",
                            dataIndex: "code",
                            render: businessName,
                          },
                          {
                            title: "规则级别",
                            dataIndex: "severity",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "当前状态",
                            dataIndex: "status",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "触发原因",
                            dataIndex: "message",
                            render: (v) => businessText(v),
                          },
                          {
                            title: "检测时间",
                            dataIndex: "detected_at",
                            render: when,
                          },
                          {
                            title: "关联运行",
                            dataIndex: "handled_by_run",
                            render: (v) => (
                              <RunLink id={v} patient={patientId} />
                            ),
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
      <Card title="近期健康记录（后端近14天、最多200条）">
        <DataView resource={resource}>
          {(d) => (
            <Table
              rowKey="id"
              size="small"
              dataSource={d.records}
              scroll={{ x: 800 }}
              columns={[
                { title: "类型", dataIndex: "kind", render: name },
                {
                  title: "数值 / 内容",
                  render: (_, r) => recordContent(r),
                },
                { title: "记录时间", dataIndex: "recorded_at", render: when },
                { title: "备注", dataIndex: "note", render: text },
              ]}
            />
          )}
        </DataView>
      </Card>
    </>
  );
}
