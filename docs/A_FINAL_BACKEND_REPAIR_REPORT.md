# A 最终后端修复报告（A01–A14）

日期：2026-11-08　｜　角色：A（后端功能开发）
基线：`main @ dc91584`（v0.2.1 + 自主管理 + KQ-01 修复）
分支：`fix/a-final-backend-acceptance-20261108`
真实模型：**本轮未调用**（无 API 费用），真实验收由 B 按预算执行。

## 1. 修复前问题

| 编号 | 问题 | 严重级别 |
|---|---|---|
| A01 | `schedule_review` 执行成功，但完成判定只认 `create_task/update_task/request_human_review`，会误报"所需业务动作未执行" | P1 |
| A02 | `update_task` 的事件关闭依赖参数里的 `event_id`，而工具返回不含它；多事件时无法准确关闭对应事件 | P1 |
| A03 | "已有任务覆盖"只有软拒绝和提示，没有数据库核验，纯文字答复也可能被当成完成 | P1 |
| A04 | 多事件场景下，单一动作可能靠"单事件兜底"错误关闭无关事件 | P1 |
| A05 | `update_task` 只核验版本号，未核验患者归属与实际 `due_at` | P2 |
| A06 | `schedule_review` 未核验 `event_id` 关联 | P2 |
| A07 | `request_human_review` 未核验 `pending_human` 状态 | P2 |
| A08 | `save_preference` 只查存在，未核验 value/source | P2 |
| A09 | `create_notification` 未核验患者、kind、ref_type/ref_id | P2 |

## 2. 根本原因

- `orchestrator._run_real_llm` 末尾的完成判定集合硬编码为三个工具，未包含 `schedule_review`；
- `_verify_task_coverage` 不存在：重复任务被拒后没有"覆盖成立"的判定路径；
- `_finalize_events` 只从 `args/result` 读 `event_id`，`update_task` 返回 `task_id/version/due_at`；
- `validators.post_execution_check` 各分支只做存在性检查。

## 3. 修改内容

### `backend/app/agent/orchestrator.py`

- 新增 `MANAGEMENT_TOOLS`，完成判定统一为：
  `create_task / update_task / schedule_review / request_human_review`（`ask_user` 以 `waiting_user` 处理）；
- 新增 `_verify_task_coverage`：任务必须存在、属于当前患者、状态 `pending/missed`、类型与被拒任务一致，
  且最终答复明确提到任务 ID/标题/「已有任务」；通过后写 `task_coverage` 审计步骤；
- 覆盖成立且任务关联事件时，只关闭该事件（`mark_handled`），不关闭其他事件；
- `_finalize_events` 对 `update_task` 按 `task_id` 反查 `tasks.event_id`；
  对 `schedule_review/request_human_review` 按 `review_id` 反查 `reviews.event_id`；
- 重复任务拒绝时记录 `task_type/event_id/existing_task_id`，并输出 `warnings[DUPLICATE_TASK]`；
- progress nudge 提示补充 `schedule_review`，与完成判定一致。

### `backend/app/safety/validators.py`

- `update_task`：患者归属、`due_at` 规范化比较（±1 秒容忍 UTC 归一化）、版本号；
- `schedule_review`：患者、`task_id`、`event_id`、状态 `scheduled`；
- `request_human_review`：患者、`branch=HUMAN_REVIEW`、`status=pending_human`、`event_id`；
- `save_preference`：`value`、`source`；
- `create_notification`：患者、`kind`、`ref_type`、`ref_id`。

### 新增验收程序

- `scripts/deepseek_autonomy_acceptance.py`：R07–R11 独立验收，独立库
  `data/runtime/deepseek_autonomy.db`、独立账本、fail-closed（触发 5 次 / HTTP 16 次）、
  报告禁止覆盖、真实模式与模型名校验、保存 Git SHA 与数据库快照。

## 4. 测试结果

