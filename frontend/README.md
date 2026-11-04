# 糖衡智管：成员 C 第一阶段真实 API 客户端

React + Vite + TypeScript + Ant Design + ECharts + React Router。默认真实 HTTP，基地址 http://127.0.0.1:8000/api。基线 main `e1674e2101bc7d1111191737626ad818aab75fda`，分支 feature/frontend-c-integration。本阶段仅修改 frontend/。

2026-11-04 更新：本地已合入团队最新 main `c5f787f`；149项后端测试、33场景、11项前端单测、4项浏览器测试通过，C-API-001并发9/9复验通过。当前仍为后端mock规划器，未验证真实厂商模型。完整同步状态、真实模型接入检查和优化优先级见 [最新复验](docs/LATEST_REVIEW.md)。远端main尚未包含完整前端，前端在本功能分支；本地合并尚未push。

## Windows 安装与启动

Node.js 24 / 推荐 npm 12（旧 npm 10 初次解析新版可选peer失败，升级后按锁文件复现）。在仓库根目录：

```powershell
python -m pip install -e ".[dev]"
# 新建专用合成库，勿对其他成员的库执行重置
$env:DIABETES_DB_PATH="$PWD/frontend/.runtime/integration.db"
$env:AGENT_LLM_MODE="mock"
$env:FRONTEND_ORIGIN="http://127.0.0.1:5180"
python scripts/reset_demo.py
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd frontend
npm install
npm run dev -- --port 5180 --strictPort
```

打开 http://127.0.0.1:5180。默认 npm run dev 使用5173，后端默认允许5173；本次验证5180需上面的FRONTEND_ORIGIN。所有服务仅绑定本机。

## 环境变量与模式

复制 .env.example 为 .env.local 后重启Vite：

```env
VITE_API_MODE=http
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

HTTP数据全部来自A的真实服务，失败不会回退Mock。后端llm_mode=mock表示确定性规划器未调用模型，但工具与SQLite实际运行；前端VITE_API_MODE=mock则显示“前端模拟数据”，只提供空数据传输桩、不执行假写入。顶部常驻患者、连接状态、后端模式与合成数据标识，健康状态每15秒检查。

## 使用路径

- `/` 健康总览：选择P001/P002/P003，读取档案、最新值、近7天图表、缺失字段、事件、待回答问题与未完成任务。不计算医学判断。
- `/records` 健康数据：支持RecordCreate全部8种kind。服药确认用1/0；症状payload需text；血压需systolic/diastolic。时间输入由本地转换UTC，留空使用后端演示时钟。保存只调用records，trigger_agent=true；原样显示record/automation及run_id跳转。事件去重时runs可为空，不冒充自动触发。
- `/tasks` 健康任务：查看状态、优先级、截止时间、来源，展开完整字段。标记完成需确认，complete发送changed_by=patient、run_agent=false，后端仍执行复评；重新读取任务并显示实际reviews响应。
- `/runs` Agent轨迹：运行列表或run_id查询；抽屉展示真实阶段、工具输入/返回、拒绝码、证据、关联任务与原始运行结果。不同患者运行归属校验不通过时拒绝展示。

主动回答、协商、偏好写入与动态复评操作属于第二阶段，本次未实现，不宣称完整F01–F26前端验收。

## 检查

```powershell
npm run typecheck
npm test
npm run build
npm run test:e2e
```

E2E使用已安装的Google Chrome，自动启动/复用5180前端，连接8000后端。闭环测试严格要求本次录入产生新事件和run_id，**必须先初始化专用演示库**；重复运行会受后端事件去重影响，不能拿历史运行凑结果。不要对共享库执行reset。

结果见docs/INTEGRATION_REPORT.md、docs/evidence/。A/B回归需NO_PROXY=127.0.0.1,localhost，避免系统代理拦截本地模型stub；真实厂商模型未测试。

## 已知限制

旧基线e1674e2存在真实ASGI并发读取跨线程异常；团队main的4c801dd已修复，当前本地9/9并发读取、并发写回归复验通过。旧问题记录与原始日志保留在docs/BACKEND_ISSUES.md，最新状态见docs/LATEST_REVIEW.md。客户端暂保留串行队列；真实模型接入前需处理前端15秒与模型单轮30秒的超时差异。主包约1.72MB，有构建体积提示，生产拆包尚未优化。

普通Git拉取因私有仓库终端认证失败；已通过已授权GitHub API获取并校验143个blob、完整树，恢复完全相同SHA的原始浅检出。未宣称常规git fetch成功，未push/合并main。原D:\cqx独立Mock成果保留，新检出在D:\cqx-current。
