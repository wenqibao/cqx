# 糖衡智管 · 医护监管工作台 V3

面向医护健康管理人员的单 Agent 辅助工作台。仅合成病例演示，不提供诊断、处方、改药或医疗处置。采用 React、TypeScript、Vite、React Router、Ant Design、ECharts、Zod、Vitest 和 Playwright。

当前前端版本为 V3（0.3.0）。2026-11-08 按后端冻结版本 `v0.2.1` 完成契约适配和 C-DS-01/03 实现，写超时为 60 秒，包含 404 回归。根据 B 反馈，将过期测试拆成两个明确场景，当前专项为 14 项，支持 Edge。复现步骤见 [v0.2.1 交接](docs/C_TO_B_V021_CONTRACT_REGRESSION.md)，最新结果见 [回复 B 的复验交接](docs/C_TO_B_V021_RETEST_RESPONSE_20261108.md)。C-UX-01/02 的既有交付继续保留。旧版报告为历史快照，结果须与各自提交对应。

## 安装与启动

本机验证 Node 24.22.1、npm 12、Python 3.13.5；首次安装后端依赖在仓库根目录执行：

```powershell
python -m pip install -e ".[dev]"
python frontend/tools/start-test-backend.py
```

该脚本只使用 `frontend/.runtime/workbench-test.db`，首次创建合成病例，已有数据直接保留，不删除、不重置其他数据库；后端为确定性 Mock，绑定 `127.0.0.1:8020`，关闭后台轮询。端口已占用时先检查，不自动终止他人进程。

另开终端：

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev -- --port 5180 --strictPort
```

打开 [监管工作台](http://127.0.0.1:5180)。如果本机服务已在运行，无需重复启动。Windows重装依赖前关闭使用本目录依赖的旧Vite进程，否则原生编译绑定可能被占用。

## 配置与模式

```env
VITE_API_MODE=http
VITE_API_BASE_URL=http://127.0.0.1:8020/api
VITE_API_WRITE_TIMEOUT_MS=60000
```

源码未配置时默认API基址仍是 `http://127.0.0.1:8000/api`。上例使用独立联调端口。连接 A 的其他本机后端时改基址，并由后端设置 `FRONTEND_ORIGIN=http://127.0.0.1:5180`；修改Vite环境后重启前端。

- HTTP + 后端 mock：真实 FastAPI、工具与SQLite，确定性规划器，无厂商费用。
- HTTP + 后端 real：配置状态来自后端；原生模型调用必须在具体run轨迹中核验，安全门处理不能算模型拒绝。
- 前端 mock：仅空传输桩，显式显示“前端模拟数据”，不执行假保存。HTTP失败不退回此模式。

模型密钥只保存在后端本地环境，不能放入任何VITE变量。普通读取15秒，写入默认60秒，可用正数毫秒配置 `VITE_API_WRITE_TIMEOUT_MS`。写入期间显示已等待时间，连接探测继续运行。超时或断连时提示“后端可能仍在运行”，使用“查询已保存结果”核对记录、任务、运行和问题，再人工解除提交保护；不会自动重发原请求。后端明确返回的 failed、未解决拒绝和部分成功按实际结果展示。

## 页面

| 路由 | 功能 |
| --- | --- |
| `/` | 多患者监管、真实待办统计、最近Agent活动 |
| `/patients`、`/patients/:id` | 搜索/新建合成患者、档案、记录趋势、事件、任务、问题、状态版本 |
| `/monitoring` | 八类结构化录入、CSV/JSON导入、自动触发结果；`?tab=events`看事件 |
| `/followups` | 模拟患者答复并恢复；`?tab=preferences`查看/覆盖/清除偏好 |
| `/tasks` | 完成、人工改期及版本；`?tab=reviews`看三分支及人工结案 |
| `/agent` | 请求、运行查询、业务化轨迹；`?tab=negotiate`做Agent协商 |
| `/agent/knowledge` | 知识包与独立检索 |
| `/audit` | 真实拒绝、升级、执行审计和后端计数口径提示 |
| `/system` | API/持久化、CLI证据、报告导入、导览、本地时钟/tick维护 |
| `/notifications` | 实际通知、对象跳转、后端已读保存 |