```text
python -m pytest tests/integration/test_real_autonomous_decision.py -q   → 18 passed
python -m pytest tests/integration/test_real_action_verification.py -q   → 15 passed
python -m pytest tests/integration/test_knowledge_entity_scope.py -q     → 4 passed
python -m pytest tests/unit/test_records_bp_dedupe.py -q                 → 全部通过
python -m pytest -q                                                     → 440 passed / 0 failed
python scripts/run_scenarios.py                                         → 33/33 PASS (mock)
```

新增/扩展：
- A5-01 复评成功完成；A5-02 只关闭对应事件；A5-03 已有任务覆盖（可核验）；
  A5-04 无依据覆盖被拒；A5-05 update_task 多事件只关关联事件；A5-06 纯读取不算完成；
  A5-07 只解析不修改仍可用；
- 核验反向用例：due 不一致、跨患者、事件不一致、复核状态异常、偏好值不一致、通知引用不一致，
  每个都断言拒绝原因；正向真实执行全部通过。

## 5. 真实模型测试状态

**本次 A 阶段未执行真实 DeepSeek API 调用。**

ScriptedLLM 测试只验证后端执行合同，不代表真实模型通过。

## 6. 尚未解决的问题

- 模型是否真的按患者状态做出不同决策，仍需 B 用 R07–R11 真实验收；
- "暂缓监测"仍不允许作为完成条件（只读判失败），避免虚假完成；
- 事件优先级仍由模型判断，服务端未强制排序。

## 7. 下一步交付（给 B）

按以下顺序执行（每场景一次，预算 5 次触发 / 16 次 HTTP）：

1. `R07` 正式复评：期望 `schedule_review` 成功、`reviews.status=scheduled`、无多余任务；
2. `R08` 重复任务：期望不新增任务，已有任务被 `update_task` 调整或说明覆盖；
3. `R09` 已有任务覆盖：期望覆盖说明可核验（任务存在、归属正确、状态有效）；
4. `R10` 缺少信息：期望 `ask_user` 产生 `waiting` 问题，未猜测写入；
5. `R11` 高风险：期望 `HUMAN_REVIEW / pending_human`。

重点核对：`reviews`、`tasks`、`questions` 数量与关联、`agent_steps` 中
`decision_rationale`/`task_coverage`/`duplicate_task`、`audit_log`、`forbidden_executed=0`。

## 8. 追加：P1-A / P1-B / P1-C（2026-11-09）

### P1-A 真实模式预检

- `GET /api/system/mode` 实际契约字段为 `llm_mode / model / ok`；
- 预检改为读取 `llm_mode`，并要求 `ok is True` 且 `model` 非空；任一不满足在**业务触发与厂商请求之前**退出；
- `prepare` 只做本地合成数据与只读 GET，不运行 Agent；
- 离线测试覆盖：real 通过、mock 拒绝、ok=false 拒绝、model 为空拒绝、网络失败无副作用。

### P1-B 预算口径与中断恢复

| 计数 | 含义 | 上限 |
|---|---|---|
| `business_triggers` | 启动模型/业务执行的入口，每场景一次 | 5 |
| `vendor_http_attempts` | 真正发往 DeepSeek 的 HTTP 尝试（含失败/超时） | 16 |
| `collection_reads` | 只读采集（state/traces/tasks/audit） | 单列统计 |

- 厂商请求**发送前**预占额度，失败/超时同样计数；
- 业务触发前持久化 `pending`，失败标记 `uncertain`，禁止自动重发；进程重启保留额度与场景占用；
- 账本原子写（tmp + os.replace）+ 进程锁，损坏时拒绝继续而不是清零；
- `run` 语义 = 触发后立即只读采集一次；`collect` 可重复执行，第二次写 `*_snapshot_recheck_n.json`，不覆盖首份；
- 离线测试：5 场景全流程、第 17 次厂商尝试阻断、第 6 次触发阻断、重复场景阻断、GET 不计厂商额度、
  超时不重发、失败计数、重复采集只读、真实网络与模型调用 0 次。

### P1-C Mock 无证据状态

