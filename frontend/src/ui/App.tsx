import { Suspense, lazy } from "react";
import {
  NavLink,
  Route,
  Routes,
  useLocation,
  Link,
  Navigate,
} from "react-router-dom";
import { Button, Select, Spin, Tag } from "antd";
import {
  DashboardOutlined,
  TeamOutlined,
  HeartOutlined,
  CommentOutlined,
  CheckSquareOutlined,
  DeploymentUnitOutlined,
  SafetyCertificateOutlined,
  ExperimentOutlined,
  BellOutlined,
} from "@ant-design/icons";
import { WorkbenchProvider, useWorkbench } from "../app/WorkbenchContext";
import { client } from "../api/client";
import {
  ErrorBox,
  PatientScope,
  OperationFeedback,
} from "../components/common";
const Dashboard = lazy(() => import("../pages/dashboard/Dashboard"));
const Patients = lazy(() => import("../pages/patients/Patients"));
const PatientDetail = lazy(() =>
  import("../pages/patients/Patients").then((m) => ({
    default: m.PatientDetail,
  })),
);
const Monitoring = lazy(() => import("../pages/monitoring/Monitoring"));
const Followups = lazy(() => import("../pages/followups/Followups"));
const Tasks = lazy(() => import("../pages/tasks/Tasks"));
const Agent = lazy(() => import("../pages/agent/Agent"));
const Knowledge = lazy(() => import("../pages/agent/Knowledge"));
const Audit = lazy(() => import("../pages/audit/Audit"));
const System = lazy(() => import("../pages/system/System"));
const Notifications = lazy(() => import("../pages/followups/Notifications"));
const nav = [
  ["/", "监管总览", DashboardOutlined],
  ["/patients", "患者管理", TeamOutlined],
  ["/monitoring", "健康监测", HeartOutlined],
  ["/followups", "智能随访", CommentOutlined],
  ["/tasks", "任务与复评", CheckSquareOutlined],
  ["/agent", "Agent 决策", DeploymentUnitOutlined],
  ["/audit", "安全与审计", SafetyCertificateOutlined],
  ["/system", "系统验证", ExperimentOutlined],
] as const;
export default function App() {
  return (
    <WorkbenchProvider>
      <Shell />
    </WorkbenchProvider>
  );
}
function Shell() {
  const { boot, error, loading, patientId, busy, setPatient, refresh } =
    useWorkbench();
  const { search } = useLocation();
  const navigationQuery = patientId
    ? "?patient=" + encodeURIComponent(patientId)
    : "";
  const state = boot?.health;
  const online = state?.status === "ok" && state.database.ok;
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-mark">
            <HeartOutlined />
          </span>
          <div>
            糖衡智管<small>医护监管工作台</small>
          </div>
        </Link>
        <div className="nav-label">工作空间</div>
        <nav aria-label="主要导航">
          {nav.map(([path, title, Icon]) => (
            <NavLink end={path === "/"} to={path + navigationQuery} key={path}>
              <Icon aria-hidden="true" />
              <span>{title}</span>
            </NavLink>
          ))}
        </nav>
        <div className="side-note">
          <SafetyCertificateOutlined />
          <span>
            单 Agent 智能辅助
            <br />
            所有行动留痕 · 人工监督
          </span>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div className="header-location">
            智能监测与随访监管<span>医护健康管理工作台</span>
          </div>
          <div className="header-status">
            <Tag color={client.mode === "http" ? "cyan" : "orange"}>
              {client.mode === "http" ? "真实 HTTP API" : "前端模拟数据"}
            </Tag>
            <Tag color={online ? "success" : "error"}>
              {online ? "后端已连接" : "后端连接失败"}
            </Tag>
            <span className="mode">
              llm_mode：{boot?.mode.llm_mode || "未知"}
              <small>{boot?.mode.model || "模型未返回"}</small>
            </span>
            <Select
              aria-label="当前演示患者"
              value={patientId || undefined}
              disabled={busy || !boot}
              placeholder="选择合成患者"
              onChange={setPatient}
              showSearch
              optionFilterProp="label"
              options={boot?.patients.map((p) => ({
                value: p.id,
                label: `${p.name} · ${p.id}`,
              }))}
              className="patient-select"
              getPopupContainer={(trigger) => trigger}
              styles={{
                popup: { root: { inset: "calc(100% + 4px) auto auto 0" } },
              }}
            />
            <Link to={"/notifications" + navigationQuery} aria-label="通知中心">
              <Button icon={<BellOutlined />} />
            </Link>
          </div>
        </header>
        <div className="disclosure">
          <span>合成数据演示 · 不提供诊断、处方或用药调整</span>
          <span>
            {busy
              ? "正在处理，请勿重复提交"
              : boot?.mode.llm_mode === "mock"
                ? "确定性演示模式"
                : boot?.mode.llm_mode === "real"
                  ? "真实模型模式"
                  : "等待后端返回模式"}
          </span>
        </div>
        <main>
          <OperationFeedback />
          {loading ? (
            <div className="loading" role="status">
              <Spin />
              正在同步工作台…
            </div>
          ) : error ? (
            <>
              <h1>监管工作台暂不可用</h1>
              <ErrorBox error={error} retry={refresh} />
            </>
          ) : (
            <Suspense
              fallback={
                <div className="loading">
                  <Spin />
                  正在加载页面…
                </div>
              }
            >
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/patients" element={<Patients />} />
                <Route path="/patients/:id" element={<PatientDetail />} />
                <Route
                  path="/monitoring"
                  element={
                    <PatientScope>
                      <Monitoring />
                    </PatientScope>
                  }
                />
                <Route
                  path="/followups"
                  element={
                    <PatientScope>
                      <Followups />
                    </PatientScope>
                  }
                />
                <Route
                  path="/tasks"
                  element={
                    <PatientScope>
                      <Tasks />
                    </PatientScope>
                  }
                />
                <Route
                  path="/agent"
                  element={
                    <PatientScope>
                      <Agent />
                    </PatientScope>
                  }
                />
                <Route path="/agent/knowledge" element={<Knowledge />} />
                <Route path="/audit" element={<Audit />} />
                <Route path="/system" element={<System />} />
                <Route
                  path="/notifications"
                  element={
                    <PatientScope>
                      <Notifications />
                    </PatientScope>
                  }
                />
                <Route
                  path="/records"
                  element={<Navigate replace to={"/monitoring" + search} />}
                />
                <Route
                  path="/runs"
                  element={<Navigate replace to={"/agent" + search} />}
                />
                <Route
                  path="*"
                  element={
                    <>
                      <h1>页面不存在</h1>
                      <Link to="/">返回监管总览</Link>
                    </>
                  }
                />
              </Routes>
            </Suspense>
          )}
        </main>
        <footer>
          <Link to="/system?tab=guide">使用说明与系统信息</Link>
        </footer>
      </div>
    </div>
  );
}
