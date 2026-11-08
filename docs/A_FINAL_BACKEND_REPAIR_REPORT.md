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
