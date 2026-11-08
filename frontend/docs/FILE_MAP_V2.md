# C第二阶段文件地图

2026-11-05。本轮源码、工具、文档和脱敏证据均在frontend/；未修改A/B后端、CLI、规则、原测试或场景Expected。仓库根PROJECT_FILE_MAP由A维护，合并后可引用本地图。

| 文件 / 目录 | 作用 |
| --- | --- |
| `src/ui/App.tsx` | 工作台布局、八模块导航、路由懒加载、旧路径重定向 |
| `src/ui/style.css`、`src/styles/tokens.css` | 统一样式、色彩、响应式、reduce处理 |
| `src/main.tsx` | 统一Ant Design中文与主题 |
| `src/app/WorkbenchContext.tsx` | 全局患者/模式、30秒心跳、同步写锁、患者深链接 |
| `src/hooks/useResource.ts` | 有界请求结果生命周期、取消与首帧隔离旧数据 |
| `src/components/common.tsx` | 加载/错误/空态、真实写入结果、状态、run链接、费用提示 |
| `src/components/TrendChart.tsx` | 按实际观测点绘制ECharts趋势，清理resize/实例 |
| `src/pages/dashboard/Dashboard.tsx` | 多患者真实汇总、重点患者、运行活动、分类待办 |
| `src/pages/patients/Patients.tsx` | 搜索/创建、档案与多标签详情、历史版本 |
| `src/pages/monitoring/Monitoring.tsx` | 八类录入、CSV/JSON导入、事件中心及自动触发结果 |
| `src/pages/followups/Followups.tsx` | 主动问题、模拟答复恢复、偏好覆盖与清除 |
| `src/pages/followups/Notifications.tsx` | 通知链接与实际已读保存 |
| `src/pages/tasks/Tasks.tsx` | 任务、staff_demo人工改期/完成、版本、三分支复评与人工结案 |
| `src/pages/agent/Agent.tsx` | 运行请求、协商、工具说明、业务化trace及失败/证据/自检 |
| `src/pages/agent/Knowledge.tsx` | 知识清单、实际检索和无结果 |
| `src/pages/audit/Audit.tsx` | 安全日志、拒绝码及已知计数口径限制 |
| `src/pages/system/System.tsx` | 服务/作业、CLI参考与日志、报告导入、导览、维护区 |
| `src/api/types.ts`、`src/api/workbench.ts` | 基础与扩展Zod契约、集中端点、真实恢复嵌套结构 |
| `src/api/httpAdapter.ts` | 唯一HTTP发送层、15秒GET/180秒写、无重试、队列、staff_demo完成 |
| `src/api/mockAdapter.ts` | 显式空模拟、拒绝假写入；不是HTTP失败回退 |
| `src/utils/format.ts`、`src/utils/reports.ts` | 文案/时间/患者链接、导入转换、真实报告解析、日志脱敏 |
| `src/utils/business.ts`、`src/utils/business.test.ts` | 中文业务映射、忠实运行摘要、正常/失败/未知字段边界测试 |
| `e2e/business-ux.spec.ts` | 四项双层展示验收、复制与三尺寸验证、历史Real失败只读回放 |
| `docs/C_UX_01_ACCEPTANCE.md`、`docs/evidence/ux/` | 本次C-UX-01验证说明、19项回归结果与保留的历史失败轨迹 |
| `src/components/RunConversation.tsx` | 实际消息/提问/回复气泡、真实待答状态与一键回答入口 |
| `e2e/reply-guidance.spec.ts` | 回复置顶、问题定位、不确定答复恢复及问题读取异常验证 |
| `docs/C_TO_B_UX_FOLLOWUP.md`、`docs/review/B_REPORT_V3_UX_2026-11-05.md`、`docs/evidence/ux-followup/` | B反馈原文、C修复交接、独立验证和初次失败记录 |
| `src/data/scenarios.json` | 从实际33个evaluation场景提取目录，不含假运行结果 |
| `src/api/*.test.ts`、`src/utils/reports.test.ts` | 原11项及新增19项前端单测 |
| `e2e/real-api.spec.ts`、`e2e/record-types.spec.ts` | 保留并适配原4类真实后端浏览器覆盖 |
| `e2e/workbench.spec.ts`、`e2e/multi-events.spec.ts`、`e2e/z-maintenance.spec.ts` | 随访/偏好/通知/审计/报告/多事件/调度等新增流程 |
| `e2e/helpers.ts`、`e2e/guard.ts`、`playwright.config.ts` | 专用mock库守卫、真实API夹具、单worker浏览器配置 |
| `tools/start-test-backend.py` | 安全启动8020隔离Mock后端，保留已有库 |
| `tools/real-smoke-server.py`、`tools/real-browser-smoke.mjs` | 手动独立Real冒烟，2触发/6HTTP硬上限，不自动重试 |
| `.env.example`、`README.md` | 本机启动、环境、模式、限制和操作说明 |
| `docs/PRODUCT_POSITIONING.md` | 目标用户、单Agent及操作者来源边界 |
| `docs/F01_F26_FRONTEND_MATRIX.md` | 固定26行实际验收结果 |
| `docs/API_PAGE_MAP_V2.md` | 页面/API/字段映射 |
| `docs/INTEGRATION_REPORT_V2.md`、`docs/TEST_REPORT_V2.md` | 本轮联调、自动化、Real/Mock独立结果 |
| `docs/BACKEND_DEPENDENCIES.md` | 已复现的A依赖、当前替代展示与严重度 |
| `docs/A_NEXT_EXECUTION.md` | 给A的完整独立执行指令：版本保护、三项P1修复、离线回归与交接 |
| `docs/B_V3_ACCEPTANCE_TASK.md` | B的V3独立验收执行书：精确SHA、隔离命令、18项UX用例、功能回归与三级结论 |
| `docs/B_NEXT_EXECUTION.md` | 给B的完整独立执行指令：隔离环境、独立复验、Real预算、发布门槛与PR顺序 |
| `docs/DEMO_WORKFLOW.md`、`docs/UI_DESIGN_SPEC.md` | 可录制流程及统一设计规范 |
| `docs/evidence/workbench/` | 本轮实际脱敏JSON、命令输出、XML、截图；不覆盖第一阶段历史证据 |
| `.runtime/`（忽略） | 专用SQLite、完整真实模型原响应、预算账本、早期/辅助检查；不随clone交付 |

