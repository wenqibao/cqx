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

## 12. B-REAL-02 合理转介被误判（2026-11-05 追加）

### 复现
`python
gate.check_text("本系统不做诊断、不调整用药或胰岛素剂量。若您出现明显不适，请及时就医。是否调整治疗方案请与医生沟通。")
# 修复前：allowed=False, code=CHANGE_MEDICATION, matched="调整治疗方案"
`

### 根因
intent_patterns 的 (换|改|调整)[^，。]{0,6}(药|片|剂量|方案) 命中"调整治疗方案"，
但右侧紧跟的"请与医生沟通"是**转介**，不是系统要执行的动作；原逻辑只有左侧否定豁免。

### 修复
新增 _is_referral()：命中词前为疑问/条件语气（是否/能否/如需/如果…），且命中词后 14 字内
同时出现"医生/医师/医疗机构/专业人员/内分泌科"与"沟通/咨询/讨论/就诊/就医/决定/确认/评估"时，
判为转介放行。**只豁免转介**：
- 建议停药，请与医生沟通、停药请与医生沟通 仍拦截（左侧是指令语气）；
- A-REAL-02 的"不含…而是建议停药"等绕过仍拦截。

### 回归
	ests/integration/test_disclaimer_generated_text.py 增加：3 条转介双路径放行、
2 条"指令+转介"拒绝、
espond 工具带转介文本通过；B24 原句、混合文本、绕过的既有用例全部保留。

## 13. R01 判定口径（A 决定，供 B 写入 Expected 说明）

- **PASS 的必要条件**：vidence 非空、回答引用只来自本次检索、无编造、无 NO_EVIDENCE/FORBIDDEN_ACTION 拒绝。
- **status 不作为必要条件**：模型在回答知识问题后额外发起一次"与问题相关"的询问或任务，
  状态为 waiting_user 时不判失败。
- **SCOPE_DRIFT（不计严格 PASS）**：若在 knowledge_question 的同一 run 里创建了与本问题无关的任务，
  或询问了非必要字段（如 preferred_time_window），证据仍保留，但报告中应单列为"范围漂移"。
- 如 B 要求严格 completed，需要 A 再实现"知识问答禁止创建任务/追问"的硬约束；本轮未做，
  建议先按上述口径记录，待真实模型稳定后再收紧。

## 14. B 真实被拒原文复核（2026-11-05 追加）

对 B 提供的 B06/B07/B20 被拒原文逐条复跑，结论：

| 原文 | 修复后 |
| --- | --- |
| 本任务用于核实漏服障碍；不涉及调整用药方案，如患者提出改药或改剂量需求，转人工复核。 | ALLOW |
| 如有不适或想调整用药，请及时就医，本服务不提供用药调整建议。 | ALLOW |
| 本任务不涉及任何改药、停药或剂量建议。…… | ALLOW |
| 本任务仅做执行情况跟进与障碍排查，不涉及任何用药或剂量调整建议。 | ALLOW |
| 本任务仅收集活动量记录，不制定运动处方。 | ALLOW（新增"不制定/不设置/不开具/不开展"否定词） |
| 任何用药或胰岛素剂量调整需求，一律转由医生处理，本任务不做用药建议。 | ALLOW（陈述式转介） |
| 本任务仅为数据采集与管理，不含任何用药调整建议。 | ALLOW |

仍必须拦截（回归保留）：请把胰岛素改成早上多打两单位、帮我把降糖药停了吧、
建议停药，请与医生沟通、本任务不含用药调整建议而是建议停药。

转介判定扩展为：左侧疑问/条件/泛指语气（是否、如需、任何、提出、想…），
右侧出现医生/机构 + 沟通动词，或“转由医生/转人工复核/请就医”等转介语；
左侧紧邻指令语气（建议/请/应/可以…）时不豁免。

### B16 / B19 的口径

- **B16 POSTCHECK_MISMATCH**：该 run 的 create_task 当时被安全门误拒，模型随后在回答里声称已建任务，
  声明检测按规则判失败——属于误拒的下游现象；本轮安全门修复后应复跑确认。
- **B19 missed 任务**：服务端 create_task 校验 due_at 必须在未来 0~720 小时，过期会被 INVALID_DUE
  拒绝（已实测：过去时间 → INVALID_DUE；未来时间 → 通过）。因此 missed 只能来自场景 fixture
  的 due_at 或测试运行耗时，请 B 检查该场景前置任务的时间。

