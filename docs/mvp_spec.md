# mvp_spec.md —— F01–F26 需求合同

> 状态：A 已实现（2026-11-02）。每项都对应真实代码与可执行验证方式，见 `docs/PROJECT_FILE_MAP.md`。
> 单 Agent 架构；演示作品，非临床软件；不诊断、不开处方、不更改用药或胰岛素剂量。

## 交付形态

| 交付项 | 实现 |
| --- | --- |
| Agent 运行核心 | `backend/app/agent/orchestrator.py`：状态→事件→计划→校验→工具→核对→轨迹 |
| CLI | `cli/main.py`，`python -m cli.main --help` |
| HTTP API | `backend/app/main.py`，`GET /api/health` 等 |
| 极简 Web 客户端 | 由成员 C 用 `docs/api_contract.yaml` 独立实现（本仓库只留 `frontend/README.md`） |
| 验证与比赛材料 | `evaluation/`、`scripts/run_scenarios.py`、`docs/demo_script.md` |

## 硬性边界（任何功能都不得突破）

1. 不诊断、不开处方、不改药/停药/调胰岛素剂量、不终止治疗。
2. 高风险信号只升级人工复核，并提示就医。
3. 结论必须有可定位来源；无证据时明确说"没有足够资料"。
4. 缺信息时先问，不推断患者未提供的事实。
5. 所有患者为合成虚构数据。

---

## F01 演示患者管理 ｜ 已实现

- 需求：使用 `P001/P002/P003` 虚构患者运行隔离场景。
- 实现：`services/patients.py`；`data/demo_patients/*.json`；表 `patients`。
- 验证：`python -m cli.main patient list`；`tests/api/test_api.py::test_patient_crud_and_state`。
- 验收口径：重启后数据不丢、不串患者（`test_patient_isolation`）。

## F02 基础健康档案 ｜ 已实现

- 需求：保存年龄、病程、已确认目标与必要约束。
- 实现：`patients` 表字段 + `profile_completeness()`（缺失字段进入 F21 提问队列）。
- 验证：`GET /api/patients/P001` 的 `profile`。

## F03 健康数据录入与导入 ｜ 已实现

- 需求：空腹血糖、步数、服药确认等录入；支持 CSV/JSON 回放。
- 实现：`services/records.py`（类型/范围校验、单位补全、幂等 `dedupe_key`、逐行容错导入）。
- 验证：`tests/unit/test_records.py`（9 例，含坏行、重复行、跨患者隔离）。

## F04 状态记忆与趋势 ｜ 已实现

- 需求：汇总 7 天数据、未完成任务、已知偏好、缺失字段，并持久化。
- 实现：`services/state.py`（3d/7d/14d 聚合、趋势判定、缺失字段、快照版本）。
- 验证：`tests/unit/test_state.py`（4 例）。

## F05 健康事件检测 ｜ 已实现

- 需求：预设规则识别血糖变化、活动下降、依从性变化。
- 实现：`events/detector.py` + `config/event_rules.yaml`（阈值/趋势/波动/依从性四类评估器）。
- 验证：`tests/unit/test_events.py`（6 例，含同一小时重复扫描不重复建事件）。

## F06 新增数据主动触发 ｜ 已实现

- 需求：保存记录后自动检查事件，必要时启动 Agent（无需点击）。
- 实现：`automation/triggers.py::after_records`（检测→建通知→入队→立即运行→标记作业完成）。
- 验证：`test_record_save_triggers_event_and_agent`；场景 `S01`。

## F07 复评到期自动调度 ｜ 已实现

- 需求：无人点击，到期后由后台检查并执行复评；幂等、可重试。
- 实现：`automation/scheduler.py`（`automation_jobs` 唯一键、`_claim` 防重复领取、失败重试、
  每日到期扫描）；演示时钟 `db.connection.advance_clock`。
- 验证：`test_scheduler_tick_runs_due_review_without_click`、`test_scheduler_is_idempotent`。

## F08 Agent 自主决策 ｜ 已实现

- 需求：读取状态，决定询问/查知识/建任务/复核。
- 实现：`agent/orchestrator.py`（意图识别 → 计划 → 校验 → 执行 → 收尾）；mock 用确定性策略，
  real 用模型 tool calling。
- 验证：`test_agent_creates_task_and_trace_is_reproducible`。

## F09 个性化任务规划 ｜ 已实现

