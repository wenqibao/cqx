# Codex 执行指令：成员 A——真实 Agent 与工作台 P1 缺陷收口

> 编制日期：2026-11-05，Asia/Shanghai。
> 本文件可直接交给成员 A 的开发代理，不依赖此前聊天上下文。
> 文中的版本是编制时快照。执行前必须重新 fetch、核对实际源码与 PR，不把快照当成永远有效的当前状态。

## 1. 身份、目标与边界

你是“糖衡智管”的成员 A 后端开发代理。仓库：<https://github.com/wenqibao/cqx>。

本轮目标：在已有实现上收口三个 P1——真实模型只读不行动、血压错误去重、审计计数口径；审查已有真实路径修复；交付可供 B 独立验收的确定版本。

平台定位：面向医护健康管理人员的单 Agent 监测与随访监管工作台，仅使用合成病例演示。不能诊断、开处方、改药、停药、调整胰岛素剂量或独立实施医疗处置。高风险仅升级人工专业复核。

本轮不是重新开发 F01–F26，不新增登录/HIS/多个业务角色，不重构前端，不实施云部署。先定位真实缺陷，再最小修复。

## 2. 已核对的版本与真实结果

| 项目 | 编制时状态 |
| --- | --- |
| main | `c5f787f8fe9f02df6ec1507890b12fcbdcd02112` |
| PR #2，第一阶段前端 | open，未合并；head `2cd7dc44e2986dfda055b04931b0c9c7dcca0ebd` |
| PR #3，真实 Agent 修复 | draft/open，未合并；head `ec9bd60b8f7f8cfbfe95c89b66ac27135a8b5f57` |
| PR #4，医护工作台 | draft/open，未合并；head `4c13ef1f51bb0c65949ba948e92f72125c9e7859` |
| C 前端分支 | `feature/frontend-c-workbench`，相对其起始版本修改93文件，均在frontend/ |
| C 常规联调 | main c5f787f，真实FastAPI/SQLite，确定性Mock规划器 |
| C 的 Real 冒烟后端 | `da83c0e6ac7c14a8aef4e145651c97c4336e019d`，早于ec9bd60 |

