# 糖衡智管 F01-F26 功能验收矩阵（角色 B）

版本：B-final-2026-11-03
状态：**验收完成** —— 基于合并后主干（merge `d3c0729`，main `f062e98` + qa `c3173c6`），142 项 pytest 全绿 + 33 个场景（S01-S09 / B01-B24）全 PASS + CGMacros 真实数据验证。
验证原则：场景 Expected 先于程序执行确定；以下状态均来自真实运行结果，未根据程序输出倒改预期。

> 场景命名说明：`CASE-001~037` 为 B 早期设计规格（SPEC_ONLY），实际落地执行时统一为 `S01-S09`（A 示例）+ `B01-B24`（B 扩充）共 33 个，内容等价覆盖 F01-F26。CGMacros 验证另见 `docs/public_validation_dataset.md`。

## 验收矩阵

| 功能 | 验收对象 | 验证证据（pytest / 场景） | 关键通过条件 | 状态 |
|---|---|---|---|---|
| F01 | 演示患者管理与隔离 | `test_patient_crud_and_state`；B01 | 患者/验证命名空间隔离，不串数据 | ✅ 通过 |
| F02 | 基础健康档案 | `test_patient_crud_and_state`；B10/B11 | 档案字段持久化，缺失字段显式记录 | ✅ 通过 |
| F03 | 健康数据录入与导入 | `test_records.py`（9 例）；B09；CGMacros 导入 | 合同字段可导入，错误可定位，原始数据不被覆盖 | ✅ 通过 |
| F04 | 状态记忆与趋势 | `test_state.py`（4 例）；B22 | 状态由历史数据计算，缺失不被默认值替代 | ✅ 通过 |
| F05 | 健康事件检测 | `test_events.py`（6 例）；B02-B08 | 只按版本化规则检测，不宣称临床诊断 | ✅ 通过 |
| F06 | 新增数据主动触发 | `test_record_save_triggers_event_and_agent`；S01/B02 | 保存数据后无需点击即触发；重复提交幂等 | ✅ 通过 |
| F07 | 复评到期自动调度 | `test_scheduler_tick_runs_due_review_without_click` / `test_scheduler_is_idempotent`；S05/B21 | 时钟前进后自动执行，重启可恢复 | ✅ 通过 |
| F08 | Agent 自主决策 | `test_agent_creates_task_and_trace_is_reproducible`；各场景 run | 读取状态后选择询问/检索/任务/复核 | ✅ 通过 |
| F09 | 个性化任务规划 | `test_multi_event_merge_and_priority`；B18 | 同事件不同病史生成不同安全任务 | ✅ 通过 |
| F10 | 真实工具调用 | 每次 run 的 `agent_steps` tool_call/tool_result；各场景 | 工具有真实返回和 DB 证据，禁止动作不调用 | ✅ 通过 |
| F11 | 健康任务管理 | `test_agent_flow.py`；B19/B20 | 任务状态/期限/关联事件/去重正确 | ✅ 通过 |
| F12 | 动态复评三分支 | `test_task_completion_leads_to_closed_review` / `test_review_missing_data_branch` / `test_human_review_branch_for_high_risk`；S05/B19/B20 | CLOSED/MISSING_DATA/HUMAN_REVIEW 可复现 | ✅ 通过 |
| F13 | 安全门与人工升级 | `test_safety.py` / `test_safety_variants.py` / `test_safety_b24.py`；S09/B13/B14/B24 | 改药/停药/调剂量等越权动作执行数为 0 | ✅ 通过 |
| F14 | 决策解释及运行追踪 | `trace RUN_ID`；各场景 | `run_id`/证据/工具/结果/错误可追溯 | ✅ 通过 |
| F15 | 极简 Web 客户端 | 后端接口就绪（`docs/api_contract.yaml`）；页面由 C 负责 | Web 读真实 API，不在前端算医学判断 | ⏳ 后端就绪，前端待 C |
| F16 | 站内待办提醒 | `services/notifications.py`；B19 | 新任务/待答/到期复评产生可查询提醒 | ✅ 通过（后端） |
| F17 | CLI 命令行客户端 | `cli/main.py`（15 子命令）；`python -m cli.main --help` | CLI 查询/录入/答复并与 API 状态一致 | ✅ 通过 |
| F18 | 后端 API 与持久化 | `test_api.py`（10 例） | 重启不丢数据，接口与 SQLite 一致 | ✅ 通过 |
| F19 | 自动化场景测试 | `scripts/run_scenarios.py`；全部 33 场景 | 可指定单场景/全量运行，隔离数据环境 | ✅ 通过 |
| F20 | 实测结果与复现报告 | `evaluation/reports/*.json` | 报告含 commit/模式/命令/日志/限制 | ✅ 通过 |
| F21 | 主动询问与信息补全 | `test_missing_data_triggers_question_then_resume`；S02/B10/B11 | WAITING_USER 持久化，回答/拒答/中断可恢复 | ✅ 通过 |
| F22 | 多事件协调与优先级 | `test_multi_event_merge_and_priority`；S03/B18 | 事件排序/任务合并/冲突检查/去重正确 | ✅ 通过 |
| F23 | 计划协商与动态重规划 | `test_negotiation_updates_task_and_saves_version`；S04/B12 | 普通任务可协商，医疗事项不可自动修改，版本可审计 | ✅ 通过 |
| F24 | 知识检索与证据约束 | `test_knowledge.py` / `test_knowledge_question_cites_source`；S07/S08/B16/B17/B23 | 有来源才引用，证据不足拒绝臆测 | ✅ 通过 |
| F25 | 长期偏好记忆 | `test_preference_applies_to_new_tasks`；B12/B24 | 明确确认的偏好跨运行有效，新值覆盖旧值留痕 | ✅ 通过 |
| F26 | 决策自检与不确定性 | `test_safety.py`（10 例）/ `test_no_evidence_blocks_claim`；B17/B23/B24 | 证据不足/工具失败/冲突/越权均不伪报成功 | ✅ 通过 |

## 测试模式和证据要求

### Mock 回归

- 使用确定性 Mock LLM，只固定模型输出，不伪造数据库或工具结果。
- 每个场景独立初始化数据库或命名空间。
- 运行后保存场景 ID、代码版本、规则版本、命令、Actual、日志和数据库快照。

### 真实模型 smoke test

- 与 Mock 回归单独统计，当前状态 **NOT RUN**（本机未提供真实厂商模型密钥，作为已知限制放行）。
- 只验证模型接入、结构化工具调用和错误恢复；不能用真实模型结果替换场景 Expected。

### 安全验收

- S09 / B13 / B14 / B24 为发布阻断场景。
- 停药、改药、改变胰岛素剂量、诊断等禁止动作的实际执行次数为 0（`audit_log.decision='reject'` 计数 = 0）。
- 未解决 P0/P1 缺陷为 0（BUG-B24-001 已由 A 修复并经 B 复验关闭）。

## 验收结论

- F01-F26 中除 F15 前端页面（C 负责）外，其余功能均有真实 pytest 用例 + 场景证据，状态为「通过」。
- 142 项 pytest（A 116 + B 2 + 24 场景参数化）全绿；33 个场景全 PASS；禁止动作执行数 0；无未解决 P0/P1。
- CGMacros 真实数据集验证已闭环（见 `docs/public_validation_dataset.md`），作为 F03/F04/F05/F06/F18/F19/F20/F21/F24/F26 的辅助证据，不产生临床疗效结论。
