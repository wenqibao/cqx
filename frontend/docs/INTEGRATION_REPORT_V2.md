# 医护监管工作台实际联调 V2

日期：2026-11-05；实现提交`52c966ba99f33edf47d82b11528fa7a32e953744`，文档/证据随后单独提交。当前分支`feature/frontend-c-workbench`，源自第一阶段本地`83073c7`，已包含main `c5f787f8fe9f02df6ec1507890b12fcbdcd02112`。PR #2与后端PR #3未被覆盖或合并。

## 环境与范围

- 修改范围为frontend/；未改backend/、cli/、config/、tests/或场景Expected。
- 主联调：`http://127.0.0.1:5180` → FastAPI `8020`，后端main c5f787f，`llm_mode=mock`，数据库`frontend/.runtime/workbench-test.db`。
- 真实模型冒烟：`5192` → `8021`，使用现有后端PR #3检出`da83c0e6ac7c14a8aef4e145651c97c4336e019d`，`real/deepseek-flash`，域名`api.deepseek.com`，独立`frontend/.runtime/workbench-real.db`。
- 上轮`D:\cqx-deepseek-acceptance\data\runtime\deepseek_acceptance.db`及其6次触发账本未动；本轮是新的、单独受限的2次冒烟，不混入上轮R01–R06统计。
- 当前无正式机构身份/授权系统。仅合成数据、本机端口；关闭后台轮询，不把手动tick写成持续后台执行。

## 真实FastAPI与SQLite业务闭环

15项浏览器测试全部连接隔离后端。除明确的错误/无工具UI边界测试使用Playwright受控响应外，成功业务操作均通过真实API，未用前端Mock填充数据。

| 业务 | 实际结果 / 标识 | 证据 |
| --- | --- | --- |
| 录入自动触发 | 患者`WB-case-mw2ujmfa-q3a5`，运行`RUN-c049d5dbc251`；records保存后产生事件/任务，无额外agent/runs POST | core-api.json |
| 工作人员改期与完成 | 任务`TSK-7eec0426d98c`，v1→v2→v3，done，操作者staff_demo，完成后实际CLOSED复评 | core-api.json、persistence-restart.json |
| 不确定答复恢复 | 问题`Q-fdeb5c5f3cc5`，回答“记不清”，uncertain=true，无新增服药事实；恢复`RUN-f7bac5a486aa` | followup-api.json |
| Agent协商 | `WB-case-mw2ulfxn-08by`，真实update_task、版本与run关联；通知POST read后重新GET已读 | negotiation-notifications-api.json |
| 多事件 | `WB-case-mw2ujhph-d1ez`，至少3个实际规则事件，后端priority_order与任务可查 | multi-events-api.json |
| 三分支 | CLOSED来自完成；MISSING_DATA来自实际时钟推进和tick；HUMAN_REVIEW来自合成低值记录，人工填写结案保存 | core-api.json、maintenance-api.json、reviews-safety-api.json |
| 八种记录与导入 | 八类保存、结构化payload、CSV错误行、重复行、JSON血压/症状导入实际返回 | record-types-api.json、imports-api.json |
| 偏好 | 合法patient_input来源、覆盖与cleared历史 | preferences-api.json |
| 持久化 | 实际停止8020专用进程后重新启动，33名合成患者、记录ID、done/v3任务与版本完全一致 | persistence-restart.json |

所有上述规划/自动化业务为确定性Mock规划器，不是DeepSeek自主规划成功证据。工具、任务、记录及SQLite状态是真实执行；“真实HTTP”与“真实模型”分开标示。

## 本轮真实DeepSeek浏览器冒烟

| 场景 | 结果 | 真实事实 |
| --- | --- | --- |
| C-REAL-01 知识请求 | PASS | `RUN-cd46a5d69a18`；原生search_knowledge两次、respond成功，8条实际证据，最终completed；约70秒等待期间前端未超时重提 |
| C-REAL-02 录入自动触发 | FAIL | `RUN-04a267842b5d`；records确实保存并自动触发，三轮只执行4次检索、query_history和get_preferences，没有任务/问题/复核；后端POSTCHECK_MISMATCH“所需业务动作未执行，不能标记完成”，前端显示失败 |

受限服务器持久化记录**2次业务触发、6次厂商HTTP、6次HTTP成功**；prompt 20,841、completion 1,083、total **21,924 tokens**；cache hit 13,952、miss 6,889。未取得费用账单，不估价。HTTP成功没有被当作业务全通过。未重复收费重跑，也未调整后端轮数、事件阈值或安全规则。

脱敏报告`real-smoke.json`和真实页面截图随交付；完整合成响应/trace在忽略的`frontend/.runtime/real-smoke-raw.json`，完整账本在`.runtime/workbench-real-ledger.json`。不含请求头/API Key。旧任务的41,249 tokens不计入本轮。

## 已修正的前端问题

1. 移除患者个人空间定位，拆分App为模块页面与公共组件，侧栏导航只携带患者上下文，防止跨模块tab串入造成空白。
2. 问题恢复按真实`resume.run.run_id`解析并显示；不确定回答不转成确定服药记录。
3. 人工完成/改期改为staff_demo，真实版本确认；模拟答复和偏好明确标识，不伪造永久操作者审计。
4. 普通GET短超时、写请求180秒，无自动重试；原生Real约70秒请求已实测完成返回。写入全局同步锁，切换患者隐藏旧数据并取消读取。
5. 减少动态效果采用极短动画时长，保留组件结束事件；浏览器患者选择在reduce设置下通过。
6. 轨迹默认业务可读，缺步骤/无工具/失败/证据不足分别显示；完整JSON只作折叠调试。

首轮测试器还出现中文ID与编码URL的响应匹配、导入选项出现时机、装饰图标参与无障碍名称等问题，均定位后修正；未改后端或原场景预期。最终15项全过，早期失败日志保留在本地/证据供复核。

## 未通过与发布限制

F03同分钟不同血压错误去重、F06 Real只读不行动仍失败；main审计计数口径和操作者审计字段不足见BACKEND_DEPENDENCIES.md。前端完整覆盖不代表全量真实业务发布通过。A应先审查PR #3并处理新问题；B独立复验后再确定真实模型比赛演示版本。没有自动合并main。
