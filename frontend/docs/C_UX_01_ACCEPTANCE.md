# V3（0.3.0）· C-UX-01 / P1：业务说明与技术详情双层展示验收

日期：2026-11-05。基于 `feature/frontend-c-workbench` 的 `4c13ef1` 继续开发。所有源码、测试和文档改动均在 `frontend/`，未修改后端、业务规则或场景 Expected。

## 已实现的行为

| 范围 | 默认业务层 | 技术层 |
| --- | --- | --- |
| Agent 运行列表 | 每次运行的业务标题、结果摘要、触发原因、中文状态 | 运行编号及原始运行对象 |
| 运行详情 | 为什么触发、已返回成功的动作、失败或拦截、人工待办、安全边界、知识依据 | 完整运行编号、触发关联、全部步骤、原始调用参数、工具结果、拒绝码与 JSON |
| 工具轨迹 | 中文业务行为、实际结果摘要、动作状态 | 对应的完整 `tool_call` / `tool_result`；缺失调用记录时明确提示 |
| 随访 | 问题正文、是否按时服药等中文字段、回答状态、不确定性 | 问题编号、来源运行、原始字段、完整回答对象 |
| 任务与复评 | 任务标题、状态、截止时间、版本、创建原因、复评结果和人工待办 | 任务、事件、运行、复评编号与版本快照 |
| 审计 | 中文业务行为、拦截原因、审计决定、下一步核查提示 | 审计编号、原码、原操作、关联运行与完整上下文 |
| 知识依据 | 标题、机构、版本、引用原文和来源链接 | 知识编号、片段编号、锚点和完整证据对象 |

运行链接显示“查看处理经过”，编号保留为小字。其他技术对象通过“技术详情（编号、参数与原始数据）”展开；原始 JSON 另有折叠入口。编号与 JSON 都提供复制按钮，实际浏览器已验证复制任务编号后剪贴板内容与 API 返回一致。

关键映射包括：`waiting_user` → 等待患者补充信息；`answer_received` → 患者已回答；`medication_taken` → 是否按时服药；`request_human_review` → 请求医护人员复核；`FORBIDDEN_ACTION` → 操作超出系统允许范围，已拦截。未知枚举明确显示“未映射业务字段（见技术详情）”，不推测含义；原值仍完整保留。

## 摘要与真实性边界

- 使用前端确定性展示模板组合已返回的信息，不新增模型请求，不产生医学判断。
- 只统计实际输出动作或实际工具结果；计划中存在某项动作不能证明执行成功。
- 工具失败、执行后核对失败、拒绝项或整次运行失败，均提示“处理未全部完成”并要求人工核查。成功读取历史或知识不能替代任务创建、提问或复核完成。
- “患者回答不确定，已安排记录核实任务”只在回答文本明确不确定、且实际成功动作包含创建任务时生成；若实际动作是追问，则显示“患者回答不确定，已继续追问核实”。
- 没有触发正文、没有知识证据或没有工具结果时明确说明未提供，不补写原因或证据。
- 原始对象不经过展示替换，完整轨迹、拒绝码与原始 JSON 可供 B 追踪。
- 审计计数口径限制继续保留；本次不修复后端计数，也不据数字宣称发布安全门已通过。

## 实际验证结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| TypeScript 严格类型检查 | PASS | 构建也执行对应类型检查，命令见下 |
| 前端单测 | 38/38 PASS，其中新增业务展示边界 8 项 | `evidence/ux/unit-results.json` |
| 完整浏览器回归 | 19/19 PASS，约 2.6 分钟 | `evidence/ux/browser-results.json` |
| 最后文案/格式调整后的专项复验 | 4/4 PASS，28.7 秒 | `evidence/ux/final-business-results.json` |
| 生产构建 | PASS | 仍有已存在的 500 kB 包体积提示；未调整告警阈值 |
| 编号复制与技术原文 | PASS | 专项浏览器测试直接核对剪贴板、原始调用与拒绝码 |
| 1366 / 1440 / 1920 宽度 | PASS | 专项覆盖 Agent、随访、任务、审计，完整回归也覆盖原 9 类页面，无文档横向溢出 |
| 历史真实失败的展示 | PASS（只读回放） | `evidence/ux/real-failure-trace.json`、`real-failure-replay.png` |