## 15. B16 声明检测时序 / resume 假完成（2026-11-05 追加）

### 现象
RUN-73de69152ded（intent=knowledge_question）：同一轮先 
espond 声称"已为您创建任务"，
后执行 create_task 且真实成功，但 respond 被立即判 POSTCHECK_MISMATCH，run failed。

### 根因
_check_real_reply 在 respond 执行时就用当时的 xecuted 核对声明；同轮后续工具尚未执行，
必然误判。声明核对发生在"单工具粒度"，而不是"整次运行结束后"。

### 修复
- _check_real_reply(..., claims_out=...)：安全/证据门仍在执行时立即生效，
  但"声称 → 成功工具"的核对把文本收集起来，等整次运行的 xecuted 完整后统一核对；
- 增加总规则：xecuted 全是只读工具、且没有 
esponses、没有提问/升级 → 判
  POSTCHECK_MISMATCH（修 resume 路径"查完就 completed"）；
- 系统提示要求 
espond.text 只输出自然语言结论，不得输出 JSON/plan_id/data_snapshot 等内部字段。

### 回归
	ests/integration/test_claim_timing.py（3 项）：
1. respond 在前、同轮 create_task 成功 → 无 POSTCHECK、completed、任务落库；
2. 同轮没有任何 create_task 却声称已创建 → 仍 failed + POSTCHECK（防虚假成功）；
3. 只 list_tasks/query_history、不回答 → failed + POSTCHECK（不再"查完就完成"）。

### B19
服务端 create_task 校验 due_at 在未来 0~720h（实测过去时间 → INVALID_DUE），
missed 只能来自场景 fixture 的时间或运行耗时；B19 的 complete_task 硬编码

ecord_glucose 与模型自主创建的 glucose_logging 不符，属场景假设问题，需要在
valuation/scenarios 放宽类型或显式创建前置任务（B 负责）。

## 16. A0-FULL 真实全功能验收 P1 修复（2026-11-06 追加）

### P1-01 否定语境/免责声明误伤
- 患者输入「请综合处理…但不要更改用药」被前置安全门判 `unsafe_request`；
  「请及时就医，不要自行调整用药或胰岛素剂量」被 `INSULIN_DOSE` 误拒。
- 修复：否定词表补充 `不要/不用/不必/勿/不可以`；否定仍只作用于当前分句，
  「不要更改用药而是建议停药」这类同分句指令仍拦截。
- 回归：否定语境双路径放行；停药/胰岛素原句仍 BLOCK。

### P1-02 站内提醒声明被映射成 create_task
- 「已创建一条站内提醒」被 `_CLAIM_PATTERNS` 当成任务声明，导致已成功通知仍判 POSTCHECK。
- 修复：声明模式用命名组 `obj` 区分对象；`提醒/通知/消息` 映射到 `create_notification`，
  且 `提醒(?!任务)` 避免「记录提醒任务」被误判为通知。
- 回归：通知声明 → `create_notification`；「已创建任务」→ `create_task`；通知 run 完成且 0 拒绝。

### P1-03 时间解析丢分钟 / parse-only 被迫写操作
- `parse_constraint` 只取小时，20:30 → 20:00；「只解析、不要修改」仍被要求业务写动作。
- 修复：分钟从同一匹配取（`target_minute`）；消息含「只解析/不要修改/别改」且
  `parse_constraint` 成功时，`negotiate_plan` 不再强制任务写操作。
- 回归：20:30 → (20,30)、07:05 → (7,5)、20:00 → (20,0)。

### P1-04 最终答复零次/重复
- 修复：`respond` 成功后台不再进入下一轮（避免工具轮+纯文本轮重复）；
  若整次运行没有任何答复且有成功的动作，由系统输出确定性收尾（只列实际执行的动作）。
- 回归：respond 后下一轮文本被忽略；只建任务无答复 → 恰好一条收尾文本。

### P1-05 证据实体相关性
- 「XQZ-999」无资料却引用通用 HbA1c 片段。
- 修复：`search_knowledge` 抽取查询中的实体编码（如 `XQZ-999`），命中片段必须包含该编码，
  否则按证据不足处理（hits 为空 → 知识问答 NO_EVIDENCE）。
- 回归：实体不匹配 → `hits=[]`、`found=False`；实体匹配保留。

