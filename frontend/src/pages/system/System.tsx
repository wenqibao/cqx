import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Form,
  InputNumber,
  Table,
  Tabs,
  Tag,
} from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { client } from "../../api/client";
import { api } from "../../api/workbench";
import { useWorkbench } from "../../app/WorkbenchContext";
import { useResource } from "../../hooks/useResource";
import {
  DataView,
  Debug,
  ErrorBox,
  Heading,
  Status,
  WriteResult,
} from "../../components/common";
import { link, name, text, when } from "../../utils/format";
import {
  parseReport,
  redactLog,
  reportResultDisplay,
  type Report,
  type ReportResult,
} from "../../utils/reports";
import catalog from "../../data/scenarios.json";
const commands = [
  ["环境检查", "python -m cli.main health"],
  ["查看患者", "python -m cli.main patient list"],
  ["状态与趋势", "python -m cli.main patient state P001"],
  ["健康记录", "python -m cli.main record list P001"],
  ["事件", "python -m cli.main event list P001"],
  ["任务", "python -m cli.main task list P001"],
  ["随访", "python -m cli.main ask list P001"],
  ["偏好", "python -m cli.main pref list P001 --history"],
  ["知识", "python -m cli.main knowledge search 血糖"],
  ["复评", "python -m cli.main review list P001"],
  ["通知", "python -m cli.main notify list P001"],
  ["调度", "python -m cli.main automation jobs"],
  [
    "场景回放（Mock）",
    "python scripts/run_scenarios.py --report frontend/.runtime/scenarios.json",
  ],
];
const guide = [
  [
    "D01",
    "多患者监管",
    "/",
    "从真实待办发现重点患者，查看档案和事件。入口只导航，不生成测试结果。",
  ],
  [
    "D02",
    "新增记录自动触发",
    "/monitoring",
    "使用已有上升记录的合成患者，录入9.6并检查实际事件、run_id与任务；未触发则如实说明。",
  ],
  [
    "D03",
    "主动随访",
    "/followups",
    "先由Agent核实缺项产生问题，再模拟答复“记不清”，查看恢复run及未知事实保留。",
  ],
  [
    "D04",
    "动态重规划",
    "/agent?tab=negotiate",
    "已有普通管理任务时输入模拟时间约束；或人工改期，分别核对来源与版本。",
  ],
  [
    "D05",
    "复评与人工接管",
    "/tasks?tab=reviews",
    "完成真实任务、查看实际复评分支；待人工复核事项由工作人员填写结案。",
  ],
  [
    "D06",
    "安全与可解释性",
    "/audit",
    "合成患者发起禁止剂量调整的请求后，检查拒绝码及轨迹；安全门拒绝不是模型自主拒绝。",
  ],
];
export default function System() {
  const { boot, patientId, busy, perform } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "status";
  const [report, setReport] = useState<Report>();
  const [filename, setFilename] = useState("");
  const [cliLog, setCliLog] = useState("");
  const [error, setError] = useState<unknown>();
  const [result, setResult] = useState<unknown>();
  const [copied, setCopied] = useState("");
  const resource = useResource("system", async (s) => ({
    health: await client.health(s),
    mode: await api.mode(s),
    version: await api.version(s),
    jobs: await api.jobs(s),
  }));
  async function maintenance(action: () => Promise<unknown>) {
    setError(undefined);
    try {
      setResult(await perform(action));
      resource.reload();
    } catch (e) {
      setError(e);
    }
  }
  async function importFile(f: File | undefined, kind: "report" | "cli") {
    if (!f) return;
    setError(undefined);
    try {
      if (f.size > 5 * 1024 * 1024) throw new Error("文件不得超过5MB");
      const raw = await f.text();
      if (kind === "report") {
        const parsed = parseReport(raw);
        setReport(parsed);
        setFilename(f.name);
      } else {
        if (!raw.trim()) throw new Error("CLI日志为空");
        setCliLog(redactLog(raw));
      }
    } catch (e) {
      if (kind === "report") setReport(undefined);
      setError(e);
    }
  }
  const set = (key: string) => {
    const n = new URLSearchParams(params);
    n.set("tab", key);
    setParams(n);
  };
  return (
    <>
      <Heading
        title="系统验证中心"
        description="开发核验与比赛演示入口。复制命令、导入报告不代表浏览器已执行 CLI、pytest 或场景脚本。"
        extra={<Button onClick={resource.reload}>刷新 API 状态</Button>}
      />
      <Tabs
        activeKey={tab}
        onChange={set}
        items={[
          {
            key: "status",
            label: "API 与持久化",
            children: (
              <DataView resource={resource}>
                {(d) => (
                  <>
                    <div className="two-columns">
                      <Card title="当前真实服务状态">
                        <Descriptions
                          column={1}
                          items={[
                            {
                              key: "service",
                              label: "服务",
                              children:
                                d.version.name + " " + d.version.version,
                            },
                            {
                              key: "health",
                              label: "FastAPI",
                              children: d.health.status,
                            },
                            {
                              key: "db",
                              label: "数据库连接",
                              children: d.health.database.ok
                                ? "连接成功"
                                : "连接失败",
                            },
                            {
                              key: "path",
                              label: "后端报告路径",
                              children: d.health.database.path || "未提供",
                            },
                            {
                              key: "mode",
                              label: "模型模式",
                              children: d.mode.llm_mode,
                            },
                            {
                              key: "model",
                              label: "模型名称",
                              children: d.mode.model || "未返回",
                            },
                            {
                              key: "config",
                              label: "模型配置",
                              children: d.mode.ok
                                ? "配置可用（不等于已调用厂商）"
                                : d.mode.error || "配置不可用",
                            },
                            {
                              key: "time",
                              label: "后端时钟",
                              children: when(d.health.time),
                            },
                          ]}
                        />
                      </Card>
                      <Card title="持久化核验方式">
                        <p>
                          写入后本工作台重新 GET
                          业务对象；刷新页面仍从后端读取。任务版本和实际 ID
                          可继续查询，不以成功弹窗代替保存证据。
                        </p>
                        <p>
                          验证重启持久化需在本机重启后端并重新
                          GET，同一数据库不可重置。实际过程与结果记录在本轮联调报告。
                        </p>
                        <Link
                          to={link(
                            "/patients/" + encodeURIComponent(patientId),
                            patientId,
                          )}
                        >
                          查看当前患者档案
                        </Link>
                        <p className="action-note">
                          此系统未实现正式机构认证或患者授权关系。演示时只绑定127.0.0.1；前端按钮不是权限保护。
                        </p>
                      </Card>
                    </div>
                    <JobList jobs={d.jobs} />
                  </>
                )}
              </DataView>
            ),
          },
          {
            key: "cli",
            label: "CLI 命令与证据",
            children: (
              <>
                <Alert
                  type="info"
                  title="CLI与Web共用后端业务service及SQLite。下列按钮只复制文字，不执行Shell；执行时需在本机设置相同DIABETES_DB_PATH，并核对模式。"
                />
                <Card title="实际支持的命令参考">
                  <Table
                    rowKey="command"
                    pagination={false}
                    dataSource={commands.map(([title, command]) => ({
                      title,
                      command,
                    }))}
                    columns={[
                      { title: "能力", dataIndex: "title" },
                      {
                        title: "本机命令",
                        dataIndex: "command",
                        render: (v) => <code>{v}</code>,
                      },
                      {
                        title: "操作",
                        render: (_, r) => (
                          <Button
                            onClick={async () => {
                              try {
                                await navigator.clipboard.writeText(r.command);
                                setCopied(r.command);
                              } catch (e) {
                                setError(e);
                              }
                            }}
                          >
                            复制命令
                          </Button>
                        ),
                      },
                    ]}
                  />
                  {copied && (
                    <Alert type="info" title={"已复制，尚未执行：" + copied} />
                  )}
                </Card>
                <Card title="导入实际 CLI 执行日志">
                  <label>
                    选择本地日志（不会执行其中命令）
                    <input
                      className="file-input"
                      type="file"
                      accept=".json,.txt,.log"
                      aria-label="导入CLI日志"
                      onChange={(e) => importFile(e.target.files?.[0], "cli")}
                    />
                  </label>
                  {cliLog ? (
                    <>
                      <Alert
                        type="info"
                        title="以下是用户导入的记录，不是本页刚执行的结果；来源真实性需结合本机命令与API核验。"
                      />
                      <pre className="json">{cliLog}</pre>
                    </>
                  ) : (
                    <p className="muted">尚未导入CLI证据，不显示已执行。</p>
                  )}
                </Card>
              </>
            ),
          },
          {
            key: "reports",
            label: "场景与实测报告",
            children: (
              <>
                <Card title="导入真实生成的 JSON 验证报告">
                  <label>
                    选择场景回放或DeepSeek验收报告
                    <input
                      className="file-input"
                      type="file"
                      accept=".json"
                      aria-label="导入验证报告"
                      onChange={(e) =>
                        importFile(e.target.files?.[0], "report")
                      }
                    />
                  </label>
                  <p className="action-note">
                    文件仅在浏览器内解析，不上传服务器。支持脚本results数组、真实模型验收scenarios数组；原样区分Mock/Stub/Real，不执行测试。
                  </p>
                  {report ? (
                    <>
                      <p>文件：{filename}</p>
                      <div className="report-meta">
                        <span>执行日期：{when(report.at)}</span>
                        <span>Git：{report.git || "报告未提供"}</span>
                        <span>明细 {report.rows.length} 项</span>
                        {Object.keys(reportResultDisplay).map((status) => (
                          <span key={status}>
                            {status} {report.rows.filter((r) => r.result === status).length}
                          </span>
                        ))}
                      </div>
                      {report.warning && (
                        <Alert type="warning" title={report.warning} />
                      )}
                      <Table
                        rowKey="id"
                        dataSource={report.rows}
                        scroll={{ x: 1000 }}
                        columns={[
                          { title: "编号", dataIndex: "id" },
                          { title: "场景 / 说明", dataIndex: "title" },
                          {
                            title: "报告模式",
                            dataIndex: "mode",
                            render: (v) => (
                              <Tag color={v === "real" ? "blue" : "default"}>
                                {name(v)}
                              </Tag>
                            ),
                          },
                          {
                            title: "实际结果",
                            dataIndex: "result",
                            render: (v: ReportResult) => (
                              <Tag color={reportResultDisplay[v].color}>
                                {reportResultDisplay[v].label}
                              </Tag>
                            ),
                          },
                          { title: "动作来源", dataIndex: "origin" },
                          {
                            title: "关联运行",
                            dataIndex: "runIds",
                            render: (ids: string[]) =>
                              ids.map((id) => (
                                <div className="mono" key={id}>
                                  {id}
                                </div>
                              )),
                          },
                          {
                            title: "失败原因",
                            dataIndex: "reason",
                            render: text,
                          },
                        ]}
                        expandable={{
                          expandedRowRender: (r) => (
                            <Debug
                              value={r.raw}
                              label="真实报告明细与证据引用"
                            />
                          ),
                        }}
                      />
                      <Debug
                        value={report.environment}
                        label="报告中的测试环境"
                      />
                    </>
                  ) : (
                    <Alert
                      type="info"
                      title="暂无验证报告；不生成通过率或实测成绩。"
                    />
                  )}
                </Card>
                <Card title="既有合成场景目录">
                  <p className="muted">
                    从仓库 evaluation/scenarios
                    读取的编号与描述；仅表示场景存在，不表示本轮运行成功。
                  </p>
                  <Table
                    rowKey="id"
                    dataSource={catalog}
                    columns={[
                      { title: "编号", dataIndex: "id" },
                      { title: "场景描述", dataIndex: "title" },
                      {
                        title: "来源文件",
                        dataIndex: "file",
                        render: (v) => <code>{v}</code>,
                      },
                    ]}
                  />
                </Card>
              </>
            ),
          },
          {
            key: "guide",
            label: "演示导览",
            children: (
              <Card title="建议5–7分钟的真实操作路径">
                <Alert
                  type="info"
                  title="导览只是导航。先确认起始数据、操作模式与费用，失败时保留实际结果，不播放预设成功动画。"
                />
                {guide.map(([id, title, path, description]) => (
                  <div className="guide-step" key={id}>
                    <div className="guide-number">{id}</div>
                    <div>
                      <h3>{title}</h3>
                      <p>{description}</p>
                      <Link
                        to={
                          path +
                          (path.includes("?") ? "&" : "?") +
                          "patient=" +
                          encodeURIComponent(patientId)
                        }
                      >
                        进入对应页面 →
                      </Link>
                    </div>
                  </div>
                ))}
              </Card>
            ),
          },
          {
            key: "maintenance",
            label: "本地演示维护",
            children: (
              <>
                <Alert
                  type="warning"
                  showIcon
                  title="仅限合成数据演示：全局时钟与tick会影响同一后端数据库的所有病例。"
                  description="这里没有服务端权限保护，勾选框只是操作确认，不是授权。后台轮询是否启用须核对启动配置；手动tick不代表后台一直自动执行。未暴露admin/reset或任意命令执行。"
                />
                <Card title="受控演示时钟与作业执行">
                  <Form
                    layout="vertical"
                    onFinish={(v) => maintenance(() => api.clock(v.seconds))}
                  >
                    <Form.Item
                      label="向前推进秒数"
                      name="seconds"
                      initialValue={3600}
                      rules={[{ required: true }]}
                    >
                      <InputNumber min={0} max={1209600} precision={0} />
                    </Form.Item>
                    <Form.Item
                      name="confirm"
                      valuePropName="checked"
                      rules={[
                        {
                          validator: (_, v) =>
                            v
                              ? Promise.resolve()
                              : Promise.reject(
                                  new Error("请核对专用合成数据库"),
                                ),
                        },
                      ]}
                    >
                      <Checkbox>
                        已核对为专用合成数据库，理解时钟对全部患者生效
                      </Checkbox>
                    </Form.Item>
                    <Button htmlType="submit" loading={busy}>
                      确认推进演示时钟
                    </Button>
                  </Form>
                  <hr />
                  <Form onFinish={() => maintenance(() => api.tick())}>
                    <Form.Item
                      name="confirmTick"
                      valuePropName="checked"
                      rules={[
                        {
                          validator: (_, v) =>
                            v
                              ? Promise.resolve()
                              : Promise.reject(
                                  new Error("请确认实际执行作业及可能模型费用"),
                                ),
                        },
                      ]}
                    >
                      <Checkbox>
                        确认执行当前到期作业；real模式可能触发收费模型
                      </Checkbox>
                    </Form.Item>
                    <Button htmlType="submit" loading={busy}>
                      确认执行一次 tick
                    </Button>
                  </Form>
                </Card>
                <DataView resource={resource}>
                  {(d) => <JobList jobs={d.jobs} />}
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
    </>
  );
}
function JobList({ jobs }: { jobs: Awaited<ReturnType<typeof api.jobs>> }) {
  return (
    <Card title="实际调度作业">
      <Table
        rowKey="id"
        dataSource={jobs}
        scroll={{ x: 950 }}
        columns={[
          { title: "作业ID", dataIndex: "id" },
          { title: "患者", dataIndex: "patient_id", render: text },
          { title: "类型", dataIndex: "kind" },
          { title: "计划时间", dataIndex: "run_at", render: when },
          {
            title: "状态",
            dataIndex: "status",
            render: (v) => <Status value={v} />,
          },
          { title: "尝试次数", dataIndex: "attempts" },
          { title: "失败原因", dataIndex: "last_error", render: text },
        ]}
        expandable={{
          expandedRowRender: (j) => (
            <Debug value={j} label="作业结果与关联复评" />
          ),
        }}
      />
    </Card>
  );
}