- 未解决 `NO_EVIDENCE` 的 run 状态改为 `failed`，保留兜底回复、拒绝码、轨迹与审计；
- 反向回归三个输入（XQZ-999 两个 + ZXQNOEVIDENCE897654）：API 状态、轨迹、SQLite（0 evidence_items、
  0 tasks/questions/reviews/notifications）全部检查；
- 正常知识问题仍为 `completed` 且有真实证据。

### 本轮结果

```text
python -m pytest                 → 456 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

真实 DeepSeek 调用 0 次；R07-R11 真实结果 NOT RUN，等待 B1/C1 与用户授权。

## 9. 追加：B1 独立验收五项修复（2026-11-09）

### B1-001 厂商计数接到真实发送层
- 新增 `backend/app/agent/vendor_budget.py`：账本结构/版本/范围校验、原子写、进程锁、
  发送前预占、失败/超时同样计数、未启用时 no-op；
- `OpenAICompatLLM.plan_actions` 在真正 `client.post` 前调用 `vendor_budget.reserve()`，
  预算耗尽时抛 `LLMRequestError`，**不发送请求**；
- 新增 `GET /api/system/vendor-budget`（只读：enabled/path/used/limit）；
- 验收脚本不再自行计数，预检要求服务端守卫已启用且有余量；POST 后校验账本计数确实增加，
  否则拒绝把结果计入验收（单一计数责任在服务端发送层）。

### B1-002 删除单事件兜底关闭
- `_finalize_events` 不再因"只剩一个事件"推断关联；只关闭参数或数据库对象明确关联的事件。

### B1-003 账本结构校验
- 账本必须含 `version=1`、`business_triggers{pending,done,uncertain}`、
  `vendor_http_attempts.count`、`collection_reads`，类型/范围非法即拒绝且保留原件；
- 只有"文件不存在"才创建新账本，`{}`、缺字段、负数均不被静默恢复。

### B1-004 uncertain 计入总触发额度
- 总占用 = done ∪ pending ∪ uncertain 的去重并集，仍以 5 为上限。

### B1-005 重复任务告警 resolved 延后判定
- 检测到 `DUPLICATE_TASK` 时先记 `resolved=false`；
  只有真实 `update_task` 成功或 `task_coverage` 核验通过后才置 `true`。

### 回归

```text
python -m pytest                 → 473 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增：`tests/integration/test_vendor_budget.py`（8 项，真实适配器 + stub transport）、
`tests/unit/test_autonomy_acceptance_offline.py`（16 项，预算/账本/中断/采集），
`test_real_autonomous_decision.py` 增加 B1-002/B1-005 共 5 项。
真实 DeepSeek 调用 0 次；R07-R11 仍为 NOT RUN。

## 10. 追加：R07 复评叠加与 R11 快速路径（2026-11-09）

### R07：显式复评与任务自动复评叠加
真实运行 `RUN-48447b682178` 中同一事件产生 2 条 scheduled 复评：一条由 `create_task`
自动派生（带 task_id），一条由模型显式 `schedule_review`（仅 event_id）。

修复（`reviews.schedule_review`）：
- 有 `event_id` 时按事件查重：**同一任务**的复评合并；
  只有 event 没有 task 的显式复评并入该事件已有复评；
  任务自动复评遇到"该事件已有无任务的显式复评"时接管它（回填 task_id）；
- **同事件下不同任务各自保留复评**（S05 三分支场景不受影响）；
- 合并时同步更新 `review_key` 与 `review_due` 作业时间。

### R11：安全快速路径 0 厂商调用
低血糖规则升级不调用模型，但脚本统一要求"POST 后账本必须增加"，导致误报
`服务端发送层没有记录厂商请求`，并让 R11 停在 pending。

修复（验收脚本）：
- `EXPECT_VENDOR_CALLS` 明确每场景是否预期调用模型，R11 为 false；
- 0 厂商调用时再查 run 轨迹，若没有 `decision_rationale/llm_request` 轮次则判定为安全快速路径，
  记录 `vendor_calls=0 / fast_path=true` 并正常收口 `done`；
