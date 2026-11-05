# F01–F26 前端逐项验收矩阵

日期2026-11-05；实现提交`52c966ba99f33edf47d82b11528fa7a32e953744`。**26项均有入口；24 PASS、2 FAIL。** 状态是本轮实际前端/API验收口径，不是整套系统已获临床或全量真实模型验收。Mock为真实FastAPI+SQLite的确定性规划器；Real单独统计。

证据目录均为`frontend/docs/evidence/workbench/`；E2E 15/15，单元30/30。F03的特殊血压去重、F06的真实模型后续行动未通过，前端没有修改后端来掩盖。

| 编号 | 合同功能 | 前端页面 | 路由 | API或真实来源 | 可用交互 | 测试用例 | 实际测试结果 | 证据文件 | 阻断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | 演示患者管理 | 患者管理/总览 | `/patients`、`/` | GET/POST patients | 搜索、新建合成患者、进入档案 | 新建合成患者/患者切换 | PASS：真实创建后重新GET | patient-created.json、browser-results.json | 无；仅合成演示 |
| F02 | 基础健康档案 | 患者详情 | `/patients/:id` | GET patients/{id} | 只读年龄/病程/目标/约束/完整度 | 新建合成患者并读取档案 | PASS：不填补缺项 | patient-created.json | 不支持修改档案，按合同保持只读 |
| F03 | 健康数据录入与导入 | 健康监测 | `/monitoring` | GET/POST records、POST records/import | 八类字段、CSV/JSON、失败行、实际去重 | 八种类型/CSV JSON导入/血压复核 | FAIL：常规录入导入通过；同分钟不同血压被后端错误去重 | record-types-api.json、imports-api.json、backend-bp-dedupe.json | A-WB-02，P1 |
| F04 | 状态记忆与趋势 | 档案/总览 | `/patients/:id?tab=records`、`?tab=history` | GET state、state/history、records | 3/7/14日记录、真实趋势、偏好、状态版本 | 患者切换及三尺寸 | PASS：图表只使用观测点 | dashboard-1366.png、browser-results.json | 历史API只给版本/时间，不提供旧正文 |
| F05 | 健康事件检测 | 事件中心/档案 | `/monitoring?tab=events` | GET events、POST events/scan | 查看规则级别/原因/状态；确认手动扫描 | 多事件协调/录入自动触发 | PASS：真实事件，无诊断推断 | multi-events-api.json、core-api.json | 无 |
| F06 | 新增数据主动触发 | 录入结果 | `/monitoring` | POST records的automation | 事件→run→实际工具及业务变化 | 核心闭环、C-REAL-02 | FAIL：Mock闭环通过；Real自动运行后三轮只读，未完成所需行动 | core-api.json、real-smoke.json | A-WB-01，P1 |
| F07 | 复评到期自动调度 | 系统验证/复评 | `/system?tab=maintenance` | GET jobs、POST clock/tick | 查看作业、确认推进时钟、执行一次tick | 隔离演示时钟与tick | PASS：实际产生到期复评；未声称本轮启用后台轮询 | maintenance-api.json | 后台持续轮询本轮关闭，未作为实测结果 |
| F08 | Agent自主决策 | 决策中心 | `/agent` | POST agent/runs、GET runs/{id} | 发起一次请求、等待/失败/阻止状态 | 主动提问、核心闭环、C-REAL-01 | PASS：Mock流程和Real知识请求实际执行 | followup-api.json、real-smoke.json | Real后续任务行动另见F06失败 |
| F09 | 个性化任务规划 | 任务/档案 | `/tasks` | tasks、state、events、preferences | 原因、事件、偏好上下文、优先级、合并元数据 | 核心闭环/多事件协调 | PASS：展示真实规划与元数据，不推测偏好曾影响任务 | core-api.json、multi-events-api.json | 本轮计划行动主要在确定性模式核验 |
| F10 | 真实工具调用 | 运行详情/工具说明 | `/agent?run=...`、`?tab=tools` | trace.steps、原生llm_response | 实际工具顺序、参数、结果、核对；14项中文说明 | 核心轨迹/C-REAL-01/无工具显示 | PASS：原生检索与respond实际成功 | real-smoke.json、real-WB-REAL-KNOW.png | 仅real标签不足时明确证据不足 |
| F11 | 健康任务管理 | 任务中心 | `/tasks` | tasks、task detail、complete | 人工确认完成、重新GET、状态/来源/版本 | 核心闭环 | PASS：staff_demo、done、v3 | core-api.json、persistence-restart.json | 不是认证后的工作人员身份 |
| F12 | 动态复评三分支 | 复评标签 | `/tasks?tab=reviews` | GET reviews、完成反馈 | 实际三分支/原因/任务/人工记录 | 核心闭环、人工复核、到期tick | PASS：三种分支均有真实记录 | core-api.json、reviews-safety-api.json、maintenance-api.json | 无 |
| F13 | 安全门与人工升级 | 审计/复评 | `/audit`、`/tasks?tab=reviews` | audit、reviews/resolve | 查看拒绝/升级、工作人员填写人工结案 | 人工复核及B24拒绝 | PASS：阻止请求、实际人工结案 | reviews-safety-api.json | A-WB-03/04；main审计计数口径须修正，身份字段不足 |
| F14 | 决策解释与追踪 | 运行详情 | `/agent?patient=...&run=...` | GET runs/{id} | 实际阶段、工具、结果变化、证据与JSON | 核心轨迹/跨患者深链接/失败显示 | PASS：缺失阶段不冒充执行 | trace-mock-1440.png、real-WB-REAL-AUTO.png | 无 |
| F15 | Web客户端 | 全局工作台 | 全部一级路由 | 统一Adapter与后端 | 导航、深链接、患者隔离、错误/空态、减少动态效果 | 三尺寸/断连/跨患者/全部流程 | PASS：1920/1440/1366，无溢出 | dashboard-1920.png、dashboard-1440.png、dashboard-1366.png、backend-offline.png | 无正式机构权限系统 |
| F16 | 站内待办提醒 | 通知中心/总览 | `/notifications` | GET notifications、POST read | 未读统计、对象链接、实际标记已读 | Agent协商与通知已读 | PASS：重新GET核验已读 | negotiation-notifications-api.json | 无 |
| F17 | CLI客户端 | 系统验证 | `/system?tab=cli` | 实际CLI命令、导入日志 | 复制不执行、导入真实日志 | CLI复制不执行；5条本机CLI | PASS：实际执行日志可查看 | cli-evidence.json、cli-evidence.png | 浏览器不能直接执行Shell，按合同不实现 |
| F18 | API与持久化 | 系统验证/各业务 | `/system` | health/mode/version、对象重新GET | 连接/数据库/模型状态、刷新读取 | 写后刷新、实际进程重启 | PASS：重启前后对象一致 | persistence-restart.json、backend-pytest.xml | 本机SQLite演示，不是生产部署 |
| F19 | 自动化场景测试 | 场景与报告 | `/system?tab=reports` | 33项真实场景目录、实际报告 | 命令复制、JSON导入、逐项结果/失败原因 | 报告导入；本轮脚本回放 | PASS：33/33仅标Mock | scenarios.json、browser-results.json | 不提供Web执行pytest的接口 |
| F20 | 实测结果与复现报告 | 场景与报告 | `/system?tab=reports` | 本轮JSON证据 | Git/日期/模式/明细/证据/限制 | 有效与无效报告、无报告空态 | PASS：不生成假通过率，不混Real/Mock | scenarios.json、real-smoke.json、TEST_REPORT_V2.md | 未提供的字段显示未提供 |
| F21 | 主动询问与信息补全 | 智能随访 | `/followups` | questions、answer.resume.run | 模拟答复/记不清/恢复run/结构化不确定性 | 主动提问与不确定答复 | PASS：不新增确定服药事实、恢复ID可见 | followup-api.json、followup-1440.png | A-WB-04；main可能重复追问，Real本轮不重测该分支 |
| F22 | 多事件协调与优先级 | 事件/决策/任务 | `/monitoring?tab=events`、`/agent` | 真实events、priority_order、tasks.meta | 同患者多事件及后端排序/合并依据 | 多事件协调 | PASS：至少3个事件、实际优先序列与任务 | multi-events-api.json、multi-events.png | 无前端自拟模型排序 |
| F23 | 计划协商与重规划 | 决策/任务抽屉 | `/agent?tab=negotiate`、`/tasks?task=...` | agent/runs、reschedule、versions | Agent协商与staff_demo人工改期分开 | 协商/核心人工改期 | PASS：旧新版本、操作者和关联run核验 | negotiation-notifications-api.json、core-api.json | 本轮协商模型为确定性模式 |
| F24 | 知识检索与证据约束 | 知识页/运行证据 | `/agent/knowledge`、运行详情 | knowledge、search、trace.evidence | 标题/机构/版本/锚点/引用、无结果 | 知识命中与无结果/C-REAL-01 | PASS：实际知识依据与Real回应 | real-smoke.json、real-WB-REAL-KNOW.png | 有限摘编，不是实时临床指南 |
| F25 | 长期偏好记忆 | 随访/档案 | `/followups?tab=preferences` | GET/POST/DELETE preferences | 模拟确认、覆盖、生效/清除历史 | 偏好来源、覆盖与清除 | PASS：合法来源，实际清除后重读 | preferences-api.json | A-WB-04；来源不是认证身份 |
| F26 | 决策自检与不确定性 | 运行自检/审计 | 运行详情checks、`/audit` | steps、rejections、post_check、audit | 拒绝码、真失败、核对、缺证据说明 | B24/无工具/失败/真实只读失败 | PASS：Real POSTCHECK_MISMATCH如实展示 | real-smoke.json、browser-results.json | 不证明任意语言意图均安全 |

发布决定：前端覆盖与本机演示已交付；**完整DeepSeek自主业务演示仍受F06阻断**。F03差异血压记录问题需A修复、B复验，前端不能通过修改去重键或虚构保存规避。