完整浏览器回归仍验证：数据录入自动触发且无额外 Agent 请求、八种记录类型、任务改期/完成/复评、随访恢复、不确定回答不伪造服药记录、偏好、知识检索、审计、多事件、患者隔离、断连、上游失败及调度。只调整了展示断言的操作路径：原先直接读取编号/工具名的断言，现在先展开技术详情；业务状态与数据库断言未放宽。

本次真实 Mock 后端回归对象例：

- 自动触发运行：`RUN-781709f48a8b`。
- 关联任务：`TSK-f5826395c109`，实际完成、版本及复评见 `evidence/ux/regression/core-api.json`。
- 不确定回答恢复运行：`RUN-45a5d1c974cc`，见 `evidence/ux/regression/followup-api.json`。

“真实 Mock 后端”表示 HTTP、业务函数和 SQLite 实际执行，规划器为确定性 Mock，不表示调用了厂商模型。本次没有重新执行后端 pytest 或 33 场景，不沿用旧结果声称为本次运行。

## 历史 DeepSeek 失败回放说明

保留历史运行 `RUN-04a267842b5d` 的实际 API 轨迹，原始患者为 `WB-REAL-AUTO`。它仍为 `failed`，拒绝项仍为 `POSTCHECK_MISMATCH`，仅成功检索/读取，没有关联任务、问题或复评。

专项测试通过浏览器路由替换回放这份已保存的 API JSON，仅把展示患者关联改为现有合成患者 `P001` 以验证页面；原 fixture、工具参数、状态、拒绝码和输出不变。测试验证零 POST。**这是历史响应的界面回归，不是新的 DeepSeek 联调，也不证明 A-WB-01 已修复。**

## 本机复现

仓库根目录启动隔离后端（保留已有库，不重置、不调用模型）：

```powershell
python frontend/tools/start-test-backend.py
```

另一终端：

```powershell
cd frontend
$env:VITE_API_MODE='http'
$env:VITE_API_BASE_URL='http://127.0.0.1:8020/api'
npm run dev -- --port 5180 --strictPort
```

执行验证：

```powershell
cd frontend
npm run typecheck
npm test
npm run build
npm run test:e2e -- business-ux
# 完整回归：npm run test:e2e
```

默认 E2E 守卫要求后端 `mock` 且数据库路径为本仓库 `frontend/.runtime/workbench-test.db`，不满足则停止。本次为保护旧版工作台证据，使用忽略目录中的临时 Playwright 配置把报告另存后复制到 `docs/evidence/ux/`；完整回归产生的新证据归档到 `ux/regression/`，旧 `workbench/` 文件已恢复。本机使用现有 Node 24.22.1，依赖未变。

## 文件与交接

- `src/utils/business.ts`：唯一业务展示转换、实际动作摘要与运行叙述。
- `src/utils/format.ts`：共享中文枚举映射。
- `src/components/common.tsx`：编号复制、完整原文复制、统一技术详情、业务运行链接。
- `src/pages/agent/`、`followups/Followups.tsx`、`tasks/Tasks.tsx`、`audit/Audit.tsx`：默认层与技术层落地。
- `src/utils/business.test.ts`、`e2e/business-ux.spec.ts`：语义边界与实际浏览器验收。
- `README.md`、`docs/FILE_MAP_V2.md`：同步操作说明和前端文件地图；根 `docs/PROJECT_FILE_MAP.md` 属 A，未跨目录修改。

B 可按本报告展开原文检查完整编号、参数、拒绝码与证据；医护业务验收只需默认层。仍需 B/实际使用者独立确认措辞是否适合答辩与医护工作习惯。本次未修改默认模型模式，未新增付费调用，未关闭 A 的三项后端 P1，也未执行 PR 合并。