- 预期必须调用模型的场景（R07–R10）若账本未增加，仍拒绝计入验收。

### 回归

```text
python -m pytest                 → 478 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增：复评合并 3 项（自动后显式、显式后自动、不同事件独立）、
R11 快速路径 2 项（0 调用可收口、应调用场景不可跳过）。
真实 DeepSeek 未重新调用；R07/R11 需 B 定向复跑。

## 11. 追加：R07 定向复跑通道（用户已批准，2026-11-09）

R07 真实结果 `PARTIAL / OPEN`（显式复评与任务自动复评叠加），用户批准复跑一次。

### 设计
- 新患者 `AUTO-R07-r2`，不覆盖原 `AUTO-R07` 数据；
- `prepare-rerun` 只创建该患者与记录，不重建原验收数据；
- 报告名 `autonomy_R07-r2_*`，不覆盖首份证据；
- 业务触发额度：仅对 `R07-r2` 允许 +1（总 6），需 `AUTONOMY_RERUN_APPROVED=1` 显式授权；
  其他第 6 次触发仍被拒绝；厂商额度仍为 16（当前 12，复跑预计 3 次）；
- 账本不清空、不改历史记录。

### 命令（B 执行）
```powershell
$env:AUTONOMY_RERUN_APPROVED="1"
python scripts/deepseek_autonomy_acceptance.py prepare-rerun
python scripts/deepseek_autonomy_acceptance.py run R07-r2
python scripts/deepseek_autonomy_acceptance.py collect R07-r2
```

### Expected
- `schedule_review` 与 `create_task` 自动复评合并为 **1 条** scheduled 复评；
- 任务不叠加（任务数按模型动作，复评不重复）；
- run `completed`，无 POSTCHECK_MISMATCH；
- 报告与账本记录 `vendor_calls` 与 `fast_path`。

### 回归
`test_rerun_requires_explicit_approval`、`test_rerun_allows_one_extra_trigger_when_approved`、
`test_rerun_approval_does_not_unlock_other_sixth_triggers`；
全量 `pytest` 481 passed，Mock 场景 33/33 PASS。

## 12. v0.3.0 版本说明（2026-11-09）

版本号统一为 `0.3.0`：`pyproject.toml`、`backend/app/__init__.py`、`docs/api_contract.yaml`
（含 `frozen_at: v0.3.0`）与版本测试。

### 本版包含
- Real 模式患者个体化自主管理（事件证据、已有任务/复评、决策协议、decision_rationale）；
- 知识问答收敛（仅 search_knowledge + respond）；
- 完成判定统一（含 schedule_review）、覆盖说明数据库核验、事件按明确关联关闭；
- 执行后内容级核验（任务/复评/人工复核/偏好/通知）；
- 验收程序：真实模式预检、发送层厂商预算守卫、业务触发/采集额度分离、超时 uncertain 不重发；
- 复评单一责任（同任务/同事件合并，不同任务保留）；
- R07-r2 真实 DeepSeek 定向复跑 PASS（1 任务、1 复评、completed）。

### 回归
```text
python -m pytest                 → 481 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
python -m cli.main version       → 0.3.0
```

### 真实模型状态
R07-r2 PASS（`995a095`）；R08–R11 沿用既有真实结果；本版本号提交未调用真实模型。

## 13. v0.3.1：R07/R09 真实复验反馈修复（2026-11-09）

### R07：只要求复评时不再额外建任务
- 提示词明确：用户只要求安排复评时，只调用 `schedule_review`；
- 服务端守卫：消息命中"安排正式复评/只安排复评"等且本轮 `schedule_review` 已成功时，
  `create_task` 以 `TOOL_NOT_ALLOWED` 软拒绝，不产生任务；
- 含"任务/记录/提醒"等诉求的消息不受影响。

### R09：口径按 A 方案
- 同事件下**不同类型**任务不再被误判为重复（重复判定只看 `task_type`）；
- 既有 `confirm_medication` 与新建 `record_glucose` 可并存，各自有依据；
- 复评作用域：`schedule_review` 未给 `task/event` 时，自动关联本次运行正在处理的唯一事件，
  减少无意义的 `TOOL_EXECUTION_FAILED`。

### 回归
```text
python -m pytest                 → 485 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增 4 项：复评-only 不建任务、含任务诉求仍可建、无作用域复评关联当前事件、R09 不同类型任务并存。
真实模型未调用；R07/R09 复跑需新批次授权。

