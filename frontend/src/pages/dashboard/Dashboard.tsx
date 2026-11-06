import { Alert, Button, Card, Empty, List, Table } from "antd";
import { Link } from "react-router-dom";
import { useWorkbench } from "../../app/WorkbenchContext";
import { client } from "../../api/client";
import { api } from "../../api/workbench";
import { useResource } from "../../hooks/useResource";
import { DataView, Heading, RunLink, Status } from "../../components/common";
import { link, name, when } from "../../utils/format";
export default function Dashboard() {
  const { boot } = useWorkbench();
  const patients = boot?.patients || [];
  const resource = useResource(
    "dashboard:" + patients.map((p) => p.id).join(","),
    async (s) => {
      const rows = [];
      for (const p of patients) {
        try {
          const state = await client.state(p.id, s);
          const reviews = await api.reviews(p.id, s);
          const runs = await client.runs(p.id, s);
          const notices = await api.notifications(p.id, s);
          rows.push({ patient: p, state, reviews, runs, notices, error: null });
        } catch (e) {
          if (s.aborted) throw e;
          rows.push({
            patient: p,
            state: null,
            reviews: [],
            runs: [],
            notices: [],
            error: e instanceof Error ? e.message : String(e),
          });
        }
      }
      return rows;
    },
  );
  return (
    <>
      <Heading
        title="监管总览"
        description="患者记录、管理事件与 Agent 行动，在同一处监督。"
        extra={
          <>
            <Link to="/system?tab=guide">
              <Button>演示导览</Button>
            </Link>
            <Button onClick={resource.reload}>刷新总览</Button>
          </>
        }
      />
      <div className="intro-strip">
        <div>
          <span className="section-label">单 Agent · 医护监管</span>
          <h2>让每一次辅助行动，都有据可查。</h2>
          <p>
            糖衡智管是面向医护健康管理人员的单 Agent
            辅助工作台。汇总健康记录、随访与任务进度，协助医护安排下一步。
          </p>
        </div>
        <div className="intro-aside">
          记录 → 事件 → Agent
          <br />
          工具执行 → 随访 → 复评
        </div>
      </div>
      <DataView resource={resource}>
        {(rows) => {
          const loaded = rows.filter((r) => r.state);
          const runs = loaded
            .flatMap((r) =>
              r.runs.map((run) => ({ ...run, patientName: r.patient.name })),
            )
            .sort((a, b) => b.started_at.localeCompare(a.started_at));
          const notices = loaded.flatMap((r) =>
            r.notices.filter((n) => n.status === "unread"),
          );
          const stats = [
            ["合成患者", patients.length],
            [
              "待处理事件",
              loaded.reduce(
                (n, r) => n + (r.state?.open_events.length || 0),
                0,
              ),
            ],
            [
              "待回答问题",
              loaded.reduce(
                (n, r) => n + (r.state?.pending_questions.length || 0),
                0,
              ),
            ],
            [
              "未完成任务",
              loaded.reduce((n, r) => n + (r.state?.open_tasks.length || 0), 0),
            ],
            [
              "待人工复核",
              loaded.reduce(
                (n, r) =>
                  n +
                  r.reviews.filter((v) => v.status === "pending_human").length,
                0,
              ),
            ],
            ["最近运行", runs.length],
            ["运行失败", runs.filter((r) => r.status === "failed").length],
          ];
          return (
            <>
              {rows.some((r) => r.error) && (
                <Alert
                  type="warning"
                  title={`仅成功加载 ${loaded.length}/${patients.length} 名患者；统计为已加载数据，不能代表全部患者。`}
                  description={rows
                    .filter((r) => r.error)
                    .map((r) => r.patient.id + ": " + r.error)
                    .join("；")}
                />
              )}
              <div className="stats-grid">
                {stats.map(([title, value]) => (
                  <div className="stat" key={String(title)}>
                    <span>{title}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <Card
                title="重点患者"
                extra={<Link to="/patients">全部患者</Link>}
              >
                <Table
                  rowKey={(r) => r.patient.id}
                  dataSource={[...rows].sort(
                    (a, b) =>
                      (b.state?.open_events.length || 0) +
                      (b.state?.pending_questions.length || 0) +
                      (b.state?.open_tasks.length || 0) -
                      (a.state?.open_events.length || 0) -
                      (a.state?.pending_questions.length || 0) -
                      (a.state?.open_tasks.length || 0),
                  )}
                  scroll={{ x: 1050 }}
                  columns={[
                    {
                      title: "合成患者",
                      render: (_, r) => (
                        <Link
                          to={link(
                            "/patients/" + encodeURIComponent(r.patient.id),
                            r.patient.id,
                          )}
                        >
                          <strong>{r.patient.name}</strong>
                          <small className="block muted">{r.patient.id}</small>
                        </Link>
                      ),
                    },
                    {
                      title: "最新记录时间",
                      render: (_, r) =>
                        r.state
                          ? when(
                              Object.values(r.state.latest)
                                .map((v) => v.recorded_at)
                                .sort()
                                .at(-1),
                            )
                          : "读取失败",
                    },
                    {
                      title: "当前事件",
                      render: (_, r) =>
                        r.state?.open_events
                          .map((e) => name(String(e.code)))
                          .join("、") || (r.error ? "未知" : "无待处理事件"),
                    },
                    {
                      title: "管理任务",
                      render: (_, r) => r.state?.open_tasks.length ?? "未知",
                    },
                    {
                      title: "待随访",
                      render: (_, r) =>
                        r.state?.pending_questions.length ?? "未知",
                    },
                    {
                      title: "人工复核",
                      render: (_, r) =>
                        r.error
                          ? "未知"
                          : r.reviews.filter(
                              (v) => v.status === "pending_human",
                            ).length,
                    },
                    {
                      title: "操作",
                      render: (_, r) => (
                        <Link
                          to={link(
                            "/patients/" + encodeURIComponent(r.patient.id),
                            r.patient.id,
                          )}
                        >
                          查看档案
                        </Link>
                      ),
                    },
                  ]}
                />
              </Card>
              <div className="two-columns">
                <Card
                  title="Agent 工作动态"
                  extra={<span className="muted">每位患者最多最近 50 次</span>}
                >
                  <List
                    dataSource={runs.slice(0, 6)}
                    locale={{ emptyText: "暂无运行记录" }}
                    renderItem={(r) => (
                      <List.Item>
                        <div>
                          <RunLink id={r.id} patient={r.patient_id} />
                          <small className="block muted">
                            {r.patientName} · {name(r.trigger_type)} ·{" "}
                            {name(r.llm_mode)} · {when(r.started_at)}
                          </small>
                        </div>
                        <Status value={r.status} />
                      </List.Item>
                    )}
                  />
                </Card>
                <Card
                  title="待处理工作"
                  extra={
                    <Link to="/notifications">
                      通知中心 · {notices.length} 未读
                    </Link>
                  }
                >
                  <div className="work-links">
                    <Link to="/followups">
                      <strong>{stats[2][1]}</strong> 待回答问题
                      <span>模拟患者反馈入口 →</span>
                    </Link>
                    <Link to="/tasks">
                      <strong>{stats[3][1]}</strong> 未完成任务
                      <span>计划与版本记录 →</span>
                    </Link>
                    <Link to="/tasks?tab=reviews">
                      <strong>{stats[4][1]}</strong> 人工复核事项
                      <span>工作人员确认结案 →</span>
                    </Link>
                  </div>
                  {!patients.length && (
                    <Empty description="暂无患者，请先新建合成患者" />
                  )}
                </Card>
              </div>
            </>
          );
        }}
      </DataView>
    </>
  );
}
