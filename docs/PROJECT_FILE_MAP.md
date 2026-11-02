# PROJECT_FILE_MAP.md

> 本文件由成员 A 维护，必须与真实代码一致；不写不存在的路径。
> 最近更新：2026-11-02（A0–A9 工作包完成）。Git：仓库已 `git init -b main`，因本机未配置 Git 身份，尚无初始 commit。

## 1. 环境与启动

| 项 | 值 |
| --- | --- |
| Python | 3.11+（本机验证 3.13.1） |
| 运行依赖 | fastapi 0.115.6 / starlette 0.41.3 / uvicorn 0.32.1 / pydantic 2.13.4 / PyYAML 6.0.1 / python-dotenv 1.0.0 / httpx 0.28.1 |
| 测试依赖 | pytest 8.1.1 |
| 数据库 | SQLite，默认 `data/runtime/diabetes_agent.db`（`DIABETES_DB_PATH` 可覆盖；测试用临时库） |
| CLI | `python -m cli.main ...`（argparse，无额外依赖） |
| API | `uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` |
| 演示重置 | `python scripts/reset_demo.py` |
| 场景回放 | `python scripts/run_scenarios.py` |
| 离线依赖引导（本机受限环境用） | `tools/getpkg.py` 下载 wheel；`tools/install_wheels.py` 直接解包到 `vendor/` |
| PDF 文本抽取（一次性分析用，非产品代码） | `tools/pdftext.py` |

## 2. 数据表（`backend/app/db/schema.sql`）

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `patients` | F01/F02 患者档案 | id, name, age, duration_years, goals(JSON), constraints(JSON), is_synthetic |
| `health_records` | F03 健康记录 | patient_id, kind, value, unit, recorded_at, payload, dedupe_key(唯一) |
| `state_snapshots` | F04 状态快照 | patient_id, version, snapshot(JSON) |
| `events` | F05 事件 | code, severity, status, evidence(JSON), dedupe_key(唯一) |
| `agent_runs` | F08/F14 运行 | trigger_type, llm_mode, model_name, status, plan(JSON), output(JSON) |
| `agent_steps` | F14 轨迹 | run_id, step_no, phase, kind, tool_name, status, code |
| `tasks` | F11 任务 | task_type, status, priority, due_at, version, dedupe_key(唯一) |
| `task_versions` | F23 版本 | task_id, version, change_kind, reason, changed_by |
| `questions` | F21 提问 | patient_id, target_field, status, answer(JSON), resume_payload(JSON) |
| `reviews` | F12 复评 | branch(CLOSED/MISSING_DATA/HUMAN_REVIEW/PENDING), status, scheduled_for |
| `preferences` | F25 偏好 | kind, value, source, status(active/superseded/cleared) |
| `knowledge_docs` / `knowledge_chunks` | F24 知识 | title, publisher, version, source_url, anchor, text |
| `evidence_items` | F24 证据 | run_id, doc_id, chunk_id, anchor, quote, citation |
| `notifications` | F16 站内提醒 | kind, title, status, ref_type, ref_id |
| `automation_jobs` | F07 调度 | kind, patient_id, ref_id, run_at, status, attempts（唯一键幂等） |
| `idempotency_keys` | 幂等键 | key, scope, result |
| `audit_log` | F13/F14 审计 | actor, action, decision(allow/reject/escalate), code |
| `app_meta` | 演示时钟等 | key, value |

## 3. 配置项