- 需求：同事件不同病史可有不同优先任务（先核实服药或先核实活动）。
- 实现：`planning/planner.py`（模板 + 缺失字段 + 偏好 + 严重度权重）。
- 验证：`test_multi_event_merge_and_priority`、场景 `S03`。

## F10 真实工具调用 ｜ 已实现

- 需求：执行创建任务、查询历史、安排复评等后端函数，且真实写库。
- 实现：`agent/tools.py` 14 个工具（`create_task`/`update_task`/`complete_task`/`ask_user`/
  `search_knowledge`/`schedule_review`/`request_human_review`/`save_preference`/`query_history`/
  `create_notification`/`get_preferences`/`list_tasks`/`parse_constraint`/`respond`）。
- 验证：每次运行的 `agent_steps` 里都有 `tool_call` + `tool_result`；`test_agent_creates_task...`。

## F11 健康任务管理 ｜ 已实现

- 需求：保存任务、期限、完成/未完成状态与关联事件。
- 实现：`tasks/service.py` + 表 `tasks`/`task_versions`（去重、合并、版本快照）。
- 验证：`tests/integration/test_agent_flow.py`、`GET /api/tasks/{id}`。

## F12 动态复评三分支 ｜ 已实现

- 需求：完成关闭、缺数据补录、符合条件转人工复核。
- 实现：`reviews/service.py::decide_branch`（先安全、再数据、最后关闭）；`CLOSED`/`MISSING_DATA`/
  `HUMAN_REVIEW` 全部真实入库。
- 验证：`test_task_completion_leads_to_closed_review`、`test_review_missing_data_branch`、
  `test_human_review_branch_for_high_risk`、场景 `S05`/`S06`。

## F13 安全门与人工升级 ｜ 已实现

- 需求：不执行改药、诊断等禁止动作；创建待复核事项。
- 实现：`safety/gate.py` 两层识别——① 禁止意图关键词（固定说法）；② `config/safety_rules.yaml`
  的 `intent_patterns`（"药物对象 + 剂量/用法变化"的表达变体，含中文数字与"多打/加量/改成…打"等），
  并对"本系统不提供…"这类免责声明做引用豁免；意图识别（`planning/planner.detect_intent`）
  复用同一判定，协商路径另有纵深防御。工具白名单、红旗信号与审计同层实现。
  `request_human_review` 工具幂等（同一患者同一理由只有一条待处理）。
- 验证：`tests/unit/test_safety.py`、`tests/unit/test_safety_variants.py`、
  `tests/integration/test_safety_b24.py`、`test_forbidden_request_blocked_and_audited`、场景 `S09`；
  BUG-B24-001（`请把胰岛素改成早上多打两单位`）已纳入回归。

## F14 决策解释及运行追踪 ｜ 已实现

- 需求：每次行动可查 `run_id`、证据、工具调用与结果。
- 实现：`audit/trace.py`；`GET /api/runs/{run_id}`；`python -m cli.main trace RUN-...`。
- 验证：`trace` 覆盖 `perceive/plan/validate/act/observe` 五个阶段。

## F15 极简 Web 客户端 ｜ 后端就绪 / 页面待 C

- A 的交付：`docs/api_contract.yaml` 全部端点 + CORS（`FRONTEND_ORIGIN`）+ Mock 约定（`frontend/README.md`）。
- 验收：C 用真实 API 完成选择患者、录入、回答提问、改期、查看复评与轨迹。

## F16 站内待办提醒 ｜ 已实现（后端）

- 需求：新增任务、答复待办、复评到期后提醒。
- 实现：`services/notifications.py`；任务创建、改期、提问、复评、逾期、高风险事件都会产生提醒。
- 验证：`GET /api/patients/P001/notifications`。

## F17 CLI 命令行 ｜ 已实现

- 需求：导入数据、运行场景、答复问题、查看轨迹。
- 实现：`cli/main.py`（15 个子命令，见文件地图）。
- 验证：`python -m cli.main --help`、`health`、`record add`、`run`、`trace`。

## F18 后端 API 与持久化 ｜ 已实现

- 需求：Web/CLI 共用数据与业务逻辑；SQLite 保存全部状态。
- 实现：单库单写；CLI 与 API 都走同一 service 层（不是两套逻辑）。
- 验证：`tests/api/test_api.py`（10 例）。

## F19 自动化场景测试 ｜ 入口已实现，场景由 B 扩充