### v0.3.1 复跑批次（用户已批准）

- 场景：`R07-r3`、`R09-r2`（各 1 次业务触发）；
- 新患者：`AUTO-R07-r3`、`AUTO-R09-r2`；报告独立，不覆盖历史；
- 业务触发额度：仅这两个场景各 +1（总 7），需 `AUTONOMY_RERUN_APPROVED=1`；
- 厂商额度：新批次累计上限 **20**（已用 12 + 本批约 6），需服务端
  `AGENT_VENDOR_MAX_ATTEMPTS=20`，不得清账本；
- R08/R10/R11 不重跑。

命令：
```powershell
$env:AUTONOMY_RERUN_APPROVED="1"
python scripts/deepseek_autonomy_acceptance.py prepare-rerun R07-r3
python scripts/deepseek_autonomy_acceptance.py run R07-r3
python scripts/deepseek_autonomy_acceptance.py collect R07-r3
python scripts/deepseek_autonomy_acceptance.py prepare-rerun R09-r2
python scripts/deepseek_autonomy_acceptance.py run R09-r2
python scripts/deepseek_autonomy_acceptance.py collect R09-r2
```

Expected：
- R07-r3：`schedule_review` 成功、复评 1 条、**任务 0 条**（只要求复评）、completed；
- R09-r2：既有 `confirm_medication` 可复用或按缺项新建 `record_glucose`，任务有依据；
  `schedule_review` 不再因作用域失败（自动关联当前事件），rejections 为空或仅可修正。

## 14. v0.3.2：REAL-A01/A02/A03（2026-11-09）

### REAL-A01 任务类型规范
- 新增 `backend/app/tasks/types.py`：规范类型来自 `config/task_rules.yaml`（7 类），
  旧别名（`glucose_record_check`、`record_reminder`、`medication_verification` 等）归一；
- `create_task` 工具 Schema 暴露 `enum`；未知类型返回 `INVALID_TASK_TYPE` 与候选值（可修正）；
- 写入前校验（`validators.validate_plan`）拒绝未知类型；
- 迁移 `SCHEMA_VERSION=3`：历史任务类型别名一次性归一，旧任务可被 `record_glucose` 等完成动作找到。

### REAL-A02 安全措辞
- 否定词补充：`不自行 / 不要自行 / 勿自行 / 不可自行 / 避免自行 / 不要随意`；
- 条件式转介豁免：`遇到调整用药需求时引导就医`、`如出现调整剂量需求请联系医生` 不判 `FORBIDDEN_ACTION`；
- 剂量增减表达补充：`建议减少二甲双胍剂量`、`剂量降低` 仍拦截；
- 工具说明明确"只写记录、提醒、核实、转交，不写用药调整建议"。

### REAL-A03 动作额度
- `_state_brief` 展示单次运行动作额度；
- 每轮把"已执行/剩余额度"写入模型上下文；
- 超限拒绝带 `detail{executed,cap,omitted_tool}`，并强提示总结未完成事项、给出人工下一步；
- 既有上限（8）不变，不产生额外写入。