| 文件 | 内容 | 被谁读取 |
| --- | --- | --- |
| `config/event_rules.yaml` | 8 条事件检测规则（阈值/窗口/严重度） | `backend/app/events/detector.py` |
| `config/task_rules.yaml` | 事件→任务模板、优先级权重、去重窗口、可合并任务类型 | `backend/app/planning/planner.py`、`backend/app/tasks/service.py` |
| `config/safety_rules.yaml` | 禁止意图关键词、红旗信号、工具白名单、动作上限 | `backend/app/safety/gate.py`、`backend/app/safety/validators.py` |
| `config/review_rules.yaml` | 复评延迟、三分支条件、数据充分性阈值、调度重试 | `backend/app/reviews/service.py`、`backend/app/automation/scheduler.py` |
| `knowledge/INDEX.yaml` | 知识包清单与检索参数（top_k、min_score） | `backend/app/knowledge/index.py`、`search.py` |
| `.env`（不入库） | 运行模式、模型端点、数据库路径、前端地址 | `backend/app/config.py` |

## 4. CLI 命令（`cli/main.py`）

| 命令 | 作用 | 对应功能 |
| --- | --- | --- |
| `version` / `health` | 版本、数据库与模式检查 | A0 |
| `patient list/show/state` | 患者、档案完整性、状态快照 | F01/F02/F04 |
| `record list/add/import` | 录入、导入（CSV/JSON）、自动触发 | F03/F06 |
| `event list/scan` | 事件查询与手动检测 | F05 |
| `run PATIENT [--message]` | 运行 Agent | F08–F10/F21–F26 |
| `trace RUN_ID` | 完整轨迹（步骤、证据、任务、复评） | F14 |
| `task list/show/complete/reschedule` | 任务管理与改期（版本） | F11/F12/F23 |
| `ask list/answer` | 待答复问题与回答后恢复执行 | F21 |
| `pref list/set/clear` | 偏好读取/覆盖/清除 | F25 |
| `knowledge list/search` | 知识清单与检索（带出处） | F24 |
| `review list/evaluate/resolve/tick` | 复评三分支与人工结案 | F12/F13 |
| `notify list/read` | 站内提醒 | F16 |
| `automation tick/jobs` | 推进调度、查看作业 | F07 |
| `clock --advance/--reset` | 演示时钟（测试可复现） | F07 |
| `demo reset/seed` | 演示数据重置 | A9 |
| `serve` | 启动 HTTP API | F18 |

## 5. HTTP API（`backend/app/api/routes_*.py`，前缀 `/api`）

| 方法 | 路径 | 作用 | 功能 |
| --- | --- | --- | --- |
| GET | `/health` | 真实健康检查（DB + 模式） | A0 |
| GET | `/version` | 版本 | A0 |
| GET | `/patients` | 患者列表 | F01 |
| POST | `/patients` | 新建合成患者 | F01/F02 |
| GET | `/patients/{id}` | 档案 + 完整性 | F02 |
| GET | `/patients/{id}/state` | 状态快照（聚合/趋势/缺失字段） | F04 |
| GET | `/patients/{id}/state/history` | 历史快照版本 | F04 |
| GET | `/patients/{id}/records` | 记录列表 | F03 |
| POST | `/patients/{id}/records` | 录入并自动触发 Agent | F03/F06 |
| POST | `/patients/{id}/records/import` | CSV/JSON 回放导入 | F03 |
| GET | `/patients/{id}/events` | 事件列表 | F05 |
| POST | `/patients/{id}/events/scan` | 手动事件扫描 | F05 |
| POST | `/patients/{id}/agent/runs` | 运行 Agent | F08–F10 |
| GET | `/patients/{id}/runs` | 运行列表 | F14 |
| GET | `/runs/{run_id}` | 运行轨迹 | F14 |
| GET | `/patients/{id}/tasks` | 任务列表 | F11 |
| GET | `/tasks/{id}` | 任务 + 版本 | F11/F23 |
| POST | `/tasks/{id}/complete` | 完成并触发复评 | F12 |
| POST | `/tasks/{id}/reschedule` | 改期（保留版本） | F23 |
| GET | `/tasks/{id}/versions` | 版本历史 | F23 |
| GET | `/patients/{id}/questions` | 待答复问题 | F21 |
| POST | `/questions/{id}/answer` | 回答并恢复执行 | F21 |
| GET | `/patients/{id}/reviews` | 复评列表 | F12 |
| POST | `/reviews/{id}/resolve` | 人工复核结案 | F13 |
| GET | `/patients/{id}/notifications` | 站内提醒 | F16 |
| POST | `/notifications/{id}/read` | 标记已读 | F16 |
| GET | `/patients/{id}/preferences` | 偏好 | F25 |
| POST | `/patients/{id}/preferences` | 保存偏好并重排任务 | F25 |
| DELETE | `/patients/{id}/preferences/{kind}` | 清除偏好 | F25 |
| GET | `/knowledge` | 知识包清单 | F24 |
| POST | `/knowledge/reindex` | 重建索引 | F24 |
| GET | `/knowledge/search?q=` | 检索并返回出处 | F24 |
| POST | `/automation/tick` | 推进时钟并执行到期作业 | F07 |
| GET | `/automation/jobs` | 调度作业列表 | F07 |
| POST | `/automation/clock` | 设置演示时钟 | F07 |
| GET | `/system/audit` | 审计日志 + 禁止动作计数 | F13/F14 |
| GET | `/system/mode` | 当前 mock/real 模式 | A0 |
| POST | `/admin/reset` | 演示重置（本地） | A9 |

