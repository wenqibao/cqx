# frontend/ —— 成员 C 独立开发的 Web 客户端

后端（A）已完成并稳定，**接口以 [`docs/api_contract.yaml`](../docs/api_contract.yaml) 为准**。
本目录当前只有说明文件，页面代码由 C 使用 React + Vite + TypeScript 实现。

## 1. 启动后端（A 提供）

```powershell
python scripts/reset_demo.py
python -m cli.main serve --port 8000
```

- 基地址：`http://127.0.0.1:8000/api`
- 健康检查：`GET /api/health`（返回 `llm_mode`，前端必须显示当前是 mock 还是 real）
- 交互式文档：`http://127.0.0.1:8000/docs`
- 已配置 CORS：`http://127.0.0.1:5173`、`http://localhost:5173`（可在 `.env` 用 `FRONTEND_ORIGIN` 覆盖）

## 2. 开发顺序（先 Mock 后真实）

1. 按契约实现 `src/api/client.ts`，只允许这一层发起 HTTP 调用。
2. 先接 `MockAdapter`（数据可写死，但**必须显式标注"模拟演示"**）。
3. 后端联调时切换 `HttpAdapter`，逐功能验证；真实模式下**不得渲染假数据**。
4. 页面里不得计算医学判断、不得虚构 Agent 决策或任务。

## 3. 需要覆盖的交互（对应 F15/F16）

| 区域 | 必需功能 | 依赖接口 |
| --- | --- | --- |
| 患者与数据 | 选择合成患者、查看状态/趋势、录入或导入记录 | `GET/POST /patients`、`GET /patients/{id}/state`、`POST /patients/{id}/records` |
| Agent 主动执行 | 展示自动触发、运行状态、创建的任务、错误与日志（不能靠按钮假造自动执行） | `POST /patients/{id}/records` 的 `automation`、`GET /runs/{run_id}` |
| 主动提问 F21 | 展示问题、提交回答、显示 `waiting_user` 与恢复状态 | `GET /patients/{id}/questions`、`POST /questions/{id}/answer` |
| 多事件与决策 F22/F24/F26 | 事件汇总、任务优先级、选择依据、资料引用、不确定性提示 | `GET /patients/{id}/events`、`GET /runs/{run_id}` 的 `evidence`/`rejections` |
| 任务与重规划 F23/F25 | 查看任务、确认完成、申请改时间、确认新计划、查看偏好 | `GET /patients/{id}/tasks`、`POST /tasks/{id}/complete`、`POST /tasks/{id}/reschedule`、`GET/POST /patients/{id}/preferences` |
| 复评与轨迹 F12/F14 | 展示 `CLOSED`/`MISSING_DATA`/`HUMAN_REVIEW`、`run_id`、工具与数据库结果 | `GET /patients/{id}/reviews`、`GET /runs/{run_id}` |

## 4. 重要约定

1. **演示时钟**：页面上的"推进时间"调用 `POST /automation/tick`（带 `advance_seconds`），
   并在界面上明确显示这是演示时钟，不是真实时间流逝。
2. **模式标识**：`/api/system/mode` 与 `/api/health` 返回的 `llm_mode` 必须常驻显示；
   mock 时标注"确定性策略（未调用模型）"。
3. **占位数据**：Mock 模式必须在页面顶部显示"模拟演示数据"，禁止与真实接口混用。
4. **不要做**：注册登录、医生工作台、HIS 对接、移动端 App、诊断/处方/改药入口。

## 5. 验收

- `npm run build` 成功；
- 真实 API 模式下可完成：录入 → 自动触发 → 回答提问 → 改任务时间 → 查看复评与轨迹；
- 断网/后端未启动时给出明确错误提示，而不是静默展示假数据。