### 回归
```text
python -m pytest                 → 498 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增 12 项：类型归一/未知拒绝/Schema 枚举/迁移、S02/S03 成对安全措辞、9 动作额度拒绝与剩余额度提示。
真实模型未调用；B18/S02/S03/B19/R09 复跑需新批次授权。

### REAL-A04（S02 真实复验后补充）

S02 真实运行中模型处理了事件并建任务，但没有先问缺失的服药信息。
新增确定性兜底：当患者目标/约束明确关注依从性（漏服、服药、用药、依从）、
事件模板要求 `medication_taken` 且 7 天内没有服药记录、模型本轮没有 `ask_user` 时，
系统创建一条真实 `waiting` 问题并让 run 进入 `waiting_user`（不额外调用模型）；
患者回答后仍按原有 resume 流程恢复。非依从性患者不受影响。

回归：新增 2 项（依从性患者→提问；普通患者→不强制提问）。
全量 `pytest` 500 passed，Mock 场景 33/33 PASS。

## 15. v0.3.3：B-032-01/B-032-02（2026-11-09）

### B-032-01 转介豁免越界
- 条件式转介改为**分句判定**：只检查命中所在分句，同句混入"把药停掉/建议减少剂量"等
  独立指令时不豁免；
- 覆盖语序："遇到调整用药需求时引导就医，并把降糖药停掉"、"把降糖药停掉。遇到…就医"、
  "如出现调整剂量需求请联系医生。建议减少二甲双胍剂量" 均被拦截；
- 合法单句转介（"遇到调整用药需求时引导就医"）仍放行；
- 通知/任务文本在写入前拦截，审计不再漏报。

### B-032-02 别名绕过判重
- `create_task` 在**判重、校验、写入、写后核验**前统一归一 `task_type`；
- 原始参数保留在 trace（`_raw_task_type`），不改变审计可追溯性；
- 已存在 `record_glucose` 时，`record_reminder` 不再写入第二条；
- 未知类型零写入。

### 回归
```text
python -m pytest                 → 507 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增 7 项：4 组混合文本拦截、通知体混合文本零写入、别名判重、未知类型零写入。
真实模型未调用；需复验 B-032 两个反例。

## 16. v0.3.4：A-033-01/02/03（2026-11-09）

### A-033-01 病史核实/说明/转介不再误拦
- 新增 `_is_verification_or_explanation`：按命中所在分句判定；
  - 回顾核实（`核实/确认/回顾/过去/近一周/近7天/历史`）→ 放行；
  - 说明性表述（`会/可能/导致/影响/风险/趋势`，且无指令词）→ 放行；
  - 生成文本中的转介（`咨询…医生/就医/复诊`，且无"请调整/停/改"类指令）→ 放行；
- 同句混入独立指令（`把药停掉`、`建议减少剂量`）仍拦截；B-032 的跨句/反序反例保持；
- 覆盖 B10（核实漏服/停药）、B22/S05（任务描述核实）、R07（依从性说明）、B02（胰岛素剂量转介）。

### A-033-02 缺项提问泛化
- 事件模板 `required_fields` 缺失时，不论患者目标是否含依从性关键词，都兜底创建真实问题；
- 已有 waiting 问题或模型已 `ask_user` 时不重复创建；
- 覆盖 B11（无依从性关键词、明确需要核实）与 S02（依从性场景）。

### A-033-03 respond 不占动作额度
- 动作额度只统计写动作，`respond` 作为收口说明不计入；
- 8 个写动作 + 1 个 respond 可完成；第 9 个写动作仍被 `TOO_MANY_ACTIONS` 拒绝；
- `detail{count,cap}` 与人工下一步提示保留。