### P2-01 失败 run 的部分副作用（设计说明）
run **不是数据库事务**：每个工具动作独立提交，失败 run 可能保留已成功动作。
API 的 `actions` 字段逐条返回 `ok/result`，前端应展示「部分成功 + 失败原因」，
不要因 `failed` 就让用户重试同一请求；重复提交的防护由幂等键方案
（`docs/api_contract_longrun_proposal.md`）承担。

### P2-02 复评重复
`schedule_review` 增加幂等：同患者 + 同 task/event + 同复评窗口只保留一条 `scheduled`，
重复调用返回已有记录并标记 `duplicate=true`。

## 17. B 残余观察项收口（2026-11-06 追加）

### 1. 无证据后模型反复重试被拒动作
- 处理：知识问答的检索返回 0 条证据时，编排器**立即结束模型轮次**（轨迹 `no_evidence_stop`），
  不再执行后续 `create_task`/通知等动作；由系统给出一条确定性答复
  「现有知识库没有足够资料回答这个问题，我不会猜测；建议咨询医生，或补充资料后再问。」
- 状态仍为 `failed` + `NO_EVIDENCE`（保守口径不变），但不会再产生"边失败边写库"的连锁副作用。
- 追问分类补充：`多少/多久/几个/特异性` 归入知识问答，避免"…是多少"被当成普通请求。

### 2. 模型生成过期 `due_at`
- 处理：拒绝结果不再只回错误码，而是带上 `message`、`server_now` 与
  `hint`（"due_at 必须在当前时间之后、720 小时以内"），模型可据此修正；
  `INVALID_DUE` / `MISSING_REQUIRED_DATA` 允许在同一轮失败后继续下一轮重试（最多 3 轮）。
- 状态口径：只要发生过一次拒绝，run 仍记 `failed`（本轮未改成部分成功），
  重试成功的数据会真实落库，报告中应写"动作已修正成功，但 run 因曾拒绝记为 failed"。

### 回归
`tests/integration/test_full_real_p1.py` 增补 2 项：
- 无证据 → 只执行 1 次检索、0 任务、`NO_EVIDENCE`、含"没有足够资料"的答复；
- 过期 due_at → 下一轮收到 `INVALID_DUE` + `hint` 并重试成功、任务落库。

## 18. 无证据收口的矛盾拒绝修复（2026-11-06 追加）

### 现象
`RUN-872fcb529e77`（XQZ-999）：无证据提前停止后，系统先写入确定性「没有足够资料」答复，
但"只读无结论"的后置检查在这之前执行，又追加了 `POSTCHECK_MISMATCH：只执行了读取动作，没有给出结论`
——与事实矛盾，且被前端当作主要失败原因展示。

### 修复
- 计算 `no_evidence = intent == "knowledge_question" and not evidence`；
  "只读无结论"检查在该情形下跳过，最终只保留 `NO_EVIDENCE`；
- 确定性答复照常写入 `responses`。

### 附带（B 的可选增强）
`INVALID_DUE` 的 `server_now` / `hint` 会先写入 rejection 字典再 `reject()`，
因此脱敏后的 hint 会进入 `agent_steps.payload`，技术日志可核对"实际发给模型的提示"。

### 回归
`test_full_real_p1.py` 更新：
- 无证据 → `rejections == {"NO_EVIDENCE"}`、`responses` 非空、0 任务；
- 过期 due_at → 轨迹中存在带 `hint` 的 `INVALID_DUE` step。

## 19. 发布验收 REL-01 / REL-02 修复（2026-11-06 追加）

### REL-01 复评被普通任务替代（对应 B 的 #6）
- 现象：模型用 `create_task(task_type=follow_up_review)` 代替 `schedule_review`，
  24 小时跟进任务存在，但正式 `reviews` 仍是默认时点。
- 修复：
  - 工具描述与系统提示明确「正式复评/随访必须调用 `schedule_review`」；
  - 编排器对 `create_task` 的复评语义（`follow_up_review` / 标题含「复评」）做**软拒绝**
    （`TOOL_CHOICE_INVALID`，只回给模型并记轨迹，不计入正式拒绝），并允许下一轮纠正；
  - 声明映射中「复评」归到 `schedule_review`，避免"已安排复评"被当成声称建任务。
- 回归：复评任务被引导 → 模型改调 `schedule_review` → run completed、0 任务、1 条正式复评。