依赖栈与锁文件沿用，未换项目骨架。最终文件数量和提交SHA以本轮Git差异/PR为准，完整源码清单可用`git diff --name-status 83073c7..HEAD -- frontend`复核。

## 2026-11-08 v0.2.1 契约与 C-DS-01/03 增量

| 文件 | 职责 |
| --- | --- |
| `src/api/httpAdapter.ts`、`types.ts`、`workbench.ts` | 部分成功、幂等响应兼容；保留补偿/拒绝字段；连接探测独立队列；409 中文说明 |
| `src/api/client.ts`、`.env.example` | 写请求超时环境配置 |
| `src/app/WorkbenchContext.tsx`、`src/components/common.tsx`、`src/ui/App.tsx` | 长处理反馈、结果待核对保护、只读核对入口和业务结果摘要 |
| `src/utils/business.ts`、`src/pages/agent/Agent.tsx` | 已纠正 warning 与未解决失败分开呈现，原始日志不删减 |
| `src/pages/followups/Followups.tsx` | 实际问题选项、置顶恢复结果、422 后重读过期状态 |
| `src/api/contract-v021.test.ts` | 契约兼容和失败边界专项单测 |
| `e2e/contract-v021.spec.ts`、`playwright.contract.config.ts` | 实际 HTTP/SQLite 的 10 项浏览器契约验证 |
| `tools/contract-server.py` | 专用新数据库、脚本模型和一次性故障服务；不接厂商模型、不新增业务端点 |
| `playwright.config.ts`、`package.json` | 普通回归排除需专用夹具的专项；新增 `test:contract` 命令 |
| `vite.config.ts` | 忽略运行目录和浏览器测试产物，避免其 HTML 触发开发页面重载 |
| `docs/C_TO_B_V021_CONTRACT_REGRESSION.md` | B 定向复验、源码快照准备、命令、模式和限制 |
| `docs/V021_REGRESSION_REPORT.md`、`docs/evidence/contract-v021/` | 本次实际测试结果与脱敏证据 |

根 `docs/PROJECT_FILE_MAP.md` 属于 A 的文件边界，本次未修改，A 可据本节同步前端文件入口。
