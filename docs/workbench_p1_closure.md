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
