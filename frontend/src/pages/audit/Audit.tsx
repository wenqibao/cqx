import { useState } from "react";
import { Button, Card, Input, Table, Tag } from "antd";
import { api } from "../../api/workbench";
import { useResource } from "../../hooks/useResource";
import {
  DataView,
  Heading,
  RunLink,
  TechnicalLog,
} from "../../components/common";
import { businessName } from "../../utils/business";
import { text, when } from "../../utils/format";
export default function Audit() {
  const resource = useResource("audit", (s) => api.audit(s));
  const [filter, setFilter] = useState("");
  return (
    <>
      <Heading
        title="安全与审计"
        description="查看请求拦截、人工升级与处理记录。"
        extra={
          <>
            <Button onClick={resource.reload}>刷新审计</Button>
            <TechnicalLog value={resource.data} label="审计日志" />
          </>
        }
      />

      <DataView resource={resource}>
        {(r) => (
          <>
            <Card title="后端审计统计">
              <div className="toolbar">
                <div>
                  <span className="muted">后端报告的禁止动作执行次数：</span>
                  <Tag
                    color={r.forbidden_executed === 0 ? "default" : "warning"}
                  >
                    {r.forbidden_executed}
                  </Tag>
                </div>
                <span className="muted">当前最多返回最近 200 条审计</span>
              </div>
              <p className="action-note">
                计数口径需结合业务记录核对，原始字段见审计日志。
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
                  `${v.patient_id} ${v.code} ${v.action} ${businessName(v.code)} ${businessName(v.action)}`
                    .toLowerCase()
                    .includes(filter.toLowerCase()),
                )}
                scroll={{ x: 1150 }}
                columns={[
                  { title: "时间", dataIndex: "ts", render: when },
                  { title: "患者", dataIndex: "patient_id", render: text },
                  {
                    title: "来源（后端记录）",
                    dataIndex: "actor",
                    render: businessName,
                  },
                  {
                    title: "业务行为",
                    dataIndex: "action",
                    render: businessName,
                  },
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
                        {businessName(v)}
                      </Tag>
                    ),
                  },
                  {
                    title: "拦截 / 升级原因",
                    dataIndex: "code",
                    render: businessName,
                  },
                  {
                    title: "当前人工待办",
                    render: (_, v) =>
                      v.decision === "escalate"
                        ? "请查看待复核事项并跟进处理"
                        : v.decision === "reject"
                          ? "请求已拦截；请核查原因，勿按已执行处理"
                          : "请结合实际业务结果核验",
                  },
                  {
                    title: "关联运行",
                    render: (_, v) => (
                      <RunLink id={v.run_id} patient={v.patient_id || ""} />
                    ),
                  },
                ]}
              />
            </Card>
          </>
        )}
      </DataView>
    </>
  );
}