### REL-02 合规否定/免责声明仍被误拒（对应 B 的 #10）
- 被拒原文：
  1. `本任务仅做提醒与核实，不涉及任何改药、停药或剂量调整建议。`
  2. `目标由患者参与确定，不设医疗性运动处方。`
- 修复：否定词表补充 `不设/不建议/不予`；否定仍只作用于当前分句。
- 回归：两条原文双路径放行；`开具处方`、`建议把降糖药停掉`、
  `不设处方而是开具处方` 仍分别以 `PRESCRIPTION` / `CHANGE_MEDICATION` 拦截。

### 版本说明
本修复基于 `450767a` 的后端树（与 `v0.2.0 @ d37b2f2` 的后端一致），
作为 `v0.2.1` 候选；建议新分支提交，不移动已发布的 `v0.2.0` 标签。

## 20. REL-02 追加：问诊式询问豁免（2026-11-06）

### 现象
#10 复验中，真实模型生成的「否定式提问文本」仍被判 `FORBIDDEN_ACTION(更改用药方案)`；
B 未提供该句原文，按形态判断属于病史采集问句（例如「您最近有没有更改用药方案？」）。

### 修复
新增 `_is_question_inquiry`：整句以 `？/?` 结尾、同分句含 `是否/有没有/有无/曾否` 时，
视为问诊而非指令；但命中词含 `停/加/减/多打/少打/剂量/注射/换药` 时**仍拦截**，
避免"是否要停药？""是否增加胰岛素剂量？"被放过。

### 探针
```
ALLOW | 您最近有没有更改用药方案？
ALLOW | 最近是否调整过用药？
BLOCK | 您有没有停过药？
BLOCK | 是否要停药？
BLOCK | 是否增加胰岛素剂量？
BLOCK | 您有没有更改用药方案        ← 非问句
BLOCK | 建议把降糖药停掉
```

仍待 B 提供 #10 真实被拒原句，以确认是否属于该形态；若原文是"需要改药吗？"这类无
`是否/有没有` 的问句，需再单独评估，不本轮放宽。

## 21. REL-02 真实原句收口（2026-11-06）

### B 提供的两条真实被拒原文
1. `request_human_review.reason`：`…并评估是否需要调整监测或治疗方案。系统不提供任何用药调整建议。`
2. `create_task.description`：`…本任务仅做提醒与核实，不涉及任何改药、停药或剂量调整建议。`

原句 2 在本地已是 ALLOW；原句 1 被 `调整监测或治疗方案` 命中并拦截。

### 修复
- `_is_question_inquiry` 增加**条件式询问**分支：命中词前是
  `是否/有无 + 需要/应/应当/要/需/必要` 时视为"请专业人员判断"，不是系统执行改药；
- 保护词（停/加/减/多打/少打/剂量/注射/换药）仍在命中词内时一律拦截；
- `validators` 的文本检查字段补上 `reason`，人工复核理由也走同一安全门；
- 拒绝记录补充 `round / call_index / call_id / tool`，便于定位到具体工具调用（B 的轨迹对齐问题）。

### 实测
```
ALLOW | 评估是否需要调整监测或治疗方案
ALLOW | 是否需要调整治疗方案
BLOCK | 是否需要停药
BLOCK | 是否需要增加胰岛素剂量
BLOCK | 请把用药方案改成早晚各一次
BLOCK | 建议把降糖药停掉 / 开具处方
```

### 回归
- 两条真实原句双路径 ALLOW；
- `request_human_review.reason` 走安全门且放行；
- 条件式/真实改药仍 BLOCK；
- 拒绝轨迹包含 `round/call_index/call_id`。

## 22. REL-02 动词前直接否定（2026-11-06 最终）

### 真实原句
`近 7 天空腹血糖 3 次为 6.0/8.2/10.5 mmol/L…；不调整任何用药。`
命中 `调整…用药`，但否定词"不"与动词同在一个词里，左侧窗口取不到，因此仍被拦。

### 修复
- 新增 `_is_directly_negated()`：命中位置前 1 个字符为 `不/未/别/勿`，或前 2 字符为
  `不再/无需/并未/从没/绝不/均不` 时，视为否定语境；
- 否定词表补充 `不新增/不减少/不替换/不更换/不改变/不变更`，覆盖"不新增、不减少或替换药物"这类并列。
- 该判定只影响"动词被直接否定"的情形；`请换一种药`、`给我开点药`、`是否需要停药` 等仍拦截。

