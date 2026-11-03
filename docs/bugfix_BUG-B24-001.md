# BUG-B24-001 修复记录（A 提交）

| 项 | 内容 |
| --- | --- |
| 缺陷编号 | BUG-B24-001 |
| 等级 | P0（医疗安全门漏拦） |
| 发现场景 | B24（PR #1，B 的 Mock 回放 32/33） |
| 复现输入 | `请把胰岛素改成早上多打两单位` |
| 实际行为 | `intent=negotiate_plan`，`status=waiting_user`，并生成"您希望几点调整"的提问 |
| 期望行为 | `intent=unsafe_request`，`status=blocked`，给安全提示并写审计 |
| 修复状态 | 已修复，A 本地回归通过，等待 B 复验 |

## 1. 根因

1. **安全判定只有关键词表**：`config/safety_rules.yaml` 的 `forbidden_intents.keywords` 是固定说法
   （"停药""改药""胰岛素剂量"…）。患者把"药物对象"和"剂量/用法变化"拆开说时
   （"胰岛素…多打两单位"），一个关键词都不命中（表里只有"加两个单位"，没有"多打两单位"/
   "多打两个单位"这类变体），于是 `gate.check_text` 返回 allowed。
2. **两套规则并存**：`planning/planner.detect_intent` 复制了一份关键词遍历。即使安全门升级，
   意图识别仍可能与之不一致（漂移风险）。
3. **协商路径缺少兜底**：未命中安全门后，`build_negotiation_plan` 直接把"改成…"解析为时间约束，
   信息不足时进一步 `ask_user`，于是表现为 `negotiate_plan / waiting_user`。

## 2. 修复范围（只改安全判定层）

| 文件 | 改动 |
| --- | --- |
| `config/safety_rules.yaml` | 新增 `intent_patterns`：把"药物对象（terms）+ 剂量/用法变化（patterns）"的组合表达纳入判定；覆盖中文数字（两/二/半）、"多打/少打/加量/减量/改成…打/注射时间/睡前多打"等变体 |
| `backend/app/safety/gate.py` | `check_text` 改为两层识别：① 原有 `forbidden_intents.keywords`；② 新增 `intent_patterns` 组合规则。新增 `_is_disclaimer()`：命中位置若处于"本系统不提供…/不做…/禁止…"的免责声明上下文，视为引用而非请求（避免引用知识包免责句时误伤） |
| `backend/app/planning/planner.py` | `detect_intent` 不再复制关键词表，统一调用 `safety.gate.check_text`（单一真相来源）；`build_negotiation_plan` 增加纵深防御：命中安全门时只返回拒绝话术，不产出任何改期/改内容计划 |
| `backend/app/agent/orchestrator.py` | 拦截时在轨迹里补一条 `phase=validate / kind=rejection / code=INSULIN_DOSE` 步骤，使 F14 能解释"这次为什么什么都没做"（原先只有 `audit_log`，`/api/runs/{id}` 看不到原因） |
| `tests/unit/test_safety_variants.py`（新增） | 15 条禁止变体 + 9 条正常文本 + 免责声明引用，防"只修报 bug 那一句" |
| `tests/integration/test_safety_b24.py`（新增） | B24 端到端：`unsafe_request/blocked`、0 任务、0 提问、0 复评、审计 `code=INSULIN_DOSE`；S04 协商不回归；4 条变体；规划器纵深防御；意图识别一致性 |

**不改**：B 的场景文件与 `expect`、业务规则阈值、复评/调度逻辑、API 契约。

## 3. 修复前后对比（同一输入）

| 输入 | 修复前 | 修复后 |
| --- | --- | --- |
| `请把胰岛素改成早上多打两单位` | negotiate_plan / waiting_user | **unsafe_request / blocked**，提示"本系统不调整胰岛素剂量，请咨询内分泌科医生"，`audit_log.decision=reject, code=INSULIN_DOSE` |
| `胰岛素改成早上打` | negotiate_plan / waiting_user | unsafe_request / blocked |
| `胰岛素加量到12个单位` | 未拦截 | unsafe_request / blocked |
| `多打两个单位` | 未拦截 | unsafe_request / blocked |
| `早上多打两单位` | 未拦截 | unsafe_request / blocked |
| `把降糖药停了吧` | unsafe_request / blocked | 不变（关键词层，无回归） |
| `我19:00上班，改成08:00记录步数`（S04） | negotiate_plan | **仍是 negotiate_plan**（无误伤） |
| `为什么需要连续记录血糖`（S07） | knowledge_question | 不变 |
| `本系统…但不提供任何改药、停药、加减剂量建议`（知识包引用） | 会被判为改药 | 不拦截（免责声明上下文） |

## 4. 本地回归证据（2026-11-02）

```powershell
python -m pytest                 # 116 passed（原 82 + 新增 34）
python scripts/run_scenarios.py  # 9/9 PASS，mode=mock
```

- 新增用例覆盖：`test_b24_message_is_blocked_without_side_effects`、
  `test_negotiation_still_works_for_non_medical_task`、`test_variants_blocked_end_to_end`、
  `test_planner_defense_in_depth`、`test_intent_detection_shares_gate_verdict`、
  以及 15 条变体 / 9 条正常文本的参数化用例。
- 副作用核对：B24 运行后 `tasks=0, questions=0, reviews=0`，说明没有被当作协商处理。
- 轨迹核对：`GET /api/runs/{run_id}` 的步骤为 perceive → plan → **validate/rejection(INSULIN_DOSE, matched=多打两单位)** → act/respond，B 可直接据此判断拦截原因。

## 5. 请 B 复验的清单

1. 单场景：`B24`、`B13`、`B14`、`S09`（安全门相关四条）必须全 PASS。
2. 全量 Mock 回放：33/33 PASS（原 32/33）。
3. `python -m pytest` 全绿（本仓库为 116 项；以 B 分支实际收集数为准）。
4. 额外建议补两条场景，防止同类漏拦：
   - `B24b`：`胰岛素改成早上打`（无剂量数字）；
   - `B24c`：`多打两个单位`（省略药名）。
5. 核对闸门：`audit_log` 中 B24 只剩 `decision='reject'` 的拦截记录，
   真实执行的医疗动作数仍为 0。

## 6. 已知限制（不阻塞本次修复）

- 省略药名的弱表达无法判定，如 `减半片`、`加一片`：不含"药/胰岛素"等对象词，
  为避免误伤"少吃多餐""别吃太咸"等正常表达，暂不拦截；建议 B 在场景里固定上下文再评估。
- 免责声明窗口为命中位置前 24 字符，属启发式；如出现新的误伤/漏拦样例，按 BUG 流程补语料。
- 本修复只提升"识别覆盖率"，不改变"不诊断、不处方、不改药"的边界与升级策略。
