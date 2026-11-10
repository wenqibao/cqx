# 下一步执行清单（真实验收后的确定事项）

## 当前决定

DeepSeek 已正式接入并真正执行了业务工具。本轮进入**修复审查和独立复验**，不再等待采购/配置模型，不新增其他模型，不启动大范围功能扩展。当前真实结果为 2 PASS / 3 FAIL / 1 INCONCLUSIVE；本轮预算已用完，禁止继续收费重试。未经 B 复验不发布“全链路已通过”的结论。

## A：审查独立后端 PR

1. 优先审查 DS-03 所有权防护、DS-06 生成文本否定/转介语境和 DS-07 指标定义；以 B24 原句、混合肯定指令、跨患者读写作为必须通过的安全门槛。P0 防护缺口虽已受控回归，B 尚未独立确认。
2. 审查 DS-01/02/05 的检索轨迹、证据 chunk、空输出/虚假成功判定，以及 DS-08 回答上下文、DS-09 偏好枚举、DS-10 更新任务关联。真实失败原始结果不得改写。
3. R01 一次两轮模型请求约 49 秒、R03 三轮请求约一分钟，而 C HttpAdapter 超时 15 秒。A/C 先敲定长运行的查询/完成反馈方式与契约，再实施；本轮未改异步 API 或 F01–F26 合同。
4. 审查通过后再向用户申请下一轮小额、明确上限的真实复验预算；本轮报告和守卫不提供绕过预算的执行方式。

## B：独立复验（下一道发布门）

1. 在独立机器/新隔离 SQLite、审查后的确定提交执行全量 pytest 与 33 场景，检查 B24 和 SQLite 并发。核对 Mock 环境不会花费真实额度。
2. 核验本轮机器报告、response_id、usage、run_id、原生工具参数、tool_result、SQLite/公开 API 的一致性；由本机持有人提供脱敏证据，GitHub clone 不含机器报告和数据库。
3. 新预算确认后优先真实复验 R01–R04 修复效果，R03 要核对“记不清”不落确定服药记录且不无效重复追问。R04 要求改时版本正确，若模型选择保存偏好也必须合法成功。预算计算包含每次自动触发及回答恢复，不按场景数偷减。
4. R05 再查 done/版本/CLOSED 的普通 API 闭环；R06 查精确原句安全拒绝及零危险副作用，明确它可能不调用模型。不要把模型 HTTP 成功或 Stub 通过计成真实业务 PASS。
5. 只有新确认版本上的关键场景和安全检查通过，才建议合并/演示。持续保留 FAIL/INCONCLUSIVE，不修改既有 Expected。

## C：独立前端缺陷与交互交接

本次只读使用 `D:\cqx-current\frontend`，没有覆盖 PR #2。下列为具体交接单；API 后端统一为本机 8010。

### C-DS-01 / P1：同步真实运行超过前端超时窗口

- 页面：`/records` 及任何触发真实 Agent 的操作。
- 触发：真实模型运行两至三轮；R01 两次 HTTP 约 49 秒，R03 三轮约一分钟；源码 HttpAdapter 默认请求超时 15 秒。
- 实际：已证实服务响应时长与前端时间窗不匹配；**没有额外收费复现浏览器超时，不宣称已发生某次重复写入**。本轮 R02 较快且 201/automation 可见。
- 预期：长运行明确显示进行中、查询 run_id/结果，网络超时不能诱导用户重复提交已保存的记录。
- API：`POST /api/patients/{id}/records`、`POST /api/patients/{id}/agent/runs`；参考 `RUN-aab60e171af9`、`RUN-ebfd94cefbb2`。
- 证据：本地 ledger 各次 latency_ms、R01/R03 snapshot；前端 `src/api/httpAdapter.ts`。
- 建议：A/C 协商完成反馈和状态查询；C 增加真实 failed/等待/部分成功说明及防重复提交，不用静态成功提示掩盖后端失败。复验厂商错误和超时 UI。

### C-DS-02 / P2：减少动态效果设置下患者选择不可用

- 页面：全局患者选择器（包括 `/records`）。
- 触发：Chromium 1440×1000、`prefers-reduced-motion: reduce`，展开患者下拉并选择 DS-R02。
- 实际：候选项 DOM 存在，但可见数量为 0、选择超时；未发送 records POST。默认动态效果下选择正常，R02/R05 操作均完成。
- 预期：系统“减少动态效果”偏好下同样能选择患者。
- API：`GET /api/patients` 已正常；无 run_id（业务未触发）。
- 证据：本地 `deepseek_selector.png` 和 `.tmp/inspect-select.mjs`；最初测试器失败留在 `.tmp/R02-browser-*.json`。
- 建议：检查 `src/ui/style.css` 的 reduced-motion 规则与 Ant Design Select 动画/可见性；由 C 修复并独立复现，不能归因后端或消耗模型预算。

### C-DS-03 / P1：接入现有问题回答入口

- 页面：总览待答问题区域；当前第一阶段仅展示，第二阶段交互未接入。
- 触发：选择 DS-R03，原问题 `Q-6f9687bda299` 在模型初轮创建后等待回答。
- 实际：本轮通过业务 API 提交“记不清”并恢复，不能在当前第一阶段前端完成该步骤。属于已知阶段缺口，不冒充新增后端回归。
- 预期：显示真实问题选项，调用回答 API，正确展示 uncertain、等待/失败、恢复 run；不补造服药事实。
- API：`POST /api/questions/{question_id}/answer`；原 run `RUN-ebfd94cefbb2`，恢复 `RUN-9bbcc2d14b65`。
- 证据：`deepseek_R03_response.json`、`deepseek_R03-answer_response.json`、对应 snapshot。
- 建议：在已有总览问题组件和统一 src/api 客户端实现；先与 A/B 确认重复追问修复结果，再录制真实演示。

## 演示门槛与顺序

先由 A 审查安全与状态修复 → B 在确定提交上复验（新的真实预算须单独确认）→ C 完成长运行反馈/问题回答及关键浏览器验收 → 再统一演示脚本和截图。真实调用波动、失败及安全门来源必须保留在演示说明；不要为录屏反复重置和收费重跑。

当前没有授权自动合并 main；本次独立后端 PR 与 C 的 PR #2 分别审查。模型密钥、数据库、原始机器日志不进 Git。成员 clone 后可按 README 配置本地环境运行，但不会自动获得本机的密钥和验收证据。

## A-REAL-AUTONOMY-01（2026-11-08）

- Real 模式上下文增强（事件证据、已有任务/问题/复评）与决策协议已实现；
- 新增执行后核验与 decision_rationale 轨迹；
- 本地回归：416 passed、33/33 Mock；
- 真实 DeepSeek：NOT RUN，待新预算批准后由 B 按 C01–C08 之外的自主决策场景验收。

## A-FINAL-BACKEND-01（2026-11-08）

- 完成判定统一纳入 `schedule_review`；多事件只关闭有数据库关联的事件；
- "已有任务覆盖"必须通过 `_verify_task_coverage` 核验（患者/状态/类型/答复提及）；
- `post_execution_check` 增加 due/患者/事件/复核状态/偏好值/通知引用核验；
- 新增 `scripts/deepseek_autonomy_acceptance.py`（R07-R11，独立库与账本）；
- 本地回归 440 passed / 33-33；真实 DeepSeek 未调用，待 B 按预算执行。
