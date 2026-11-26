# O4 计划变化前端交接

2026-11-27，成员 C。开发自验记录，待 B 独立验收实际合并候选。

## 代码组合

| 项目 | 版本 |
| --- | --- |
| 起点 main | `80117eaad5fd31c18d348c27f5787d86ae452590`，O1 后端已合入 |
| plan_changes 后端 | `d49dc837b3e660a0163972410ec3212364ec0d9b`，feature/backend-agent-2day-adaptation |
| 前端分支 | feature/frontend-agent-2day-plan-changes |
| 包含的 O1 前端 | 从 ebed699 移植到最新 main，提交 dc1cc17，源码内容沿用已交付 O1 |
| O4 前端完整 SHA | 随提交交接，通过 git rev-parse HEAD 核验 |

当前 main 尚无 plan_changes，兼容入口按可选字段处理。计划变化的实际 API 联调绑定上表适配分支。最终合并时由 B 核验 A 的最终提交和目标 main，并更新组合版本。

## 实现

1. 在现有运行详情 summary 中增加可选 plan_changes 类型，旧响应省略字段时继续可读。
2. 仅把 result=saved 且存在实际差异的条目展示为计划变化。
3. changed_fields 内 before 与 after 相同的字段不显示，空差异不产生版本面板。
4. 失败结果或 plan_changes=[] 时不显示修改后版本。失败原因仍由 O1 的 unfinished 展示。
5. 前后版本、任务标题、原因和保存结果均读取当前运行的 plan_changes，关联任务的新状态不替代历史版本。
6. 首次保存的 version_before=null 显示首次保存，实际新版本号来自 API。
7. 已知字段使用中文名称。日期使用现有 when 函数，按原始带时区值转换为浏览器本地时间，保留完整日期。
8. 数字 0 按实际数值显示，空值显示未设置。任务状态和类型沿用业务映射。
9. 任务入口使用实际 patient_id/task_id，原始 plan_changes、来源扩展字段和 JSON 保留在运行日志。

字段映射和时间转换只负责展示。前端不从患者请求重新推算新计划或版本。

## 验证范围

前端使用 Node 24.22.3。适配后端通过 git archive 导出源码到本工作区忽略目录，在独立 SQLite、端口 8020、后端 Mock、关闭后台轮询的环境验证。

首次系统 tar 提取中文文件名不完整，得到的 571 项 pytest / 21 场景属于不完整快照。已用 Python tarfile 的 UTF-8 提取创建新快照，核对 33 个场景文件后重跑全部后端检查。最终全量结论使用完整快照的结果。

浏览器 O4 的成功链路走实际 FastAPI 和 SQLite，受控前端反例通过 Playwright 路由明确构造，覆盖字段无差异、空差异、未保存结果及旧响应。后端失败更新的真实版本与 plan_changes 由适配分支 test_run_adaptation.py 在 API 层验证。

本轮验证未调用真实 DeepSeek 厂商。离线检查包含受控模型 Stub，其模式和名称按原测试保留，不能作为厂商调用证明。

## 检查结果

| 检查 | 结果 |
| --- | --- |
| npm test | 62 passed |
| npm run build（包含 TypeScript 检查） | 通过 |
| 常规 E2E | 30 passed，含 3 项 O4 专项及 3 项 O1 专项 |
| 适配后端 python -m pytest | 完整快照 583 passed |
| 原场景 | 完整快照 33/33 PASS |
| 旧契约专项 | 14 passed，验证缺少新字段的旧响应兼容 |
| 审计 | forbidden_executed=0 |

构建保留既有大包提示和 Ant Design 弃用提示。截图已人工检查计划版本、字段差异、原因和任务链接。

## 三项 O4 浏览器专项

| 用例 | 核验 |
| --- | --- |
| 真实连续两次改期 | API 返回真实版本和差异，页面对应数据库版本；再次改期后刷新旧运行，原前后版本与时间仍一致 |
| 受控差异过滤 | 相同字段不出现，空差异条目及 result=failed 条目不显示版本，优先级 0 保留，原始日志完整 |
| 失败与旧响应 | 空 plan_changes 显示实际失败原因，页面不显示新版本；移除可选字段后仍可读取 |

实际 API 与截图证据在前端忽略目录，交付时可随文件包提供，独立复验重新生成。

- `frontend/.runtime/o4-api-evidence.json`。
- `frontend/.runtime/o4-plan-changes.png`。
- `frontend/.runtime/o4-e2e-final.json`。
- `D:/cqx-deliverables/o4-scenarios.json`。

本轮证据患者 `WB-O4changes-mwxs4fkn-oey2`，第一次运行 `RUN-fe1da9eafbbf`，第二次运行 `RUN-90845f7154ab`。同一实际任务的版本从 1 到 2，再从 2 到 3，页面刷新第一次运行后仍展示 1 到 2 的实际对照。已提交的合成证据位于 `frontend/docs/evidence/o4/plan-changes-api.json` 和 `plan-changes.png`。

## B 复验

1. 获取本前端分支完整 SHA、A 的适配分支最终 SHA、拟合并 main SHA，记录精确组合。
2. 确认 plan_changes 来自对应后端真实实现，字段包含 task_id/title/version_before/version_after/changed_fields/reason/result。
3. 建独立数据库，执行 Node24 依赖安装、前端单测和构建。
4. 执行 `npm run test:e2e -- e2e/plan-changes.spec.ts`，核查真实改期、历史运行和失败显示。
5. 执行完整前端 E2E 和旧契约检查，补后端规定的全量检查、健康检查和 forbidden_executed=0。
6. 查看技术日志，核对原始版本、字段、原因及未展示条目仍完整保留。
7. 根据项目要求对 A 的决策变化安排真实 DeepSeek 验证，报告中区分本轮前端展示验证和真实厂商验证。
8. 候选或 main 更新时，对实际组合重新核验，PASS 后由维护者合并。

A 根据 `frontend/docs/FILE_MAP_V2.md` 更新根文件地图。当前交付为候选，main 合并及 B 独立验收待执行。
