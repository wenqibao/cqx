import { useState } from "react";
import { Alert, Button, Card, Input, Table, Tag } from "antd";
import { api } from "../../api/workbench";
import { useResource } from "../../hooks/useResource";
import {
  DataView,
  Heading,
  RunLink,
  TechnicalDetails,
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
                  <span className="muted">后端报告的禁止动作执行次数：</span>
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
                description="该指标曾存在统计口径偏差。请结合实际动作和保存结果核验，不能把被拦截次数当成已执行次数。原始字段及版本限制见技术详情。"
              />
              <TechnicalDetails
                value={{
                  forbidden_executed: r.forbidden_executed,
                  rejection_codes: r.rejection_codes,
                  version_note:
                    "main 基线曾将拒绝记录计入此字段；PR #3 提供修复，是否已集成须按运行后端版本核验。",
                }}
              />
              <p>
                系统可识别的拦截原因：
                {r.rejection_codes.map((c) => (
                  <Tag key={c}>{businessName(c)}</Tag>
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
                expandable={{
                  columnTitle: "技术详情",
                  expandedRowRender: (v) => (
                    <TechnicalDetails
                      value={{
                        ...v,
                        parsed_detail:
                          typeof v.detail === "string"
                            ? safeDetail(v.detail)
                            : v.detail,
                      }}
                      ids={{
                        审计编号: v.id,
                        运行编号: v.run_id,
                        拒绝码: v.code,
                        原始操作: v.action,
                      }}
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
