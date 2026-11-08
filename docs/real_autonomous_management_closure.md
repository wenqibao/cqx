# Real 模式患者个体化自主管理收口（A-REAL-AUTONOMY-01）

日期：2026-11-08　｜　作者：A
基线：`main @ 694be88`（v0.2.1）　｜　分支：`feature/backend-autonomous-management`
验证：Mock / ScriptedLLM（**真实 DeepSeek：NOT RUN，待 B 在新预算内验收**）

## 1. 原始失败表现

历史真实运行（`RUN-04a267842b5d` 等）暴露：模型能检索、能读状态，但不知道"该做什么"：

- 只调用 `search_knowledge` / `query_history` / `get_preferences`，不产生管理动作；
- 看到 `GLUCOSE_RISING` 就倾向固定动作，而不是按患者状态判断；
- 已有待办任务时仍重复创建同类任务；
- 缺信息时不询问，或询问与问题无关的字段；
- 工具返回成功但无法与数据库状态交叉核对。

## 2. 源码级根因

| 现象 | 根因位置 | 说明 |
| --- | --- | --- |
| 只读不行动 | `orchestrator._run_real_llm` | 只读轮没有推进提示；模型没有"先读后行动"的显式协议 |
| 机械决策 | `orchestrator._state_brief` | 上下文只给事件**代码**，没有证据、已有任务/问题/复评，模型无法区分患者 |
| 重复建任务 | `_state_brief` + `orchestrator` | 已有待办没有进入模型可见上下文，模型只能重复创建 |
| 事件关联缺失 | `services/state.build_state` | `open_events` 只查 `code/severity/status/message/detected_at`，缺 `evidence` 与记录 ID |
| 复评不可见 | `build_state` | 没有查询 `reviews`，模型不知道已有 scheduled/pending_human 复评 |
| 执行不可核验 | `validators.post_execution_check` | `create_task` 只查存在，`request_human_review` 走通用成功分支 |
| 工具定义不一致 | `tools.TOOL_SPECS` | `schedule_review` 未暴露 Handler 已支持的 `reason` |
| 管理动作分类不一致 | `orchestrator.ACTION_TOOLS` | `schedule_review` 未纳入管理动作集合 |

## 3. 修改内容

### 3.1 Patient State（`services/state.py`）

- `open_events` 增加 `evidence_summary`（阈值/趋势/区间/次数等）与 `record_ids`（最近 5 条）；
- 新增 `open_reviews`（scheduled / pending_human：id、task_id、event_id、branch、scheduled_for）；
- 新增 `recent_answers`（最近 5 条已答复/过期问题，含 answer 与时间）；
- 任务保留 `event_id/version/required_fields`，问题保留 `target_field/status`；
- 所有查询带 `patient_id` 作用域，记录查询有 `<= now` 上界。

### 3.2 有界上下文（`orchestrator._state_brief`）

按"高风险优先、证据优先、最近优先"组织：患者目标/约束/档案完整度、7 天三项指标、趋势、
最近记录、逐条事件（含证据与记录 ID）、已有待办任务、待回答问题、最近答复、已安排复评、
回答上下文、有效偏好。只给必要字段，不塞全量历史。

### 3.3 决策协议（系统提示）

新增显式协议：先读状态 → 高风险优先 → 同事件不同患者可不同行动 → 已有任务能覆盖则更新/沿用 →
缺信息先问 → 需要复评用 `schedule_review`、高风险用 `request_human_review` → 每个动作必须可核验。

### 3.4 工具与分类（`tools.py` / `orchestrator.py`）

- `schedule_review` Schema 补 `reason`，与 Handler 一致；
- `ACTION_TOOLS` 纳入 `schedule_review`；
- 复评软拒绝统一按 `task_type`（`follow_up_review/followup_review/review`）判断，标题不再参与。

### 3.5 执行后核验（`validators.post_execution_check`）

逐工具与 SQLite 交叉核对：

- `create_task`：任务存在、患者/类型/状态正确、`event_id` 与参数一致；
- `ask_user`：问题存在、`waiting`、患者与 `target_field` 一致；
- `schedule_review`：复评存在、患者/任务关联正确、状态 `scheduled`；
- `request_human_review`：`branch=HUMAN_REVIEW`、患者一致；
- `save_preference` / `create_notification`：记录存在且归属正确；
- 其余保持既有检查（`update_task` 版本、`complete_task` 状态）。

### 3.6 结构化决策轨迹

Real 模式每次工具调用前写入 `agent_steps.kind='decision_rationale'`：
`round / rationale（≤200 字）/ tools / linked_event_ids`。
使用同一模型响应，不额外增加请求；不记录隐藏思维链。

## 4. 防重复与防虚假完成

- 已有任务/问题/复评进入模型上下文，提示明确"先判断是否覆盖，不要重复创建"；
- `create_task` 的服务层去重、`schedule_review` 的单一责任、通知幂等继续生效；
- 工具"报成功但库里没有"→ `POSTCHECK_MISMATCH`；事件关联错误、患者归属错误同样失败；
- 只读不行动仍判失败，事件保持 `open`；安全拒绝不被 warnings 豁免。

## 5. 测试

新增 `tests/integration/test_real_autonomous_decision.py`（5 项，ScriptedLLM）：

1. 相同事件、不同患者状态 → 模型上下文不同（含证据、已有任务），可做不同决策；
2. 已有待办任务 → 更新而不重复创建，版本递增；
3. 缺信息 → `ask_user` 指定字段，`waiting`，不猜测写入；
4. 高风险 → `request_human_review`，`HUMAN_REVIEW/pending_human`，不建普通任务；
5. 决策轨迹含 rationale / tools / linked_event_ids。

新增 `tests/integration/test_real_action_verification.py`（8 项）：
伪造成功、错误患者、错误事件关联、复评/人工复核/通知/问题不存在等均被 postcheck 拦截；
真实任务通过核验。

回归：

```text
python -m pytest        → 416 passed
python scripts/run_scenarios.py → 33/33 PASS (mock)
```

## 6. 验证类型区分

| 类型 | 本轮结果 | 能证明什么 |
| --- | --- | --- |
| Mock 场景 | 33/33 PASS | 既有合同未回退 |
| ScriptedLLM | 13 项新回归通过 | 后端执行合同、上下文装配、核验逻辑 |
| Real DeepSeek | **NOT RUN** | 不能据此声称模型自主决策通过 |

真实模型自主决策是否达标，必须由 B 在新预算内用同一组场景复验。

## 7. 仍未解决

- "暂缓监测"作为合法完成条件尚未开放：只读不行动仍判 failed（避免虚假完成）；
- 事件优先级仍由模型判断，未在服务端强制排序；
- 真实模型的决策质量（是否真的按患者状态选择不同行动）待 B 验收。

## 8. 对前端/契约的影响

- `GET /patients/{id}/state` 新增 `open_reviews`、`recent_answers`，事件增加
  `evidence_summary/record_ids`（均为增量字段，旧消费方可忽略）；
- 运行轨迹新增 `decision_rationale` 步骤类型；
- 无删除、无改名，`v0.2.1` 契约保持兼容。