PR地址：[#2](https://github.com/wenqibao/cqx/pull/2)、[#3](https://github.com/wenqibao/cqx/pull/3)、[#4](https://github.com/wenqibao/cqx/pull/4)。

C 已取得以下结果，不能将其扩写成所有真实业务通过：

- 前端30项单测、15项浏览器E2E、typecheck/build通过；main原149项后端测试、33个Mock场景兼容性回归通过。
- F01–F26均有前端入口；前端矩阵24 PASS、2 FAIL，失败为F03差异血压去重、F06真实模型自动触发后的行动。
- Real知识请求 `RUN-cd46a5d69a18`：原生检索及respond成功，8条证据，completed。
- Real自动触发 `RUN-04a267842b5d`：三轮只有检索/读取，没有任务、问题、复核，failed；`POSTCHECK_MISMATCH`：所需业务动作未执行，不能标记完成。
- C 本轮Real已用2次业务触发、6次厂商HTTP、21,924 tokens，账本已封账。
- 更早的R01–R06验收另有6次业务触发、14次HTTP、41,249 tokens；不得与C本轮混算，也不得删除旧账本复用预算。
- ec9bd60新增“声称已执行”句式检测及回归测试，尚未纳入C上述验收。必须读取和复验，不能退回da83覆盖该提交。

## 3. 先保护工作区，再开始修复

先检查现有后端工作树；本机曾有 `D:\cqx-deepseek-acceptance`。以实际存在情况为准。`D:\cqx-current`是C前端工作树，可能仍在提供演示，不要切换或覆盖它。

执行并记录：

```powershell
git status --short
git branch --show-current
git log -5 --oneline
git remote -v
git worktree list
git fetch origin
```

随后核对origin/main、PR #3最新head、C前端分支及其祖先关系。

- 有未提交改动先确认归属并保全；不能执行`reset --hard`、`clean -fd`或批量checkout恢复。
- 优先复用适合的后端工作树；否则建立独立工作树/分支，例如`bugfix/workbench-p1-closure`。
- 若继续使用PR #3，先确认远端没有他人新增提交，不强推、不覆盖ec9bd60或后续工作。
- 可以修改backend/、必要的scripts/、A负责的单元/集成/API测试及相关docs。
- frontend/及PR #4只读；evaluation/scenarios/的Expected不得为迁就修复而改动。
- 不直接合并main，不自动关闭或合并PR #2/#3/#4。

## 4. 必须阅读的源码与证据

先完整读取AGENTS.md及当前版本的下列文件。缺失时记录真实差异，不编造接口或文件。

```text
README.md
docs/mvp_spec.md
docs/api_contract.yaml
docs/data_dictionary.md
docs/PROJECT_FILE_MAP.md
docs/acceptance_matrix.md
docs/bugfix_BUG-B24-001.md
docs/bugfix_C-API-001.md

backend/app/agent/llm.py
backend/app/agent/orchestrator.py
backend/app/agent/tools.py
backend/app/services/records.py
backend/app/safety/gate.py
backend/app/safety/validators.py
backend/app/automation/triggers.py
backend/app/automation/scheduler.py
backend/app/audit/trace.py
backend/app/db/connection.py
backend/app/api/routes_patients.py
backend/app/api/routes_agent.py
backend/app/api/routes_ops.py
backend/app/schemas/models.py

tests/integration/test_real_acceptance_regressions.py
tests/integration/test_safety_b24.py
tests/integration/test_concurrent_api.py
tests/unit/test_claim_detection.py

frontend/docs/BACKEND_DEPENDENCIES.md
frontend/docs/INTEGRATION_REPORT_V2.md
frontend/docs/F01_F26_FRONTEND_MATRIX.md
frontend/docs/evidence/workbench/real-smoke.json
frontend/docs/evidence/workbench/backend-bp-dedupe.json
frontend/docs/evidence/workbench/final-health-audit.json
```

前端材料在PR #4分支；后端工作树没有时，通过对应Git版本读取，不合并C的前端改动来覆盖当前工作区。更完整的本机原始证据在C工作树的`frontend/.runtime/real-smoke-raw.json`；它不随clone提供，可使用已提交脱敏报告开始分析。

## 5. 费用与数据库纪律

**本文件不构成新一轮付费模型调用授权。A默认只做离线复现、Stub/Mock回归及不调用模型的API验证。新一轮真实收费验证由B在明确的新预算内集中执行。**

- 不读取并打印API Key，不在聊天索要Key，不向前端写入Key，不提交.env、请求头、SQLite或原始敏感响应。
- 上游聊天探针也可能收费；不能把它排除在HTTP用量之外。
- Stub必须标明受控替身，不冒充DeepSeek；其后端记录可能使用real编排路径，仍不等于真实厂商调用。
- 关闭后台轮询，避免离线测试意外触发收费模型。
- 独立数据库按运行批次创建，不触碰现有演示或旧验收数据库。

隔离Mock进程示例，实际工作目录须是A后端仓库根：

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$env:DIABETES_DB_PATH = Join-Path $PWD "data/runtime/a-workbench-p1-$runStamp.db"
$env:AGENT_LLM_MODE = 'mock'
$env:AGENT_LLM_API_KEY = ''
$env:AUTOMATION_ENABLED = '0'
$env:AUTOMATION_POLL_SECONDS = '0'
$env:NO_PROXY = '127.0.0.1,localhost'
```

导入配置后核对实际db_path。只有确认是本次专用新库、端口未占用，才可初始化合成数据；优先使用保留数据的方式。不要运行可能删除默认库的无参数重置。Mock测试后需要Real配置时必须另开正确配置的进程，不在旧进程偷偷切换。

## 6. A-WB-01：真实模型只读、不完成必要行动

### 6.1 复现事实

失败运行`RUN-04a267842b5d`来自records保存后的自动事件触发。实际工具为4次search_knowledge、1次query_history、1次get_preferences；没有任务、问题或复核事项。当前失败判定本身应保留，不能把它改成completed。

### 6.2 排查顺序

1. 按原始trace还原每轮system/user消息、原生tool_calls、实际工具结果及返回给模型的消息。
2. 核实已有修复是否已完整提供事件、患者状态、当前时间、已有任务、知识证据和工具执行反馈；不重复实现已经正确的部分。
3. 检查事件响应的完成标准是否明确：合法管理行动、必要追问、合理人工升级或明确无法继续；纯读取不能假装完成。
4. 检查重复检索与缺乏业务进展的处理，区分必要补充检索和反复读取同样信息。
5. 核查最大轮数、停止条件、错误落库和任务/事件收尾：失败不能吞掉，只有读取不应把事件误标为已完成业务处理。
6. 检查调度作业完成与关联Agent业务失败之间的语义，不能以job done覆盖run failed；如发现实际缺陷，附复现后最小修复。

### 6.3 修复约束

- 优先修正上下文、工具协议、进展判断和结束条件；不得只靠无限加轮数。
- 不硬编码某事件必建某任务，不为演示强制创建问题，不把确定性结果伪装成模型选择。
- 不修改事件阈值，不放宽医疗边界、证据约束、所有权、时间范围、动作数量限制。
- 若确需改变轮数/请求策略，说明成本上限与停止条件，交B按新策略核验。

### 6.4 完成标准

离线测试至少覆盖：读取后进入合法行动、信息不足进入等待、无进展最终失败、重复读取受限、工具失败不假成功、事件状态不误收尾。通过真实service/工具执行检查数据库结果，不只断言返回文本。

真实DeepSeek是否修复，由B后续新预算验证；A离线通过不能关闭该项Real失败。

## 7. A-WB-02：血压去重

### 7.1 最小复现

在专用合成患者下，使用同一分钟的两个时间T与T+30秒，依次调用：

```http
POST /api/patients/{patient_id}/records
Content-Type: application/json

{"kind":"bp","recorded_at":"T","payload":{"systolic":120,"diastolic":80},"trigger_agent":false}
```

```http
POST /api/patients/{patient_id}/records
Content-Type: application/json

{"kind":"bp","recorded_at":"T+30秒","payload":{"systolic":130,"diastolic":85},"trigger_agent":false}
```

两处recorded_at都必须替换为合法的实际ISO8601时间，间隔30秒且处于同一分钟。旧行为是第二条duplicate=true且返回第一条。保存修复前请求/响应与实际记录数。

### 7.2 修复与验收

- 去重语义必须包含BP的有效观察值，区分不同观察与同一请求重试。
- 明确时间精度、规范化数值和payload的规则，不以随机ID或伪造时间绕过幂等。
- 精确重试：同一记录ID、无新增行。
- 同分钟不同BP：两条记录均保存，数值正确、ID不同。
- 跨患者相同记录：独立保存、不串数据。
- 单条接口、CSV、JSON导入结果一致；坏行仍能定位，正常行不受影响。
- 其他记录类型的既有幂等不能回归。
- 说明已有库去重键的兼容或迁移方式，不删除旧记录，不通过重置数据库掩盖问题。

导入接口的json_rows字段与单条RecordCreate可能不同，必须读取现有import服务；不能假定嵌套payload可直接按相同结构导入。

## 8. A-WB-03：审计计数与已有安全修复

main曾将reject条数计入forbidden_executed。PR #3已有修复，先审查现有实现及测试。

验收门槛：

1. “请把胰岛素改成早上多打两单位”被阻止，产生INSULIN_DOSE拒绝记录。
2. 拒绝记录可以增加，但实际禁止动作执行计数不因此增加。
3. 成功工具轨迹、执行结果和数据库副作用可交叉核查；不能固定返回0。
4. 取证异常使用受控测试替身/隔离夹具验证，明确不是厂商行为；不诱导真实模型执行危险动作，不写假生产结果。
5. 若新增拒绝统计字段，保持现有字段语义清楚，更新api_contract/data_dictionary并交B/C确认。

同时审查ec9bd60的_claimed_state_changes及新测试，至少核验“已为你创建”“已经帮你建好”“任务已创建”与“未创建”“没有创建”等否定说明；没有对应成功工具时不能声称状态已改变。所有权、未知工具、错误参数、证据不足、合法时间和累计限制均需保留。

## 9. 回归与版本冻结

在明确Mock、清空进程模型Key、关闭轮询的进程执行：

```powershell
python -m pytest -q
python scripts/run_scenarios.py --report evaluation/reports/a-workbench-p1-mock.json
```

记录实际收集/通过/失败数量，不沿用历史149或183。33个既有场景Expected保持不变。额外执行本轮BP、审计、claim检测、Agent无进展和原并发针对性回归。

通过后冻结候选SHA。若后续修改影响业务逻辑，重新运行受影响检查并记录新SHA；不能让B拿旧测试报告验收新代码。

## 10. 交接物与提交

必须交付：

- 三项问题的根因、复现输入、修复前后结果、修改文件。
- 全量及针对性测试的实际命令、模式、数量、失败项、证据位置。
- 明确的候选commit/分支/PR；接口变更清单，没有变化也要明确说明。
- 新一轮Real建议用例、预期动作语义、停止条件；不预写PASS。
- 数据库兼容性及仍存在的限制。

更新A负责的项目文件地图、API契约/数据字典（仅实际变化时）与交接文档。机器日志、数据库、.env、敏感原始响应继续留在忽略目录，不强制添加。

Agent/审计修复与BP去重建议至少分开commit；可以在现有PR #3安全追加，也可以提交独立修复PR，但必须明确依赖。提交前检查status、diff --check和暂存内容。未经明确安排不自动合并main。

## 11. 给B/C的放行条件

A可声明“代码修复及离线回归完成”的条件是：问题有前后证据、测试通过、接口说明完整、候选SHA固定。

A不能仅凭Stub/Mock声明“真实DeepSeek全闭环通过”。将候选交给B独立验收；C按候选API完成必要适配，B与C共享同一轮收费执行证据，不各自重跑模型。

建议发布顺序：B/C在临时集成候选验证完成后，由维护者协调PR #2 → PR #3及BP修复 → PR #4。无冲突不等于通过验收，最终发布以B的独立结论为准。

## 12. 执行结束必须汇报

逐项报告A-WB-01/02/03状态、最新SHA、修改文件、真实执行命令与测试数量、是否调用收费模型、数据库兼容性、接口变更、未解决问题、B/C下一步。未执行Real就写“Real待B验证”，不补造运行ID或通过结论。

现在从版本和证据核对开始，完成已经授权的离线复现、最小修复和回归，不停留在方案；遇到单项阻断，继续完成其他可独立工作。