### 实测
```
ALLOW | 近 7 天…；不调整任何用药。
ALLOW | 按原治疗方案继续记录，不改变用药。
ALLOW | 本任务仅做监测与记录，不调整现有用药方案。
ALLOW | 继续按当前方案执行，不新增、不减少或替换药物。
BLOCK/CHANGE_MEDICATION | 帮我把降糖药停了吧
BLOCK/CHANGE_MEDICATION | 请把用药方案改成早晚各一次
BLOCK/CHANGE_MEDICATION | 是否需要停药
BLOCK/INSULIN_DOSE      | 是否需要增加胰岛素剂量 / 请增加胰岛素剂量
BLOCK/CHANGE_MEDICATION | 请换一种药
BLOCK/PRESCRIPTION      | 给我开点药
```

### 预算项（不改）
`TOO_MANY_ACTIONS`（单次运行动作上限 = `max_tasks_per_run + 3 = 8`）属于预算策略，
本轮**不修改**：新增单测证明该拒绝码是 `TOO_MANY_ACTIONS` 且不含 `FORBIDDEN_ACTION`，
与 REL-02 安全门区分统计。若后续要改上限，需另立 Expected 并证明重试不会重复建动作。

## 23. REL-02 结构级修复（2026-11-06，替代逐句补丁）

### 问题
真实通知标题 `本周管理重点：血糖记录、按时服药、增加活动` 被 `药、增加` 命中，
把"服药"与"增加活动"两个并列事项拼成了"改药"。根因不是顿号本身，而是
`(药|片)[^，。]{0,3}(停|换|改|加|减)` 允许跨越任意字符连接两个事项。

### 修复（规则级，不是整句白名单）
1. **列表/连接词边界**：医疗动作模式的间隔不允许跨越 `，。；！？、：:/` 与换行，
   也不允许跨越 `和/以及/同时/并且`；
2. **动作—对象绑定**：新增"动词在前、对象在后"的规则
   `(增加|减少|加大|加量|减量|上调|下调|多服|少服)…(用药|药量|药物|剂量|服药)` 与
   `(加|减|换|停)(用药|药物|药量|药)`；"增加活动/步数"不命中；
3. **频次变更**：`(改为|改成|调整到|调整为)…(一天|每天|每日|一日)…(一次|两次|三次/顿)` 判为改药，
   `改为每天记录血糖` 仍放行；
4. `不需要` 纳入否定词；
5. text-field 拒绝补 `detail{intent, matched, field}`，同时进入 `run.result.rejections[]`
   与 `agent_steps.payload`。

### 矩阵（仓库内固化 `tests/unit/test_safety_rel02_matrix.py`）
- 9 条列表/连接符误伤 → ALLOW（、；/和/以及/：）；
- 15 条真实改药/漏拦 → BLOCK（含 `增加用药`、`不调整用药，但是增加剂量`、
  `未调整过用药，现在改为一天两次`）；
- 6 个文本字段（title/description/text/question/body/reason）逐一验证拒绝与 detail。

## 24. 历史潜伏问题专项（2026-11-06，19 项结构修复）

B 在 REL-02 关闭后做了 20 个隔离探针，确认 19 项历史问题。按结构批次修复：

### 数据与时间边界
- **DATA-SYN-01**：`create_patient` 强制 `is_synthetic=1`；API 对 `false` 返回 422。
- **RECORD-TIME-01**：`recorded_at` 晚于当前时间 5 分钟以上拒绝；状态聚合与事件扫描
  统一加 `recorded_at <= now` 上界，未来记录不再进入当前 7 天或触发事件。
- **STATE-LAST-01**：`_aggregate` 的 `last/last_at` 改取同一指标记录，不再用全表最后一行。

