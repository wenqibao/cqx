# 数据字典（草案 v1，已与 `backend/app/db/schema.sql` 对齐）

> 约定：所有时间为 UTC ISO8601 字符串（`YYYY-MM-DDTHH:MM:SSZ`）；业务时间 = UTC + 演示时钟偏移。
> 所有业务表都带 `patient_id`，查询必须按患者过滤，禁止跨患者串数据。

## patients（F01/F02）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 患者编号，演示用 `P001`…`P00x` |
| name | TEXT | 姓名（虚构，标注"（虚构）"） |
| age | INTEGER | 年龄 |
| sex | TEXT | 性别 |
| diabetes_type | TEXT | 默认 `T2DM` |
| duration_years | REAL | 病程年数 |
| complications | JSON array | 已记录并发症（仅记录，不做判断） |
| goals | JSON array | 患者已确认的管理目标（系统不自行设定医学目标） |
| constraints | JSON array | 患者明确说明的约束（如"晚上要照顾孙子"） |
| baseline | JSON object | 身高体重等基线 |
| is_synthetic | INTEGER | 1=合成虚构病例（本项目恒为 1） |
| created_at / updated_at | TEXT | 时间戳 |

## health_records（F03）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER PK | 自增 |
| patient_id | TEXT FK | 患者 |
| kind | TEXT | `fasting_glucose` / `postprandial_glucose` / `steps` / `weight` / `medication_taken` / `symptom` / `meal` / `bp` |
| value | REAL | 数值；`medication_taken` 用 1/0 表示是/否 |
| unit | TEXT | 单位（mmol/L、步、kg…） |
| recorded_at | TEXT | 记录时间 |
| source | TEXT | `manual` / `csv_import` / `json_import` / `demo` / `question_answer` |
| note | TEXT | 备注 |
| payload | JSON | 扩展字段（`text` 症状描述、`systolic/diastolic` 血压） |
| dedupe_key | TEXT | 幂等键（患者+类型+分钟+值），唯一索引；重复写入返回 `duplicate=true` |

## events（F05）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | `EVT-*` |
| code | TEXT | `GLUCOSE_RISING` / `GLUCOSE_VARIABILITY` / `HYPOGLYCEMIA_RECORD` / `HYPERGLYCEMIA_RECORD` / `LOW_ACTIVITY` / `MEDICATION_NONADHERENCE` / `WEIGHT_GAIN` / `REVIEW_DUE` |
| severity | TEXT | `high` / `medium` / `low` |
| status | TEXT | `open` / `handled` / `merged` / `dismissed` |
| message | TEXT | 面向患者的说明（不含诊断结论） |
| evidence | JSON | 触发依据：窗口天数、命中值、记录 id |
| dedupe_key | TEXT 唯一 | `患者:规则:小时`，保证重复扫描不重复建事件 |

## agent_runs（F08/F14）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | `RUN-*`，对外主键，可复现一次决策 |
| trigger_type | TEXT | `record_created` / `event_detected` / `review_due` / `answer_received` / `task_completed` / `user_request` / `scheduled_tick` |
| trigger_ref | TEXT | 触发源 id（事件/问题/复评） |
| llm_mode | TEXT | **`mock` 或 `real`，必须如实记录** |
| model_name | TEXT | mock 为 `deterministic-planner`；real 为实际模型名 |
| status | TEXT | `running` / `completed` / `waiting_user` / `blocked` / `failed` |
| intent | TEXT | `event_response` / `check_in` / `knowledge_question` / `negotiate_plan` / `unsafe_request` / `patient_request` / `escalation` / `real_llm` |
| input / plan / output | JSON | 输入快照、计划、最终输出（含拒绝码与引用） |
| error | TEXT | 失败原因（不伪装成功） |

## agent_steps（F14）

| 字段 | 说明 |
| --- | --- |
| run_id + step_no | 同一次运行内的递增序号 |
| phase | `perceive` / `plan` / `validate` / `act` / `observe` / `self_check` / `finalize` |
| kind | `tool_call` / `tool_result` / `decision` / `validation` / `rejection` / `error` |
| tool_name | 工具名（`create_task`、`search_knowledge`…） |
| payload | 该步输入/输出 JSON |
| status | `ok` / `rejected` / `failed` / `skipped` |
| code | 拒绝码（见下） |

## tasks（F11/F23）

