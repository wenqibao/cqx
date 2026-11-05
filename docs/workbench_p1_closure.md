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

## 7. A-REAL-01 否定式边界被误判（2026-11-05 追加）

### 复现
真实 R02（RUN-e6ac66424fa8）：模型创建任务时写"本任务仅为数据采集，不含用药调整建议。"，
被 gate.check_text(..., generated=True) 以 CHANGE_MEDICATION 拒绝，两次 create_task 均失败，
任务数 0、run failed（人工复核与检索本身成功）。

### 根因
免责否定词表只有"不包含/不涉及/不得"等，没有"不含/不包括"；"用药调整"命中
(剂量|药量|药)[^，。；]{0,4}(调整|改|换|停) 规则，而命中位置前的分句"不含用"未被识别为否定。

### 修复
- DISCLAIMER_MARKERS 增加"不含""不包括""无须"；
- 否定仍只作用于**当前分句**，因此混合文本照旧拦截：
  不含诊断，但建议你停药。 → CHANGE_MEDICATION；
  本系统不提供诊断，但我现在诊断为糖尿病。 → DIAGNOSIS。
- 未删除任何关键词、未放宽阈值、未改患者输入路径的严格性。

### 回归
	ests/integration/test_disclaimer_generated_text.py（17 项）：5 条否定边界放行、
4 条真实指令/混合文本拦截、带声明的 create_task 通过、带"建议停药"的任务被拒、
R02 式脚本模型（检索→人工复核→带声明任务）completed 且任务/复核真实落库。

## 8. 验收脚本 P2（2026-11-05 追加）

| 问题 | 修复 |
| --- | --- |
| prepare 在干净目录未先建 .tmp/ | 入口即 mkdir(parents=True, exist_ok=True) |
| 账本硬编码 6 次触发 / 18 次 HTTP | 改为 ACCEPTANCE_TRIGGER_LIMIT（默认 5）/ ACCEPTANCE_REQUEST_LIMIT（默认 16），旧账本自动补齐限额字段 |
| preflight 访问 P001 在新库 404 | 改为使用本场景刚创建的 DS-R01 状态接口 |

回归：	ests/unit/test_acceptance_budget_limits.py（4 项）覆盖默认值、环境变量覆盖、
触发上限生效、旧账本补字段；并更新既有的账本重启测试。

## 9. A-REAL-02 同分句安全绕过（2026-11-05 追加，P0）

### 复现
以下三条在 generated=True 与患者输入路径都被判为允许（应拒绝）：

`	ext
本任务不含用药调整建议而是建议停药
不包括改药方案只是建议把药停了
无须调整用药建议停药观察一周
`

### 根因
_is_disclaimer() 只检查命中位置左侧窗口里是否出现任意免责标记，没有识别
"免责之后同一分句里又出现真实指令"的情况；无标点时窗口包含"不含"就整句放行。

### 修复
在窗口内取**最后一个**免责标记，检查其后的文字：
- 出现转折词（而是/只是/反而/不过/却/仍然/还是）→ 免责不覆盖命中位置；
- 以指令引导词结尾（建议/请/应/需要/可以/要/立即/马上/尽快/务必/宜）→ 同样不覆盖。
其余情况维持原语义（R02 的"不含用药调整建议"仍放行）。未删除任何关键词、未放宽阈值，
两条路径（generated / 患者输入）共用同一判定。

### 回归
- 	ests/integration/test_disclaimer_generated_text.py：5 条绕过文本双路径均拒绝；
  create_task/
espond/create_notification 三个带自由文本的工具都不能绕过；
  4 条否定边界仍放行；删除了恒真断言。
- 探针结果（真实仓库）：9/9 预期一致。

## 10. 真实模型语义项（2026-11-05 追加）

| 场景 | 处理 |
| --- | --- |
| B12 偏好写成 kind=note | 工具 schema 为 save_preference 补 kind/value/source 描述与枚举（时间偏好必须 preferred_time_window、值用 HH:MM）；系统提示同步强调 |
| B17 无证据却进入 waiting_user | 真实路径新增判定：知识问答在没有任何证据时强制 NO_EVIDENCE，run 记 ailed，不允许用追问代替 |
| B06/07/08/10/11/16/20 的被拒动作 | 需按 700dfc1 重跑后查看各自 
ejections 文本；本轮已修复同类"免责声明误判"，其余待真实复验再定位 |
| B19 无可完成任务 | 场景前置任务与工具选择契约问题，需 B 提供该 run 的 tool_calls 才能定责，本轮未改 |

## 11. A-HARNESS-02 旧账本未收紧（2026-11-05 追加）

AcceptanceBudget 读取旧账本（写死 6/18）时会沿用旧上限。改为取
min(持久化上限, 当前批准上限) 并立即落盘，收紧后重启仍生效。
回归 	ests/unit/test_acceptance_budget_limits.py 增加旧 6/18 账本被压到 5/16 的用例。