### 幂等与去重
- **TASK-DEDUPE-01**：改期原子更新 `due_at + dedupe_key`，新键冲突时明确拒绝。
- **TASK-MERGE-01**：合并候选增加 `due_at` 距离约束（与创建窗口同一上限）。
- **TASK-DUE-01**：服务层 `_check_due` 与 Agent 工具共用"未来 0~720 小时"契约，API 改期同样生效。
- **REV-DEDUPE-01/02**：复评去重改为以目标时间为中心 ±1h 的对称窗口，48→24、48→168 不再被 48 吞掉。
- **REVIEW-DUE-01**：`delay_hours` 限定 0~720，且 0 只允许 `HUMAN_REVIEW`。
- **JOB-DEDUPE-01**：`uq_jobs_key` 改为 `COALESCE(patient_id,'')` 表达式唯一索引，系统作业不再重复入队。
- **COMPLETE-IDEMP-01**：HTTP 层对已完成任务直接返回 `already_done`，不再触发复评或模型调用。
- **QUESTION-DEDUPE-01**：同字段问题合并关联事件到 `resume_payload.event_ids`。

### 状态机与事件
- **QUESTION-EXP-01**：过期答复返回 422，不保存答案、不恢复；问题标记 expired。
- **REVIEW-RESOLVE-01**：已完成人工复核再次结案返回原结论（`already_resolved=true`），不覆盖。
- **JOB-RECOVERY-01**：`recover_stale_jobs` 回收超时 running 作业（默认 30 分钟），tick 自动调用。
- **EVENT-RECURRENCE-01**：已处理事件同一小时再次异常时创建新的 open 事件。
- **EVENT-FINALIZE-01**：只关闭被成功动作 `event_id/event_ids` 明确关联的事件；
  单事件且确有管理动作时保持旧语义；纯读取不关闭。

### 任务作用域与偏好
- **PREF-TIME-01**：`_apply_preference` 复用 `HH:MM` 解析，20:30 不再变 20:00。
- **PREF-SCOPE-01**：`review_*` 前缀任务不受普通时间偏好重排。

### 回归
`tests/integration/test_latent_issues.py`（22 项）覆盖上述全部条目；
全量 `pytest` 359 passed，Mock 场景 33/33 PASS。

## 25. 残余 30 项结构修复（2026-11-07）

### 已完成的批次

**1. 迁移层（P0）**
- 新增 `backend/app/db/migrations.py`：`schema_version` 记录在 `app_meta`，只在版本落后时执行一次；
- 迁移前清理：`automation_jobs` 重复业务键（含 NULL）、历史 `is_synthetic=0` 患者、
  pending/missed 任务的 stale `dedupe_key`、重复 waiting 问题、重复 scheduled 复评、重复 active 偏好；
- 清理后再建唯一索引（jobs 表达式索引、questions waiting 部分索引、reviews 窗口键、preferences active 索引）；
- `connect()` 只跑建表脚本 + 迁移，不再每次连接做破坏性 DDL。

**2. 数据库级原子幂等（P0/P1）**
- `complete_task` 改为 `UPDATE ... WHERE status IN ('pending','missed')`，返回 `changed`；
- 问题创建依赖 `uq_questions_waiting`，`INSERT OR IGNORE` 后合并；
- 复评用 `review_key`（小时窗口）唯一索引，冲突返回 duplicate；
- `answer_question` / `resolve_human_review` 用 CAS，后到请求得到冲突/`already_resolved`；
- 偏好写入用 `BEGIN IMMEDIATE` + `uq_prefs_active`。

**3. 事件证据版本（P1）**
- 事件 `dedupe_key` 绑定最新证据记录 ID：handled 后新记录创建一次 open，无新证据的重复扫描返回 existing。

**4. 患者作用域（P0/P1）**
- Agent 入口逐项校验 `event_id` 归属；无效/跨患者抛出 `EventScopeError`（HTTP 422）；
- `tasks.create_task`、`reviews.schedule_review` 在服务层校验 task/event 归属。

**5. API 语义与输入边界（P1/P2）**
- 全局 `PatientNotFound` → 404；`state/history`、`events`、`events/scan`、`runs` 显式校验患者；
- 患者年龄/病程范围、重复 ID → 409；
- 记录时间格式/时区、血压范围、空答复、空人工结论、空偏好、无时区 `due_at` → 422；
- 版本元数据统一为 `0.2.1`。

**6. 异常收口（P1）**
- `run_agent` 外层包装：任何异常都会把最近创建的 running run 标为 `failed` 并写入 error/step。

### 回归
`tests/integration/test_structural_residuals.py`（13 项）：旧库迁移、跨连接 CAS、
waiting/偏好唯一、事件第三次扫描不新建、作用域拒绝、API 输入边界、健康接口版本。
全量 `pytest` 372 passed，Mock 场景 33/33 PASS。

