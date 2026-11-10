# 成员 B 执行指令：糖衡智管 V3 独立验收

编制日期：2026-11-05（Asia/Shanghai）。本文件可直接交给 B 或 B 的开发代理执行，不依赖此前聊天。

## 1. 身份、目标与边界

你是糖衡智管成员 B，负责独立验收，不代替 C 补写通过结论。

本轮首先验收 **V3 前端及 C-UX-01 / P1 双层展示**，然后给出它与候选后端组合后的功能回归结论。必须分别回答：

1. C-UX-01 是否真正解决，能否关闭该缺陷？
2. V3 前端是否可接受，是否可以进入后续集成？
3. 整个平台是否达到发布/参赛演示条件，还有哪些独立阻断？

只使用合成患者。系统不诊断、不开处方、不改药/停药/调胰岛素剂量，不自动医疗处置。高风险只交人工专业复核。

B 的提交范围遵守 `AGENTS.md`：`evaluation/`、`tests/e2e/`、指定的测试/缺陷/发布文档。不要直接修改 C 的 `frontend/src/`，不要为通过而修改场景 Expected、关闭断言或隐藏失败。产品缺陷分别交 A/C 修复后重新冻结候选。

本文件不是新的 DeepSeek 付费授权。不需要等真实模型预算才能开始 V3 界面与 Mock 后端验收。

## 2. 必须冻结的版本

