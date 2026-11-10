# DeepSeek 真实路径缺陷与修复

日期：2026-11-04；基线 main c5f787f；功能修复截至 27d8e3a。
原失败真实证据只保留在本地 evaluation/reports；源码与受控回归进入独立分支。以下**全部未由 B 独立复验**，修复后的真实模型场景未重跑，避免突破 6 次预算。

| 编号 / 级别 | 复现、根因及影响 | 修改与前后行为 | 针对性回归 |
| --- | --- | --- | --- |
| DS-01 / P1 | 本地 Stub 调用 search_knowledge：原特殊分支不经统一执行器，证据未完整回传模型、轨迹缺失；无法追溯 | agent/orchestrator.py：统一 _execute_action，完整 tool_call/tool_result 和实际结果消息；累计证据回传模型 | test_search_has_complete_trace_and_supplies_actual_quotes |
| DS-02 / P1 | 本地 Stub 无检索直接健康回答、声称已建任务、空输出等；原路径可能 completed | orchestrator.py：知识请求证据门、文本输出校验、虚假写入核对、空输出失败；允许无必要写操作的纯解释；部分失败如实保存 | test_knowledge_text_without_evidence_is_not_success、test_claimed_write_without_write_is_rejected、test_empty_output_is_failed_but_pure_explanation_is_allowed |
| DS-03 / P0 防护缺口 | 受控模型传其他患者 ID/其他患者 task_id；非法 args、无时区时间、跨轮多次 ask_user；原执行前校验不足 | safety/validators.py、orchestrator.py：工具参数形状、所有权、时间、累计动作/任务/问题上限；禁止访问其他患者、拒绝后不执行 | test_cross_patient_tool_arguments_never_execute、test_invalid_due_is_a_rejection_not_server_crash、test_malformed_tool_arguments_are_rejected、test_question_limit_is_cumulative_across_rounds |
| DS-04 / P1 | Stub 上游异常导致持久化 run 仍 running；原请求错误可能含厂商敏感正文；DeepSeek 原生工具协议配置需确定 | agent/llm.py、orchestrator.py：官方 DeepSeek 请求显式禁用 thinking；错误只留状态和类型，run 失败落库，无自动重试；保存安全响应元数据 | test_deepseek_payload_disables_thinking、test_upstream_error_finishes_persisted_run、test_provider_error_is_explicit_and_redacted（400/401/402/429/5xx/格式异常）、test_provider_timeout_does_not_retry |
| DS-05 / P1 | R01 真正检索 KD-001-C003 等，respond 引用被误判 NO_EVIDENCE | knowledge/search.py、validators.py：实际 chunk_id 随来源返回且纳入本轮证据允许集合；虚假引用仍拒绝 | test_real_citation_chunk_and_explicit_non_diagnosis_are_allowed；保留 R01 原失败 |
| DS-06 / P1 | R01“不作诊断”、R02“不涉及任何用药或剂量调整”、R03“不构成诊断/任何用药调整请咨询医生”等被误拦；原否定窗口还可能掩盖后分句的肯定指令 | safety/gate.py、validators.py、orchestrator.py：分句限定否定范围，遍历所有匹配，可信固定拒绝话术；仅生成文本启用否定/通用转介识别，患者输入路径仍保守；未修改配置阈值/白名单 | test_disclaimer_cannot_hide_later_forbidden_instruction、test_generated_unsafe_text_is_blocked、test_real_recording_task_with_no_medication_change_disclaimer、test_generated_refusal_and_generic_doctor_referral_are_not_medical_actions；原 B24 仍通过 |
| DS-07 / P1 | 原 forbidden_executed 将 reject 审计算成“执行”；拦截越多反而计数越高 | safety/gate.py：查询成功 tool_result 的对应调用并核对工具/文本；另行查 SQLite 副作用，非硬编码归零 | test_rejection_count_is_not_forbidden_execution_count |
| DS-08 / P1 | R03 回答“记不清”后恢复只给模型回答文字，缺原问题/字段/不确定性，引起重复提问 | orchestrator.py：将已保存的原问题、target_field、结构化 answer 和 uncertain 加入状态，明确不把未知补成事实；意图仍遵守合同 | test_answer_resume_includes_original_question_and_uncertainty；真实两轮记录不变，尚不能保证修复后模型不再追问 |
| DS-09 / P1 | R04 update_task 已成功，额外 save_preference kind=reminder_time/source=中文说明失败；schema 任意字符串没有声明实际枚举 | agent/llm.py、safety/validators.py：从真实 memory 常量暴露 kind/source enum，非法值在执行前拒绝；未添加新偏好类型 | test_preference_tool_advertises_actual_backend_enums；真实 R04 仍 FAIL，不改历史 |
| DS-10 / P1 | R04 task_versions 已关联 run，但 GET run.tasks=[]：原 trace 只关联创建来源，遗漏更新 | audit/trace.py：纳入 task_versions.run_id，保持原 API 形状；修复后只读查询看到任务 | test_updated_task_is_associated_with_run_trace；deepseek_final_readonly.json |

修复前新增回归实际 16 failed/1 passed，最终全量 183 passed、33 场景通过。统计中包含 Stub 与 Mock，不计入真实通过率。既有 SQLite check_same_thread=False、busy_timeout 和并发实现已在基线，**没有重复开发或替换**，通过原测试复验。

安全剩余限制：关键词/正则检查不能覆盖任意语言意图；生成文本通用转介识别修复需 A 重点审查、B 复验肯定指令与免责声明混合样例。既有知识包的教育性用药文字仍可能被保守拒绝；不能用放宽规则追求真实场景全通过。R03 的 prompt 补充是上下文修复，若后续真实复验仍重复追问，需另复现再修复。

其他本地验收工具问题：首次证据收集器将 patients 主键误写为 patient_id，已改为 id 并只读重采；浏览器夹具初始患者与选择器假设修正，没有重发收费业务。这些是测试工具问题，不计作产品缺陷。预算守卫和报告目录忽略规则用于防止超额调用及提交本地日志，不替代业务测试。

C 前端的只读复现与交接字段见 `docs/deepseek_next_actions.md`；本次没有修改 frontend/。