## 6. F01–F26 → 代码映射

| 功能 | 主要实现 | 验证命令 / 用例 |
| --- | --- | --- |
| F01 演示患者管理 | `services/patients.py` | `python -m cli.main patient list`；`tests/api/test_api.py::test_patient_crud_and_state` |
| F02 基础健康档案 | `services/patients.py::profile_completeness`、`schemas/models.py` | `test_patient_crud_and_state` |
| F03 数据录入与导入 | `services/records.py` | `tests/unit/test_records.py`（9 例） |
| F04 状态记忆与趋势 | `services/state.py` | `tests/unit/test_state.py`（4 例） |
| F05 事件检测 | `events/detector.py` | `tests/unit/test_events.py`（6 例） |
| F06 新增数据主动触发 | `automation/triggers.py::after_records` | `test_record_save_triggers_event_and_agent` |
| F07 复评到期自动调度 | `automation/scheduler.py` | `test_scheduler_tick_runs_due_review_without_click`、`test_scheduler_is_idempotent` |
| F08 Agent 自主决策 | `agent/orchestrator.py` | `test_agent_creates_task_and_trace_is_reproducible` |
| F09 个性化任务规划 | `planning/planner.py` | `test_multi_event_merge_and_priority` |
| F10 真实工具调用 | `agent/tools.py`（14 个工具） | 每次 run 的 `agent_steps` 均有 tool_call/tool_result |
| F11 健康任务管理 | `tasks/service.py` | `tests/integration/test_agent_flow.py` |
| F12 动态复评三分支 | `reviews/service.py` | `test_task_completion_leads_to_closed_review`、`test_review_missing_data_branch` |
| F13 安全门与人工升级 | `safety/gate.py` | `tests/unit/test_safety.py`、`test_forbidden_request_blocked_and_audited` |
| F14 决策解释与追踪 | `audit/trace.py` | `python -m cli.main trace RUN_ID` |
| F15 Web 客户端（前端） | 后端接口由 A 提供，页面由 C 实现 | `docs/api_contract.yaml` |
| F16 站内待办提醒 | `services/notifications.py` | `GET /api/patients/{id}/notifications` |
| F17 CLI | `cli/main.py` | `tests/api`…（CLI 由 `docs/setup_and_run.md` 命令验证） |
| F18 API 与持久化 | `backend/app/main.py`、`db/connection.py` | `tests/api/test_api.py`（10 例） |
| F19 自动化场景测试 | `scripts/run_scenarios.py` + `evaluation/scenarios/` | `python scripts/run_scenarios.py`（9/9） |
| F20 实测结果与报告 | `evaluation/reports/*.json` | 同上，报告含 run_id/mode/通过数 |
| F21 主动询问与补全 | `questioning/service.py` | `test_missing_data_triggers_question_then_resume` |
| F22 多事件协调与优先级 | `planning/planner.py::build_event_plan` | `test_multi_event_merge_and_priority` |
| F23 协商与动态重规划 | `planning/planner.py::build_negotiation_plan`、`tasks/service.py::reschedule_task` | `test_negotiation_updates_task_and_saves_version` |
| F24 知识检索与证据约束 | `knowledge/*` | `tests/unit/test_knowledge.py`、`test_knowledge_question_cites_source` |
| F25 长期偏好记忆 | `memory/preferences.py` | `test_preference_applies_to_new_tasks` |
| F26 决策自检与不确定性 | `safety/validators.py` | `tests/unit/test_safety.py`、`test_no_evidence_blocks_claim` |