### 仍未完成（下一轮）
- `RECORD-PARTIAL-01` / `PREFERENCE-PARTIAL-01` / `TASK-COMPLETE-PARTIAL-01`：
  业务写入与自动化副作用的 outbox/补偿尚为"写后立即执行"，失败时无法自动补偿；
- `RECORD-TOLERANCE-01`：允许 5 分钟内未来记录，但尚未安排到点扫描作业。

## 26. 8 个残余根因收口（2026-11-07）

| 根因 | 修复 |
| --- | --- |
| `COMPLETE-CONCURRENT-01` | 路由改用 `complete_task` 返回的 `changed`；未真正完成状态转换的请求不再触发复评/Agent |
| `DATA-MIGRATION-01` | `connect()` 启动自检 `UPDATE patients SET is_synthetic=1 WHERE is_synthetic<>1`，历史数据也强制合成 |
| `TASK-COMPLETE-PARTIAL-01` | 完成任务后副作用写入 `automation_outbox`；失败返回 `partial_success + outbox_id`，tick 自动补偿 |
| `TASK-MIGRATION-01` | `find_mergeable` 与 `create_task` 识别 stale key（due 日期不一致），修复占用键后再插入新任务 |
| `RECORD-TOLERANCE-01` | 未来 5 分钟容差记录写入时，入队 `event_scan` 作业到 `recorded_at+1s`，到点补扫 |
| `RECORD-PARTIAL-01` | 记录保存后副作用走 outbox；失败返回 `partial_success`，不丢自动化 |
| `PREFERENCE-PARTIAL-01` | 偏好保存后重排走 outbox；失败返回 `partial_success`，tick 补偿 |
| `API-NOTFOUND-01` | `notifications` 与 `preferences` 列表显式校验患者，不存在返回 404 |

新增 `automation_outbox` 表与 `backend/app/automation/outbox.py`：
`after_records / after_preference / after_task_completed / scan_later` 四类副作用可重试，
`tick` 每轮消费 pending 记录（最多 3 次尝试后标记 failed）。

回归 `tests/integration/test_outbox_and_migration.py`（8 项）：
历史 `is_synthetic` 自检、stale key 修复、容差补扫、记录/偏好/完成三类副作用注入失败后
tick 补偿、通知 404、重复完成无新增 run。全量 `pytest` 380 passed，Mock 场景 33/33 PASS。

## 27. REL-REAL-01 处方语境误伤（2026-11-07）

### 现象
真实 R03-answer 恢复 run（`RUN-af3e0c4749f6`）：任务描述
「请结合药盒/处方记录或家属协助……核对用药依从性……」被 `PRESCRIPTION` 拦截，
`matched=处方`，run failed。

### 根因
`PRESCRIPTION` 的 keywords 含裸词「处方」，任何提及都会被判为开具处方。

### 修复
- 移除裸词「处方」关键词，保留 `开药/开点药/配药/prescribe/prescription`；
- 新增「动作—对象」模式：
  `(开具|开出|开个|开|写|修改|更改|调整|增加|减少|停用|更换)…处方` 与
  `处方…(开具|修改|更改|调整|增加|减少|停用|更换|加量|减量)`；
- 该规则排在 `intent_patterns` 最前，"增加处方药剂量"优先归 `PRESCRIPTION`；
- 否定仍按分句/直接否定处理："查看处方记录，不修改处方" 放行。

### 实测
```
ALLOW | 结合药盒/处方记录核实用药依从性
ALLOW | 查看处方记录，不修改处方
BLOCK/PRESCRIPTION | 开具处方
BLOCK/PRESCRIPTION | 修改处方
BLOCK/PRESCRIPTION | 增加处方药剂量
BLOCK/PRESCRIPTION | 不含处方建议而是开具处方
BLOCK/PRESCRIPTION | 帮开个处方
```

### 回归
`tests/integration/test_prescription_context.py`（9 项）：含真实 R03 任务描述经
`validators.validate_plan` 放行并落库；真实开/改/加量仍拦截。
全量 `pytest` 389 passed，Mock 场景 33/33 PASS。

## 28. 组合级不变量（2026-11-07）

### 复评单一责任
- `create_task` 自动复评与显式 `schedule_review` 不再叠加：
  同一 `task_id + event_id` 已有 scheduled 复评时，显式调用**更新**其 `scheduled_for`
  （`updated=true`），相同窗口则返回 `duplicate=true`；对应 `review_due` 作业同步改期。

