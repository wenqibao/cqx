# 工作台 P1 收口记录（A-WB-01/02/03）

日期：2026-11-05　｜　作者：A　｜　基线：`ec9bd60`（PR #3 head）
分支：`bugfix/workbench-p1-closure`　｜　模式：全部离线（Mock/Stub，无厂商调用）

> 结论：三项 P1 已完成离线修复与回归；**真实 DeepSeek 效果仍待 B 在新预算内复验**，
> 本文不声明真实链路通过。

## 1. A-WB-02 血压误去重（已修复）

### 复现
同一患者、同一分钟（T 与 T+30s）依次写入 `120/80`、`130/85`。

- 修复前：第二条 `duplicate=true`，ID 与第一条相同，payload 仍是 `120/80`，库里只有 1 条。
- 修复后：两条都保存，ID 不同，第二条 payload 为 `130/85`，查询返回 2 条。

### 根因
`backend/app/services/records.py` 的去重键由 `patient_id | kind | recorded_at 分钟 | value | payload.text`
组成。血压的 `value` 恒为 `None`，真正的观察值在 `payload.systolic/diastolic`，未进入键，
于是同一分钟内不同血压生成同一个键，被 `INSERT OR IGNORE` 合并。

### 修复
- 新增 `canonical_observation()`：把"这次观察到了什么"归一化成字符串
  （`systolic/diastolic` 数值规范化、`symptom` 文本折叠空白、`medication_name`/`tags` 归一）。
- 去重键改为 `short_hash(patient|kind|分钟|canonical_observation)`；数值 `120`、`120.0`、`"120"`
  归一为同一值。
- **升级兼容**：同时计算旧键；插入前若旧键命中且观察值一致，仍判为重复，
  因此升级后重试旧记录不会插出第二条。旧行不删除、不改写、不需要迁移。
- 导入接口 `json_rows` 支持嵌套 `payload`（与单条 API 语义一致），CSV 扁平字段继续可用。

### 回归
`tests/unit/test_records_bp_dedupe.py`（9 项）：同分钟同值去重、同分钟异值不去重、
数值形式归一、跨患者隔离、旧键兼容、症状文本区分、其他类型（血糖/步数/体重）不回退、
嵌套 payload 导入。

## 2. A-WB-01 真实模型只读不行动（已加固，待 B 复验）

### 复现
`RUN-04a267842b5d`：三轮只调用 `search_knowledge`/`query_history`/`get_preferences`，
未产生任务、提问或复核，运行被正确判为 `failed`（该失败判定保留，未改成 completed）。

### 修复（只改上下文与停止条件，不加轮数、不硬编码任务）
- 系统提示补充"完成标准"：处理健康事件必须产生 `create_task`/`ask_user`/`request_human_review`
  之一；只读取不算完成；检索最多 2 次。
- 只读轮之后追加一条 `system` 消息推下一步（每条运行最多 1 次），并在轨迹里记 `progress_nudge`，
  便于解释"为什么模型下一轮开始行动"。
- `search_knowledge` 超过 2 次不再执行，返回 `NO_PROGRESS` 工具结果（标记为 `skipped`，
  不计入拒绝、不产生副作用），迫使模型基于已有证据行动或说明无法继续。
- 事件收尾保持原规则：只有 `create_task`/`update_task`/`request_human_review` 成功才标记 handled。

### 回归
`tests/integration/test_real_agent_progress.py`（4 项，受控脚本模型，不调用厂商）：
只读→提示→执行任务并完成；只读到底 → `failed` + `POSTCHECK_MISMATCH` + 事件仍 open；
检索封顶 2 次且第 3 次记 `NO_PROGRESS`；提示确实出现在下一轮请求里。

### 限制
真实模型是否因此修复，必须由 B 在真实端点复验；本轮离线通过**不能**关闭该项真实失败。

## 3. A-WB-03 审计计数口径（复核 + 补强）

- 复核 PR #3 的 `forbidden_action_count()`：按成功 `tool_result` 反查对应 `tool_call` 参数，
  统计"越权工具或动作文本"，不再把 `decision='reject'` 当执行。
- 新增两个可交叉核查字段（`GET /api/system/audit`，仅为增量）：
  - `blocked_total`：拒绝/拦截条数（会随拦截增加）；
  - `checked_tool_results`：本次计数覆盖的工具结果条数（证明不是固定返回 0）。
- 回归 `tests/integration/test_audit_counting.py`（5 项）：B24 拦截不抬高执行计数；
  受控夹具注入"成功但越权"的工具结果 → 计数 +1；非白名单工具 → +1；正常运行保持 0；
  接口同时返回两类计数。

## 4. 回归结果（离线，Mock）

```
python -m pytest                                        → 214 passed
python scripts/run_scenarios.py --report evaluation/reports/a-workbench-p1-mock.json
                                                        → 33/33 PASS（llm_mode=mock）
```

## 5. 接口与数据库影响

| 项 | 变化 |
| --- | --- |
| API 路由/参数 | 无变化 |
| `/api/system/audit` 响应 | **仅增量**：新增 `blocked_total`、`checked_tool_results` |
| 数据表结构 | 无变化 |
| 去重键 | 语义扩展（含规范化观察值）；旧键数据保留，靠兼容查询继续幂等 |
| 前端 | 无需同步修改（新增字段可忽略；导入嵌套 payload 为增强） |

## 6. 仍需处理

- 真实模型复验（B，新预算内）：R01/R02/R03/R04 + 安全门槛。
- C 的 `C-DS-01` 长运行超时与 `C-DS-03` 问题回答入口，等契约确认后实施。