## 7. 调用链

```
POST /patients/{id}/records
  → services.records.add_record                 （校验 + 幂等去重）
  → automation.triggers.after_records
      → events.detector.detect_events            （规则判定 + 事件幂等）
      → automation.scheduler.enqueue_job         （agent_run 作业）
      → agent.orchestrator.run_agent
          → services.state.build_state           （F04 状态）
          → safety.gate.check_text / escalation_hits
          → knowledge.search + record_evidence   （F24 证据）
          → planning.planner.build_*             （F09/F21/F22/F23）
          → safety.validators.validate_plan      （F26 执行前）
          → agent.tools.execute                  （F10 真实写库）
          → safety.validators.post_execution_check（F26 执行后）
          → audit.trace.add_step / finish_run    （F14 轨迹）
      → services.state.save_snapshot
  → automation.scheduler.tick（后台线程或显式调用）
      → reviews.evaluate_review                  （F12 三分支）
```

## 8. 测试命令

```powershell
python -m pytest -q                 # 82 项：单元 + 集成 + API + 场景回放
python scripts/run_scenarios.py     # 9 个固定场景，生成 evaluation/reports/*.json
```

## 9. 文档索引

| 文件 | 作用 |
| --- | --- |
| `README.md` | 安装、演示、模式说明、限制 |
| `AGENTS.md` | 三人协作与代码边界规则 |
| `docs/setup_and_run.md` | 启动步骤与本次真实输出 |
| `docs/mvp_spec.md` | F01–F26 需求合同与全局验收口径 |
| `docs/api_contract.yaml` | API 契约（含已实现端点与计划端点） |
| `docs/data_dictionary.md` | 数据表字段、拒绝码 |
| `docs/test_plan.md` | 测试计划骨架（B 接管） |
| `docs/handover_to_b.md` | A→B 交接清单与验证重点 |
| `docs/demo_script.md` | 5 段演示脚本（C 录屏用） |
| `docs/reference/plan_extracted.txt` | 参赛计划书 PDF 的文本抽取（仅作需求参考，非项目文档） |
| `evaluation/README.md` | 场景文件格式与预期维护规则 |
| `frontend/README.md` | C 的前端接入约定（Mock/真实模式） |
| `presentations/README.md`、`media/README.md` | C 的材料与视频目录约定 |

## 10. 已知缺陷与限制

1. `real` 模式已由本地 OpenAI 兼容 stub 端到端验证（`tests/integration/test_real_mode_stub.py`：
   tool calling → 安全校验 → 真实写库 → `llm_mode=real`），但本机没有真实厂商模型密钥，
   **尚无真实模型 smoke test 数据**。
2. 知识检索为词频/IDF 打分（无向量检索），知识包仅 4 篇中文摘要。
3. `automation/tick` 是显式触发为主，uvicorn 启动时才会起轮询线程（`AUTOMATION_POLL_SECONDS`，测试置 0）。
4. SQLite 单写锁；并发写场景未做压测。
5. 前端（`frontend/`）尚未实现，仅提供契约与 Mock 约定。
6. 未做鉴权：仅允许 `127.0.0.1` 本机演示。
