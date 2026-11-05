import { useState } from "react";
import { Alert, Button, Card, Input, Table, Tag } from "antd";
import { api } from "../../api/workbench";
import { useResource } from "../../hooks/useResource";
import { DataView, Debug, Heading, RunLink } from "../../components/common";
import { text, when } from "../../utils/format";
export default function Audit() {
  const resource = useResource("audit", (s) => api.audit(s));
  const [filter, setFilter] = useState("");
  return (
    <>
      <Heading
        title="安全与审计"
        description="监督越权请求、拒绝原因与人工升级；审计来自真实后端，不以界面隐藏按钮充当授权。"
        extra={<Button onClick={resource.reload}>刷新审计</Button>}
      />
      <Alert
        type="info"
        title="Agent 不诊断、不开处方、不改药或胰岛素剂量。高风险管理事项仅升级人工专业复核。"
      />
      <DataView resource={resource}>
        {(r) => (
          <>
            <Card title="后端审计统计">
              <div className="toolbar">
                <div>
                  <span className="muted">后端报告 forbidden_executed：</span>
                  <Tag
                    color={r.forbidden_executed === 0 ? "default" : "warning"}
                  >
                    {r.forbidden_executed}
                  </Tag>
                </div>
                <span className="muted">当前最多返回最近 200 条审计</span>
              </div>
              <Alert
                type="warning"
                title="计数口径须按后端版本核验，不能单凭数字证明安全。"
                description="main 基线曾将拒绝记录计入此字段；修复在独立 PR #3 待审。这里原样展示，并结合实际工具结果及数据库副作用核验，不把被拦截次数伪装成已执行次数。"
              />
              <p>
                可返回拒绝码：
                {r.rejection_codes.map((c) => (
                  <Tag key={c}>{c}</Tag>
                ))}
              </p>
            </Card>
            <Card title="实际审计日志">
              <Input.Search
                className="search"
                aria-label="筛选审计"
                placeholder="筛选患者、拒绝码或操作"
                onChange={(e) => setFilter(e.target.value)}
                value={filter}
              />
              <Table
                rowKey="id"
                dataSource={r.items.filter((v) =>
                  `${v.patient_id} ${v.code} ${v.action}`
                    .toLowerCase()
                    .includes(filter.toLowerCase()),
                )}
                scroll={{ x: 1150 }}
                columns={[
                  { title: "时间", dataIndex: "ts", render: when },
                  { title: "患者", dataIndex: "patient_id", render: text },
                  { title: "来源（后端记录）", dataIndex: "actor" },
                  { title: "操作", dataIndex: "action" },
                  {
                    title: "审计决定",
                    dataIndex: "decision",
                    render: (v) => (
                      <Tag
                        color={
                          v === "reject"
                            ? "error"
                            : v === "escalate"
                              ? "gold"
                              : "default"
                        }
                      >
                        {v}
                      </Tag>
                    ),
                  },
                  { title: "拒绝 / 升级码", dataIndex: "code", render: text },
                  {
                    title: "关联运行",
                    render: (_, v) => (
                      <RunLink id={v.run_id} patient={v.patient_id || ""} />
                    ),
                  },
                ]}
                expandable={{
                  expandedRowRender: (v) => (
                    <Debug
                      value={
                        typeof v.detail === "string"
                          ? safeDetail(v.detail)
                          : v.detail
                      }
                      label="实际审计原因与上下文"
                    />
                  ),
                }}
              />
            </Card>
          </>
        )}
      </DataView>
    </>
  );
}
function safeDetail(value: string) {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}
