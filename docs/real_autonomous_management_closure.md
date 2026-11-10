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

## 9. 追加：知识问答意图收敛（A-REAL-AUTONOMY-02，2026-11-08）

### 真实表现
患者只问「血糖 9.8 是不是太高」，真实模型却建任务、发通知、提人工复核：
一次 9 个任务触发 TOO_MANY_ACTIONS 直接 failed（RUN-f3cf61a3bee5），
另一次 completed 但回答是「本轮已完成：…」而不是回答问题（RUN-330b654f71bc）。

### 修复
- 意图分类补充 是不是 / 是否 / 会不会 / 算不算 / 正常吗 / 高吗，这类问句正确归为 knowledge_question；
- Real 模式在 knowledge_question 下只向模型暴露 search_knowledge 与 
espond 两个工具；
- 系统提示明确：知识问答不得建任务/发通知/提复核/反问，回答要直接针对问题，不汇报执行动作；
- 若模型仍调用其他工具，编排器软拒绝（TOOL_NOT_ALLOWED，只记轨迹、不产生副作用），
  并提示直接回答；下一轮仍可正常 respond。

### 回归（新增 2 项，共 7 项自主决策测试）
- 「血糖 9.8 是不是太高」→ knowledge_question；
- 工具清单只含 search/respond；模型强行调用 create_task/notification/review 时被跳过，
  任务/通知/复核均为 0，run completed，回答包含实际答案。

全量 pytest 418 passed，Mock 场景 33/33 PASS。真实模型待 B 复验。

## 10. 追加：已有任务复用硬约束（A-REAL-AUTONOMY-03，2026-11-08）

### 真实表现（B 复验）
患者 B 已有「核实近3天服药」pending 任务，真实模型仍 `create_task` 新建同类任务；
A/B/C/D 四状态的基础动作几乎一致，只有高风险 D 多了一次人工复核。

### 修复
- Real 模式在 `create_task` 执行前做服务端检查：患者已有 pending/missed 任务且
  （同 `task_type` 或同 `event_id`）时，软拒绝 `DUPLICATE_TASK`，返回已有任务 ID 并提示
  `update_task` 或说明覆盖；不产生任务、不写库；
- 该拒绝可被后续 `update_task` 纠正，run 记 completed + `warnings`；
- 提示词增加"已有同类任务必须复用"与按状态选择下一步的明确引导。

### 回归（新增 2 项，自主决策共 9 项）
- 已有同类任务 → `create_task` 被 `DUPLICATE_TASK` 跳过 → `update_task` 成功，
  任务数仍为 1、版本递增；
- 不同 `task_type` 的合法新任务仍可创建。

全量 `pytest` 420 passed，Mock 场景 33/33 PASS。真实模型待 B 定向复验患者 B 场景。

## 11. 追加：事件级可覆盖任务 + 拒后强制复用（A-REAL-AUTONOMY-04，2026-11-08）

### 真实表现（B 复验 759dcf8）
`DUPLICATE_TASK` 已能拦住重复建任务，但模型被拒后仍不 `update_task`，
改去建其他任务 + `ask_user`，最终 `waiting_user`、任务数 1→2。

### 修复
1. **上下文标注**：`_state_brief` 对每个 open 事件计算"已有可覆盖任务"
   （同 `event_id`，或按事件代码与任务类型的相关性映射），直接给出任务 ID/类型/标题/到期时间；
2. **拒后强制复用**：`create_task` 被 `DUPLICATE_TASK` 拒绝后，下一轮**只向模型暴露**
   `update_task / respond / list_tasks`，并追加系统提示"只能调整该任务或说明覆盖"；
   `update_task` 成功后解除限制。

### 回归（新增 2 项，自主决策共 11 项）
- 事件上下文包含"已有可覆盖任务"及任务 ID；
- 被拒后第二轮工具清单不含 `create_task`，模型 `update_task` 成功，任务数保持 1。

全量 `pytest` 422 passed，Mock 场景 33/33 PASS。真实模型待 B 复验患者 B 场景。

## 12. 追加：Mock 知识问答证据一致性（C-REG-KQ-01，2026-11-08）

### 现象（C 的浏览器回归）
Mock 模式下问「XQZ-999 生物标志物是什么」：真实 `search_knowledge` 因实体不匹配返回 0 命中，
但 Mock 规划器用规划阶段未过滤的通用片段生成了引用 KD-001 的回答，run 仍完成。
即"计划证据"与"实际检索结果"不一致。

### 根因
实体相关性过滤原先只在 `tools._search_knowledge` 中执行；`planner.build_knowledge_plan`
使用调用方传入的未过滤 hits 生成 respond 与 citations。

### 修复
- 把 `filter_relevant_hits` 下沉到 `knowledge/search.py`，工具与规划器共用；
- `build_knowledge_plan` 入口先过滤 hits，再决定"有证据回答"或"无证据兜底"；
- `_build_mock_plan` 在调用 `record_evidence` **之前**过滤：未知实体不再持久化证据
  （C 复验发现的残留：首轮修复只作用于规划，未作用于证据落库）；
- `tools._filter_relevant_hits` 保留为薄封装，既有测试不受影响。

### 回归（新增 3 项）
- 未知实体 → evidence 为空、`NO_EVIDENCE` 拒绝、回答为"没有足够资料"，不出现在知识片段引用；
- 未知实体 → `evidence_items` 表中该 run 为 0 行；
- 正常知识问题 → 仍有证据并给出基于知识库的回答。

全量 `pytest` 426 passed，Mock 场景 33/33 PASS。