| 字段 | 说明 |
| --- | --- |
| id | `TSK-*` |
| task_type | `confirm_medication` / `record_glucose` / `record_activity` / `record_weight` / `review_*` / `review_followup` |
| status | `pending` / `done` / `missed` / `cancelled` |
| priority | 排序权重（安全类最高） |
| due_at | 截止时间 |
| event_id / source_run_id | 来源事件与运行（可追溯） |
| version | 版本号，每次改期/完成 +1 |
| required_fields | JSON array，复评判断数据是否齐备 |
| dedupe_key | 唯一索引，保证同类任务不重复入库 |
| meta | JSON（`event_ids`、合并标记、知识检索词） |

## task_versions（F23）

`task_id` + `version` + `snapshot`（完整 JSON 快照）+ `change_kind`（create/reschedule/complete/cancel）+ `reason` + `changed_by`（agent/patient/system）+ `run_id`。

## questions（F21）

| 字段 | 说明 |
| --- | --- |
| kind | `missing_field` / `ambiguous_record` / `confirm_change` |
| target_field | 目标字段（`medication_taken`、`steps`、`preferred_time_window`…） |
| status | `waiting` / `answered` / `expired` / `cancelled` |
| answer | JSON（`text` / `value` / `uncertain`） |
| resume_payload | 恢复执行所需上下文（事件、任务类型） |
| expires_at | 过期时间（默认 72h，过期后 `expire_stale` 置为 expired） |

## reviews（F12/F13）

| 字段 | 说明 |
| --- | --- |
| branch | `PENDING`（创建时）/ `CLOSED` / `MISSING_DATA` / `HUMAN_REVIEW` |
| status | `scheduled` / `completed` / `pending_human` |
| scheduled_for | 到期时间（由调度器在到期后评估） |
| detail | JSON：任务状态、事件严重度、数据点数量、人工结论 |

## preferences（F25）

| 字段 | 说明 |
| --- | --- |
| kind | `preferred_time_window` / `task_obstacle` / `contact_window` / `reminder_channel` / `note` |
| value | 偏好值（如 `08:00`、`morning`） |
| source | 仅允许 `patient_confirmed` / `patient_input` / `import`（禁止 Agent 推断） |
| status | `active` / `superseded` / `cleared`；新偏好把旧值置为 superseded |

## knowledge_docs / knowledge_chunks / evidence_items（F24）

- `knowledge_docs`：`id`（KD-001…）、`title`、`publisher`、`version`、`source_url`、`published_at`、`path`、`checksum`。
- `knowledge_chunks`：按二级标题+段落切分，`anchor` 形如 `#1-自我血糖监测的意义-2`，供引用定位。
- `evidence_items`：一次运行实际引用的证据（`run_id`、`doc_id`、`chunk_id`、`anchor`、`quote`、`score`、`query`）。

## notifications（F16）

`kind`：`task_created` / `task_updated` / `task_overdue` / `question_created` / `review_due` / `agent_alert` / `reminder`；`status`：`unread` / `read`；`ref_type` + `ref_id` 指回业务对象。

## automation_jobs（F07）

`kind`：`agent_run` / `review_due` / `event_scan` / `overdue_check` / `reminder`；`status`：`pending` / `running` / `done` / `skipped` / `failed`；`attempts` 最多 3 次，失败按 60s×次数重试。唯一索引 `(kind, patient_id, ref_id, run_at)` 保证同一作业只入队一次。

## audit_log（F13/F14）

`actor`（agent/patient/system）、`action`、`decision`（`allow` / `reject` / `escalate` / `info`）、`code`、`detail`。
`decision='reject'` 是**拦截**记录，不等于执行。`GET /api/system/audit` 分开返回：
`forbidden_executed`（成功工具调用中出现越权工具/动作文本的次数，必须是 0）、
`blocked_total`（拒绝条数，随拦截增加）与 `checked_tool_results`（本次计数覆盖的工具结果数，便于交叉核查）。

## 拒绝码（`backend/app/safety/validators.py`）

| 码 | 含义 |
| --- | --- |
| `NO_EVIDENCE` | 需要知识证据但检索无结果（禁止臆测） |
| `FORBIDDEN_ACTION` | 计划/文本包含禁止的医疗动作 |
| `TOOL_NOT_ALLOWED` | 工具不在白名单 |
| `TOO_MANY_ACTIONS` | 单次计划动作超限 |
| `INVALID_DUE` | 截止时间越界或非法 |
| `DUPLICATE_TASK` | 重复任务/时段冲突 |
| `MISSING_REQUIRED_DATA` | 缺少必要数据 |
| `TASK_NOT_FOUND` | 引用的任务不存在 |
| `TOOL_EXECUTION_FAILED` | 工具执行失败 |
| `POSTCHECK_MISMATCH` | 工具声称成功但数据库不一致 |
| `UNSAFE_CLAIM` | 不安全表述 |
| `UNKNOWN_TOOL` | 未知工具 |