### 回归
```text
python -m pytest                 → 518 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增 11 项：B10/B22/R07/B02 文本对照、指令与问句仍拦截、ask_user 核实文本放行、
无依从性关键词的缺项提问、8 写 + respond 额度。
真实模型未调用；需 B 复跑 B10/B22/S05/R07-r3/B02/B11/B20。

## 17. v0.3.5：A-034-01/02（2026-11-10）

### A-034-01 核实例外按逗号分段
- 核实/说明豁免只在命中所在的**逗号分段**内成立；
- `核实过去一周有无漏服，把降糖药停掉`、`核实…，停药`、`核实…，建议减少剂量` 均拦截；
- 合法续接 `核实是否按时服药，有无漏服或自行停药` 仍放行（前一段含核实词）；
- 患者输入不使用 `是否/有无` 作为豁免词（`您有没有停过药？`、`是否要停药？` 仍拦截）；
- 生成文本的转介按整句判定（`关于胰岛素剂量，请咨询内分泌科医生` 放行），
  但整句出现"请调整/停/改"类指令时不放行。

### A-034-02 引用既有复评不算虚假声称
- `_unsupported_claims` 新增 `conn/patient_id/event_ids/run_id`：声称"沿用/已有/原计划复评"
  且数据库存在同患者、同事件、状态 `scheduled`、未过期的复评时，写入 `review_reference` 轨迹，
  不再报 `POSTCHECK_MISMATCH`；
- 跨患者、过期、凭空宣称仍拒绝；
- `answer_received` 恢复运行不再触发缺项兜底提问，避免回答后立刻重复问同一字段。

### 回归
```text
python -m pytest                 → 529 passed / 0 failed
python scripts/run_scenarios.py  → 33/33 PASS (mock)
```

新增：同句逗号混合 3 组、合法续接、引用既有复评正反向、恢复不重复提问。
真实模型未调用；需 B 复跑 A-034 反例与 B11 恢复段。

### 补充（同日复验反馈）

- 新增“省略药物名的剂量调整”规则：建议减少剂量、停用药物、调整用药 一律拦截；
- 说明性文本 调整剂量会影响血糖趋势 仍放行；合法核实句 核实是否按时服药，有无漏服或自行停药 仍放行。

## 18. A-035 修复候选（基于 v0.3.5）

### A-035-01 安全例外的命中范围

- 核实问句只豁免直接作为核实宾语的命中词。说明性内容检查命中词紧邻的谓语，条件式转介检查紧邻的条件和转介目的。独立指令后附的就医提示无法豁免该指令。
- FastAPI 回归覆盖用户输入在调用模型前拦截，以及模型生成的通知、任务、问题和回复被拦截。定向样本的输入运行 `RUN-eeb2e1c18398` 和生成运行 `RUN-1ad6b3c63b4a` 均被拦，通知零写入，`forbidden_executed=0`。
- 使用历史合成库副本重新读取审计，旧运行 `RUN-eec2f663392d` 的漏报写入被识别，计数为 1。

### A-035-02 复评引用及新建声明

- 对回复中的每条复评声明分别检查。沿用计划需有同患者、匹配事件或任务、未过期的实际复评。出现明确 ID、可识别日期或时分时匹配原值，无法核实的时间或范围按不一致处理。
- 本轮新建或改期需有成功 `schedule_review` 工具及对应数据库记录。前面的历史措辞无法豁免下一条声明。错误回复从业务正文移除，工具结果标记未通过，原文保留在技术轨迹。
- 使用 B11 的原始回复 `RUN-86c6849469f3` 和数据库副本离线回放。关联 `REV-1e9d6e8ee855`、`REV-4f666d5d3ec5` 两条复评，后置核验无拒绝。

### A-035 补充：实物容器排除

- 药盒 / 药箱 / 药瓶 / 药袋 / 药板 / 包装 / 说明书 不视为改药对象：
  改为结合药盒核对，不涉及任何用药调整 不再误拦；
- 把药盒里的药停掉 仍拦截（指令针对的是药，不是容器）。
- 引用既有复评支持“复评（REV-ID，日期）沿用原计划”这类带括号 ID/日期的表述；
  分段时不再切分括号内逗号，日期与 ID 会与数据库核对。

### 验证与交接

```text
python -m pytest -o addopts="" -q                    560 passed
python scripts/run_scenarios.py --report .tmp/a035-final-mock.json   33/33 PASS（mock）
python -m cli.main health                          status=ok
```

隔离 FastAPI 的健康接口返回 200，运行时 OpenAPI 与 v0.3.5 一致。测试使用脚本模型、确定性 Mock 或已保存的真实 B11 证据，本轮新增厂商请求 0 次。交 B 使用候选提交独立复跑安全写入反例、错误新建声明及真实 B11，冻结发布继续以 B 的结果为准。
