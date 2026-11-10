import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
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
export default function System() {
  const { patientId } = useWorkbench();
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get("tab");
  const tab = requestedTab === "cli" || requestedTab === "reports"
    ? requestedTab
    : "status";
  const [report, setReport] = useState<Report>();
  const [filename, setFilename] = useState("");
  const [cliLog, setCliLog] = useState("");
  const [error, setError] = useState<unknown>();
  const [copied, setCopied] = useState("");
  const resource = useResource("system", async (s) => ({
    health: await client.health(s),
    mode: await api.mode(s),
    version: await api.version(s),
    jobs: await api.jobs(s),
  }));
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
                              key: "time",
                              label: "后端时钟",
                              children: when(d.health.time),
                            },
                          ]}
                        />
                        <details>
                          <summary>运行详情</summary>
                          <p>本地演示使用合成病例，供健康管理流程展示。</p>
                          <Debug
                            value={{ mode: d.mode, database: d.health.database }}
                            label="接口字段"
                          />
                        </details>
                      </Card>
                      <Card title="患者档案">
                        <Link
                          to={link(
                            "/patients/" + encodeURIComponent(patientId),
                            patientId,
                          )}
                        >
                          查看当前患者档案
                        </Link>
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
                <Card title="命令参考">
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
                    <Alert type="info" title={"已复制：" + copied} />
                  )}
                </Card>
                <Card title="导入 CLI 日志">
                  <label>
                    选择本地日志
                    <input
                      className="file-input"
                      type="file"
                      accept=".json,.txt,.log"
                      aria-label="导入CLI日志"
                      onChange={(e) => importFile(e.target.files?.[0], "cli")}
                    />
                  </label>
                  {cliLog ? (
                    <pre className="json">{cliLog}</pre>
                  ) : (
                    <p className="muted">尚未导入日志</p>
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
                <Card title="导入验证报告">
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
                      title="暂无验证报告"
                    />
                  )}
                </Card>
                <Card title="场景目录">
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
        ]}
      />
      {error && <ErrorBox error={error} />}
    </>
  );
}
function JobList({ jobs }: { jobs: Awaited<ReturnType<typeof api.jobs>> }) {
  const { boot } = useWorkbench();
  const patientNames = new Map(boot?.patients.map((p) => [p.id, p.name]));
  return (
    <Card title="实际调度作业">
      <Table
        rowKey="id"
        dataSource={jobs}
        scroll={{ x: 950 }}
        columns={[
          { title: "作业ID", dataIndex: "id" },
          {
            title: "患者",
            dataIndex: "patient_id",
            render: (id) => patientNames.get(id) || "—",
          },
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