| 项目 | 本轮输入 |
| --- | --- |
| 仓库 | <https://github.com/wenqibao/cqx> |
| 前端分支 | `feature/frontend-c-workbench` |
| V3 提交 | `ecdff65c02c4822b18a93d88826e07555a4d73fd` |
| 前端包版本 | `0.3.0` |
| 评审入口 | [PR #4](https://github.com/wenqibao/cqx/pull/4) |
| 本次主要缺陷 | C-UX-01：技术编号/英文/工具名过度暴露，业务可理解性不足 |

开始前执行并保存输出：

```powershell
git status --short
git branch --show-current
git remote -v
git worktree list
git fetch origin
git log -5 --oneline
git show --no-patch --format=fuller ecdff65c02c4822b18a93d88826e07555a4d73fd
```

在 B 自己的独立 checkout/工作树建立 `qa/v3-acceptance` 等验收分支。不要在 C 的 `D:\cqx-current` 工作树切换分支、重置数据库或运行写入测试。不要执行 `reset --hard`、`clean -fd` 或覆盖他人的未提交改动。

先验收上述精确 V3 提交。若远端又有新提交，记录差异并明确本轮到底验收哪个 SHA，不让测试过程中候选继续漂移。

若需要集成 A 的新修复：另行记录前端 SHA、A 的 SHA、集成后 SHA。**“V3 原始候选通过”和“新后端集成候选通过”分别出结论。** 不用原来的前端报告覆盖新的集成结果。

## 3. 必读文件与已有成绩的使用方式

```text
AGENTS.md
README.md
docs/mvp_spec.md
docs/api_contract.yaml
docs/data_dictionary.md
docs/PROJECT_FILE_MAP.md
frontend/README.md
frontend/docs/C_UX_01_ACCEPTANCE.md
frontend/docs/F01_F26_FRONTEND_MATRIX.md
frontend/docs/API_PAGE_MAP_V2.md
frontend/docs/BACKEND_DEPENDENCIES.md
frontend/docs/B_NEXT_EXECUTION.md
frontend/src/utils/business.ts
frontend/src/utils/business.test.ts
frontend/src/components/common.tsx
frontend/e2e/business-ux.spec.ts
frontend/playwright.config.ts
frontend/e2e/guard.ts
frontend/docs/evidence/ux/browser-results.json
frontend/docs/evidence/ux/final-business-results.json
frontend/docs/evidence/ux/real-failure-trace.json
```

C 提供的成绩是 **38 项单测、19 项浏览器回归通过，最后 4 项专项通过，构建通过**。这些仅供复现与对照，B 必须自己执行，记录本轮实际数量、失败与耗时。

旧 `B_NEXT_EXECUTION.md` 用于全平台、A 的 P1 和后续真实模型验收；其中 PR head 和 30/15 项成绩是旧快照。本次 V3 前端基线以上述 `ecdff65` 和本文件为准。

## 4. 建立不收费、互不干扰的环境

### 4.1 B 独立检出中的后端

以下命令在 B 自己的仓库根执行，先确认绝对路径和端口归属。示例使用后端 **8030**、前端 **5181**；若占用，选择其他空闲端口并同步修改所有配置，不停止别人的服务。

```powershell
$bRepo = $PWD.Path
$env:DIABETES_DB_PATH = Join-Path $bRepo 'frontend/.runtime/workbench-test.db'
$env:AGENT_LLM_MODE = 'mock'
$env:AGENT_LLM_API_KEY = ''
$env:AUTOMATION_ENABLED = '0'
$env:AUTOMATION_POLL_SECONDS = '0'
$env:FRONTEND_ORIGIN = 'http://127.0.0.1:5181'
$env:NO_PROXY = '127.0.0.1,localhost'
$env:PYTHONIOENCODING = 'utf-8'
python -m pip install -e ".[dev]"
```

数据库必须属于 B 的独立检出。若已有历史，先核对，不删除；新批次可采用新的独立检出。确认路径后初始化/补齐合成演示数据：

```powershell
python scripts/reset_demo.py --keep
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030
```

`--keep` 保留已有患者数据；不要使用无参数重置命令。初始化前还须确认 `AGENT_LLM_MODE=mock` 已在当前进程环境中生效。

另开终端核验以下真实请求，保存状态码及脱敏响应：

```powershell
Invoke-RestMethod http://127.0.0.1:8030/api/health
Invoke-RestMethod http://127.0.0.1:8030/api/system/mode
Invoke-RestMethod http://127.0.0.1:8030/api/patients
Invoke-RestMethod http://127.0.0.1:8030/api/patients/P001/state
```

要求：数据库正常；模式为 `mock`；数据库绝对路径属于 B；患者为合成数据。后端 `mock` 仍是真实 HTTP/业务函数/数据库执行，不是前端 MockAdapter，也不是厂商调用。

### 4.2 前端构建和测试

Node 满足 `package.json` 的要求，C 使用 Node 24.22.1。B 使用当前锁文件安装：

```powershell
cd frontend
npm ci
npm run typecheck
npm test -- --reporter=json --outputFile=.runtime/b-v3-unit-results.json
npm run build
```

每一步单独记录退出码，不因为最后一条命令成功就认定前面的命令成功。Chrome 缺失或依赖安装失败应标记环境阻断，不写 PASS。

### 4.3 同机独立端口的浏览器验收

既有配置默认 5180/8020；不能只把 API 夹具改到 8030，却继续用 C 的 5180 页面。UI、夹具和守卫必须连接同一个后端。

在 B 检出的 `frontend` 目录生成临时配置，保持提交的产品代码不变：

```powershell
$env:WORKBENCH_API_BASE = 'http://127.0.0.1:8030/api'
New-Item -ItemType Directory -Force .runtime | Out-Null
@'
import { defineConfig } from '@playwright/test';
import base from '../playwright.config';
export default defineConfig({
  ...base,
  testDir: '../e2e',
  globalSetup: '../e2e/guard.ts',
  use: { ...base.use, baseURL: 'http://127.0.0.1:5181' },
  outputDir: './b-v3-playwright-results',
  reporter: [
    ['list'],
    ['json', { outputFile: process.cwd() + '/.runtime/b-v3-browser-results.json' }],
  ],
  webServer: {
    command: 'npm run dev -- --port 5181 --strictPort',
    url: 'http://127.0.0.1:5181',
    cwd: process.cwd(),
    reuseExistingServer: false,
    env: { VITE_API_MODE: 'http', VITE_API_BASE_URL: process.env.WORKBENCH_API_BASE! },
  },
});
'@ | Set-Content -Encoding utf8 .runtime/b-v3-playwright.config.ts

npx playwright test --config .runtime/b-v3-playwright.config.ts
```

完整测试包含 4 项 `business-ux` 专项，无需为了凑次数重复执行。如修改展示、修复失败或需要定位，再单独运行：

```powershell
npx playwright test business-ux --config .runtime/b-v3-playwright.config.ts
```

守卫要求后端 mock，且数据库路径结尾为 `/frontend/.runtime/workbench-test.db`。不要绕过守卫。数据库同名不意味着可以复用 C 的库，必须核对绝对路径。

测试会改写 B 独立检出下的部分 `frontend/docs/evidence/` 截图和结果。先保留旧证据，将本轮输出复制到 B 的 `evaluation/reports/` 批次目录；不要把生成物当作前端源码修复提交。保存运行前后源码哈希，证明没有偷偷改产品或 Expected。

## 5. C-UX-01 核心人工验收：不看编号也能理解

选用 B 本轮产生的合成病例，至少覆盖以下四类运行：

1. 健康记录变化自动触发，产生实际管理任务。
2. 缺信息主动提问，患者模拟回答“记不清”，恢复后仍保持不确定性。
3. 超范围请求被安全门拦截。
4. 存在真实失败/执行后核对不一致，或无可确认工具结果。

对每一类运行，先保持所有技术详情关闭，不以编号/JSON作为解释材料。请测试者仅根据页面回答并把原话记入报告：

- 患者发生了什么，为什么启动这次处理？
- Agent 实际做了什么？
- 哪些动作成功，哪些失败或被拦截？
- 现在需要谁做什么，有没有待补充信息/任务/人工复核？
- 哪些结论有知识依据，系统有哪些安全边界？

只提供“已完成”“运行成功”但无法解释上述问题，或者必须看 RUN/EVT/TSK 才能理解，即为该用例不通过。没有实际触发信息时，明确写“未提供”是合格的诚实展示，不能要求前端编造原因。

至少一名非本次实现作者完成独立阅读；若由非医护成员测试，应如实注明身份，不能写成“医护专家认可”。记录理解障碍与具体页面，不以开发者自评替代。

## 6. 逐项用例与硬性 Expected

所有用例记录 PASS / FAIL / BLOCKED / NOT_RUN、对象编号、证据位置。不能只列勾选框。

| ID | 操作 | Expected |
| --- | --- | --- |
| UX-01 | 查看运行列表与详情，保持技术层关闭 | 业务标题和一句话摘要优先；触发原因、实际动作、人工下一步清楚；编号不再充当主标题 |
| UX-02 | 检查五个指定枚举 | waiting_user=等待患者补充信息；answer_received=患者已回答；medication_taken=是否按时服药；request_human_review=请求医护人员复核；FORBIDDEN_ACTION=操作超出系统允许范围，已拦截 |
| UX-03 | 检查其他状态/工具/拒绝原因与未知字段 | 有中文业务映射；未知内容明确“未映射/见技术详情”，不猜含义；原值可找回 |
| UX-04 | 展开运行、任务、问题、事件与知识详情 | API 实际返回的 RUN/EVT/TSK/Q/KD、触发关联、精确状态完整保留；不能凭空生成不存在编号 |
| UX-05 | 复制编号及完整 JSON，粘贴到文本中比对 | 内容与真实接口逐字一致，无截断、错患者或错对象；复制失败不可提示已成功 |
| UX-06 | 展开工具轨迹 | 默认为中文行为；原 tool_call/tool_result、参数、结果、核对、拒绝码和顺序能完整追溯；缺调用记录时不补造参数 |
| UX-07 | 仅有计划、没有实际执行 | 摘要不得声称已创建任务/提问/复评；实际未执行与未返回清楚可见 |
| UX-08 | 工具返回成功但 post_check 失败 | 整次业务不能写成全部完成；显示失败/不一致、已有动作及人工核查要求 |
| UX-09 | 不确定模拟回答与恢复 | 不把“记不清”转成已服药事实；标题只描述实际成功的追问或任务，不照抄固定演示文案 |
| UX-10 | 安全门拦截请求 | 业务原因明确；原拒绝码可查；系统门拦截不冒充模型主动拒绝；无危险任务或医疗修改 |
| UX-11 | 检查有证据及无证据运行 | 标题、机构、版本、原文/出处可读，精确编号可查；没有证据时不伪装成有依据结论 |
| UX-12 | 任务列表、改期版本及复评 | 任务标题/原因/截止时间/来源/当前待办清晰；人工操作与 Agent 动作区分；版本原文不丢 |
| UX-13 | 审计日志与计数提示 | 中文行为、拦截原因、决定、后续人工核查清楚；原始字段/上下文和口径警告保留，不把被拦截解释成实际执行，不前端硬改计数为0；后端统计修复单独判定 |
| UX-14 | 切换患者、打开其他患者的 run/task 链接 | 拒绝混用患者上下文；不得展示旧患者残留数据、发起错误患者写入 |
| UX-15 | 断连、404、422、上游失败、超时、空轨迹 | 明确错误或空数据；不回退前端假数据，不伪装成功，不自动重复收费写入；不支持的错误用受控测试响应并注明 |
| UX-16 | 1920×1080、1440×900、1366×768 | 默认业务信息可读，详情/表格可操作，无文档横向溢出；局部表格滚动可接受且须可发现 |
| UX-17 | 键盘展开/关闭技术详情、复制、关闭抽屉；减少动效 | 焦点可见、主要操作可达；禁用动效不使界面卡住；颜色之外有文字标识失败/状态 |
| UX-18 | 打开/关闭业务详情和复制 | 展示行为不偷偷触发 Agent、恢复回答或重试模型；通过网络记录核查零业务写入 |

对控制响应/fixture 的用例，记录覆盖了哪些接口；不能把浏览器响应替换结果写成实际后端执行通过。若发现展示同时显示“动作失败”和“整体成功”，保留两者同屏证据并提交缺陷，不能仅依靠技术详情解释。

## 7. 历史 DeepSeek 失败的专项取证

V3 保留的历史失败：`RUN-04a267842b5d`，原患者 `WB-REAL-AUTO`，`status=failed`，`POSTCHECK_MISMATCH`。工具有检索/读取成功，但未完成必要业务动作。

使用 `frontend/docs/evidence/ux/real-failure-trace.json` 运行现有专项。必须确认：

1. 默认层显示“处理未全部完成”、实际读取动作和人工核查要求。
2. 不因已有知识证据就写“任务已创建”“处理成功”。
3. 展开能找到完整 run、事件、原始调用参数、拒绝码及 JSON。
4. 测试不发起新的 POST/模型请求。
5. 报告写明是**历史真实响应只读回放**。现有测试仅把展示患者关联替换为 P001，fixture 原始状态/参数/输出不变；不能把该患者关联视为数据库事实。

本项展示通过，不代表真实模型“只读不行动”已修复，也不代表新的 DeepSeek 端到端验收通过。

## 8. 原有闭环与持久化回归

至少保留并独立验证以下流程；优先复用完整 19 项测试，缺覆盖时在 B 目录补测试并说明：

- 八类记录/CSV/JSON导入、逐行错误与重复结果；记录保存后自动触发，无额外“运行Agent”POST冒充自动化。
- 任务实际创建、工作人员改期、版本保存、完成、复评结果；`staff_demo` 与模拟患者/Agent来源区分。
- 主动提问、答复恢复，检查真实嵌套 `resume.run.run_id`；不确定答复没有伪造药物事实。
- 多事件协调、偏好保存/覆盖/清除、知识命中/无结果、通知已读。
- 患者切换、深链接、刷新后对象一致、失败/断连如实展示。
- 写入后 GET、刷新与实际重启 B 后端后读取同一数据库，任务状态、版本、记录保持一致。

重启只针对 B 自己的进程；保留进程参数、数据库绝对路径和前后对象。手动 tick 测试不得声称后台无人操作轮询已通过。

## 9. 后端 P1 与真实模型：单独判定

以下三项属于后端，V3 的界面改造本身没有修复：

| 问题 | B 的判定要求 |
| --- | --- |
| A-WB-01：真实模型只读不行动 | 在 A 的新候选上独立证明实际管理动作或合理等待/拦截，并核对工具/数据库；历史失败回放不能关闭 |
| A-WB-02：同分钟不同血压被去重 | 验证不同 BP 均保存、精确重试幂等、跨患者与导入一致；不能前端篡改时间/随机键规避 |
| A-WB-03：审计计数口径 | 验证拒绝与真正执行分开，计数与副作用一致；旧main问题与新后端候选分开报告 |

若 A 已交付新分支，先 fetch 并审查实际源码/提交，不沿用旧 PR head。详细后端用例参考 `B_NEXT_EXECUTION.md`，本文件不宣布这些问题仍存在于未经检查的新候选，也不提前宣布关闭。

真实 DeepSeek 验收只有在明确新预算、隔离数据库、持久化账本与停止条件后执行。没有新授权时标记 `BLOCKED / budget_not_authorized`，完成其他所有验收；不要求用户在聊天中提供 Key，不删除旧账本，也不复用 C 已耗尽的额度。

`llm_mode=real` 只表示运行配置；厂商真实调用需要原生响应、HTTP尝试计数、工具结果、证据和数据库副作用共同核验。Mock、受控 Stub、历史回放、真实 DeepSeek 分列，不混成绩。

## 10. 缺陷报告与交付物

建议在 B 所有的目录交付：

```text
evaluation/reports/v3-acceptance/<batch-id>/
  manifest.json
  commands.txt
  browser-results.json
  unit-results.json
  api/                  # 本轮真实脱敏请求/响应
  database/             # 只读查询结果，不提交原始数据库
  screenshots/
  human-readability.md
  case-results.csv
  acceptance-report.md
docs/bug_log.md          # 更新本轮BUG与状态
docs/release_report.md   # 写独立发布判断
```

这是要求 B 生成的产物，当前不假定已经存在。无证据项标记未执行；不能用空文件冒充结果。manifest 至少包括候选 SHA、前端版本、后端 SHA、Node/Python/浏览器版本、API基址、数据库归属、模式、测试时间和实际数量。

每个缺陷必须包括：

```text
BUG-ID / 严重度 / 责任人A或C
精确候选SHA、患者及运行/任务/问题编号
前置数据、操作步骤、请求与响应（脱敏）
Expected / Actual
业务影响：医护会误解什么，B是否仍能追踪
截图/轨迹/只读数据库证据
复现率、是否回归、建议修复范围
修复SHA与复验结果（未修复就明确未关闭）
```

证据不含 Key、Authorization、`.env`、真实患者信息、原始数据库或模型隐藏推理。保留失败，不改 Expected。完成后提交 B 的测试/报告分支，提供真实 commit 与可复现命令，不直接合并 main。

## 11. 验收门槛与最终回复模板

**关闭 C-UX-01 的必要条件**：默认层可解释触发/动作/结果/下一步；技术原文完整且可复制；失败不写成功；指定中文映射正确；没有由展示引入的跨患者/虚假事实/隐式写入问题；自动化与人工阅读均有独立证据。

**V3 前端可接受**：上述成立、核心闭环无新增 P0/P1 回归，构建/类型/测试通过；已知后端问题和前端限制明确保留。仍有阻断时给出可复现事实，不签“有条件全通过”。

**平台可发布/合并 main**：另需集成候选通过 A 的后端 P1 复验、适用安全门和必要的真实模型验收。V3 前端验收通过不自动满足这一层。不要自动合并、关闭旧 PR 或宣布真实模型全功能闭环通过；将精确 SHA 与建议交维护者协调。

最终回复必须包含：

```text
验收候选：前端SHA / 后端SHA / 集成SHA / 包版本
环境与模式：Mock / Stub / 历史回放 / Real分别列明
自动化：实际总数、通过、失败、阻断、耗时
人工业务阅读：测试者身份、四类运行、五问回答与结果
C-UX-01：可关闭 / 不可关闭，理由与证据
V3前端：接受 / 暂缓，理由与证据
后端P1：逐项已关闭 / 未关闭 / 未验证
平台发布：允许建议 / 暂缓，未满足的门槛
缺陷清单：BUG-ID、责任人、严重度、复现证据
B实际提交：commit、分支、报告路径、复现命令
```

不要只回复“页面正常”“测试全绿”“可以合并”。必须区分前端展示通过、真实后端功能通过和真实厂商模型通过。