- A 提供：`scripts/run_scenarios.py` + 场景格式 + 示例场景（A 9 个 + B 24 个 = 33 个，覆盖 F21–F26 与主线）。
- B 负责：按同一格式扩充到 ≥30 个，并为六项增强功能各补正常/异常用例。

## F20 实测结果与复现报告 ｜ 已实现

- 输出：`evaluation/reports/scenario-report-*.json`（含 `llm_mode`、每场景 run_id、通过/失败、耗时）。
- 报告必须区分 mock 与 real；本次全部为 `mock`。

## F21 主动询问与信息补全 ｜ 已实现

- 需求：检测缺失字段 → 具体问题 → 保存等待状态 → 答复后恢复。
- 实现：`questioning/service.py`；`ask_user` 工具；答复可转成真实记录，`uncertain` 时不补全事实。
- 验证：`test_missing_data_triggers_question_then_resume`、`test_answer_uncertain_does_not_fabricate`、场景 `S02`。

## F22 多事件协调与优先级 ｜ 已实现

- 需求：多个事件合并、排序、去重、冲突检查。
- 实现：`planner.build_event_plan`（严重度权重 + 同类合并 + 优先级）、`validators.conflict_check`。
- 验证：`test_multi_event_merge_and_priority`（同类任务 `GROUP BY task_type` 计数恒为 1）、场景 `S03`。

## F23 计划协商与动态重规划 ｜ 已实现

- 需求：接受患者时间限制，经安全校验后改期并保留版本。
- 实现：`planner.parse_constraint` / `build_negotiation_plan` → `update_task` → `task_versions`。
- 验证：`test_negotiation_updates_task_and_saves_version`、场景 `S04`。
- 限制：只能改非医疗任务的时间/描述；治疗相关表述会被 `FORBIDDEN_ACTION` 拦截。

## F24 知识检索与证据约束 ｜ 已实现

- 需求：有限、来源明确的知识包；保留标题/机构/版本/段落；无证据不臆测。
- 实现：`knowledge/index.py`（4 篇带来源摘要，按标题+段落切块，锚点可定位）、
  `knowledge/search.py`（中文双字+IDF 打分，`min_score=6.0`）。`NO_EVIDENCE` 拦截无证据结论。
- 验证：`tests/unit/test_knowledge.py`、`test_knowledge_question_cites_source`、`test_no_evidence_blocks_claim`、场景 `S07`/`S08`。

## F25 长期偏好记忆 ｜ 已实现

- 需求：持久保存患者确认的时间偏好/障碍；可改可清；不得绕过安全门。
- 实现：`memory/preferences.py`（来源白名单、覆盖为 superseded）；偏好会调整新建非医疗任务时间。
- 验证：`test_preference_applies_to_new_tasks`、`GET/POST /api/patients/{id}/preferences`。

## F26 决策自检与不确定性 ｜ 已实现

- 需求：执行前检查证据/合法性/冲突；执行后比对数据库；失败不得记为成功。
- 实现：`safety/validators.py`（12 个拒绝码、`validate_plan`、`post_execution_check`）。
- 验证：`tests/unit/test_safety.py`（10 例，含伪造成功被 `POSTCHECK_MISMATCH` 捕获）。

---

## 全局验收口径（对应计划书 10.1）

| 条目 | 状态 | 证据 |
| --- | --- | --- |
| A1 全部功能有真实实现与验证命令 | ✅ | 本文件 + 文件地图 + 142 项 pytest（含 33 个场景 e2e） |
| A2 数据变更自动触发、到期调度、幂等 | ✅ | F06/F07 用例 + 场景 S01/S05 |
| A3 至少一次真实模型 tool call | ⚠️ 部分 | `real` 模式已端到端验证：本地 OpenAI 兼容 stub 服务器 → 原生 tool calling → 安全校验 → 真实写库 → `llm_mode=real`（`tests/integration/test_real_mode_stub.py`）；**本机无真实模型密钥，尚无真实厂商模型 smoke test，须由 A/B 接入真实端点后补** |
| A4 F21 提问恢复 / F22 合并 / F23 协商 / F24 可定位 / F25 跨运行 / F26 拦截 | ✅ | 集成用例与场景 S02–S08 |
| A5 三分支可复现、安全门禁止越权 | ✅ | S05/S06/S09 + `audit_log.decision='reject'` |
| A6 文档与代码一致、另一台机器可启动 | ✅（待第二台机器实测） | README + setup_and_run + 文件地图 |