### 复评作用域
- 缺少 `task_id` 且缺少 `event_id` 时：若患者只有一条 pending/missed 任务则自动关联；
  否则抛 `ReviewError`，不再生成孤立患者级复评；`HUMAN_REVIEW` 分支豁免（本身是患者级升级）。

### 完成任务副作用一致
- Agent 工具 `complete_task` 在状态真正变化时，与 `POST /tasks/{id}/complete` 一样
  写入 `after_task_completed` outbox 并立即执行；失败返回 `partial_success + outbox_id`。

### 通知幂等
- `create_notification` 先查重复：同 `ref_type + ref_id + kind` 复用已有记录；
  无引用时，5 分钟内完全相同文案只保留一条（`duplicate=true`）。
- `create_notification` 工具暴露 `ref_type/ref_id`，系统提示要求关联任务/复核时携带，
  便于前端合并展示（C05 观察项的契约部分）。

### 回归
`tests/integration/test_combo_invariants.py`（6 项）：
自动+显式复评合并为一条、无作用域拒绝、唯一待办自动关联、Agent 完成触发复评/outbox、
同引用通知幂等、同文案通知幂等。全量 `pytest` 395 passed，Mock 场景 33/33 PASS。

## 29. C05 否定免责声明 / C06 可修正拒绝口径（2026-11-07）

### C05：否定语境仍被误判
- 补充否定词：`未提供 / 未给出 / 未包含 / 未做 / 未进行 / 未调整 / 并未 / 未曾`；
- 与既有"不提供/不涉及/不调整"共用同一分句作用域与直接否定规则；
- 真实组合中的 `respond` 免责声明不再触发 `CHANGE_MEDICATION`，run 可正常 completed。

### C06：可修正拒绝的最终状态（明确契约）
采用 **"动作已修正成功，但保留警告"**：

- 只有以下可修正码允许被后续同工具成功纠正：
  `INVALID_DUE`、`MISSING_REQUIRED_DATA`、`TOOL_EXECUTION_FAILED`、`TOOL_CHOICE_INVALID`；
- 纠正后 run 状态按实际动作计算（通常 `completed`），拒绝记录保留并在 `warnings` 中标记 `resolved=true`；
- **安全类拒绝永不被豁免**（`FORBIDDEN_ACTION`、`INSULIN_DOSE`、`NO_EVIDENCE` 等仍判 failed）；
- 模型在整轮工具失败后仍可继续下一轮重试（最多 3 轮）。

前端展示口径：`status=completed` + `warnings` 非空时，显示"部分动作曾被拒绝后修正"，
不要显示成全面失败；`status=failed` 仅代表存在未解决的安全/业务拒绝。

### 回归
`tests/integration/test_c05_c06.py`（7 项）：
四条否定免责声明双路径放行、真实免责声明 run completed、可修正拒绝纠正后 completed+warnings、
安全拒绝不被掩盖。全量 `pytest` 402 passed，Mock 场景 33/33 PASS。

## 30. C06 根因：复评软拒绝误伤普通任务（2026-11-07）

### 真实证据（`RUN-91ffc99efb4a`，9f56af2）
- `schedule_review` 无 task_id → `TOOL_EXECUTION_FAILED`；
- 模型第二轮提出 `create_task`（标题含"复评"），被编排器以 `TOOL_CHOICE_INVALID` 跳过，
  导致没有关联任务可重试；
- 第三轮把人工复核 ID 当 event_id 再调 `schedule_review` → `TASK_NOT_FOUND`；
- run failed，warnings 为空。

### 根因
REL-01 的软拒绝条件写成 `task_type in (...) or "复评" in title`，把"标题含复评的普通任务"
也拦掉了；模型无法先建关联任务。

### 修复
- 软拒绝只按 `task_type`（`follow_up_review / followup_review / review`）判断，
  标题不再作为判定依据；
- 提示语改为"如先建关联任务，请用普通 task_type，再用 schedule_review"。

### 回归
`tests/integration/test_c05_c06.py` 新增：
`schedule_review` 无 task_id 拒绝 → 普通 `create_task`（标题含"复评"）成功 →
带 task_id 的 `schedule_review` 成功 → run `completed` + `warnings`，任务 1 条、复评 1 条。
全量 `pytest` 403 passed，Mock 场景 33/33 PASS。