患者上下文为 `?patient=P001`，运行深链接为 `/agent?patient=P001&run=RUN-...`；任务用`task`、问题用`question`。切换患者清除对象参数，跨患者任务/run拒绝混用。旧`/records`、`/runs`重定向保留。

工作人员完成/改期发送`staff_demo`；模拟患者答复及偏好有醒目标识。回答、偏好及复核接口仍缺完整工作人员身份审计，不能声称实现机构认证和授权。

## 本轮测试与真实模型

```powershell
npm run typecheck
npm test
npm run build
npm run test:e2e
# 使用专用契约服务时，完整准备步骤见 v0.2.1 交接
npm run test:contract
```

E2E要求8020为专用`workbench-test.db`且模式mock；入口守卫不满足条件直接停止，防止误用共享库或收费模型。初版工作台验证为前端30项单测、15项E2E，以及后端149项和33场景兼容性回归。V3原始展示改进验证为38项单测、19项浏览器回归。根据B反馈继续改进后，前端45项单测、22项浏览器回归通过；本次未重新运行后端测试，最新证据见C→B复验交接。见 [测试报告](docs/TEST_REPORT_V2.md)。

另有本轮实际浏览器DeepSeek冒烟：**2次业务触发、6次厂商HTTP、21,924 tokens**。知识回答PASS；自动触发后的模型只读未行动FAIL。使用的是独立PR #3后端（仍待A审查），没有改后端源码；未将Mock成绩算入Real。`5192`真实模型预览已用满守卫预算，仅用于只读核验，不能继续收费重跑。

`tools/real-smoke-server.py`、`tools/real-browser-smoke.mjs`为手动受限验收工具，不由npm测试自动运行。再次真实调用必须先明确新预算、新隔离环境及已审查后端，不能删除账本绕过限制。

## 证据与交接

- [产品定位](docs/PRODUCT_POSITIONING.md)、[UI规范](docs/UI_DESIGN_SPEC.md)
- [接口映射](docs/API_PAGE_MAP_V2.md)、[实际联调](docs/INTEGRATION_REPORT_V2.md)
- [后端依赖](docs/BACKEND_DEPENDENCIES.md)、[演示流程](docs/DEMO_WORKFLOW.md)
- [文件地图](docs/FILE_MAP_V2.md)、本轮脱敏证据 `docs/evidence/workbench/`

原始完整真实模型响应、账本与SQLite在忽略的`.runtime/`。clone可复现源码与公开脱敏证据，不包含本机密钥、数据库或node_modules。当前主bundle已拆为路由块，仍有大块体积提示；不是生产部署、临床或机构权限验收。

## C-UX-01：根据B复验继续改进

Agent 的实际回复与待回答问题直接展示在操作结果和运行详情顶部；有未答问题时提供“去回答”，进入对应患者的问题并聚焦答复框。已保存的患者消息、Agent 提问与回复使用轻量消息气泡呈现。

日常页面优先显示业务内容，逐条技术折叠已移除。完整编号、调用参数、结果、拒绝码和 JSON 集中在页面/运行的日志入口，可复制或下载。失败、拦截、不确定回答、模型费用和必要操作确认继续保留；重复解释合并到全局演示说明、日志或系统信息。

本次没有新增 DeepSeek 调用，历史失败仍通过只读回放检查。原 [V3验收报告](docs/C_UX_01_ACCEPTANCE.md) 是 ecdff65 的历史交付；B后续指出的可用性问题与本次修复、证据和复验步骤见 [C→B UX复验交接](docs/C_TO_B_UX_FOLLOWUP.md)。C的检查通过后仍需B独立确认能否关闭C-UX-01。
