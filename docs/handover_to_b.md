# 交接说明：A → B（功能完成后待验证清单）

日期：2026-11-02　｜　版本：0.1.0　｜　Git：`main` 分支已 init，**尚未 commit（本机未配置 Git 身份）**
数据库：`data/runtime/diabetes_agent.db`（可随时 `python scripts/reset_demo.py` 重建）

## 1. 已交付能力（A 负责部分）

| 范围 | 状态 | 证据 |
| --- | --- | --- |
| F01–F14 主线（患者/记录/状态/事件/触发/调度/Agent/工具/任务/复评/安全/轨迹） | 完成 | `python -m pytest` 82 项全绿 |
| F15/F16 后端接口（页面由 C 实现） | 完成 | `docs/api_contract.yaml` |
| F17 CLI（15 个子命令） | 完成 | `python -m cli.main --help` |
| F18 API + SQLite 持久化 | 完成 | `GET /api/health` 实测 |
| F19/F20 场景执行入口与报告 | 完成（示例 9 个场景） | `python scripts/run_scenarios.py` → 9/9 |
| F21–F26 六项增强 | 完成 | 集成用例 + 场景 S02–S08 |
| 文档 | 完成 | `docs/` 全套 + `AGENTS.md` |

**未完成/受限**：真实厂商模型 smoke test（无密钥）；前端页面（C）；≥30 个场景（B）。

## 2. 复现步骤（B 请按此独立验证）

```powershell
python -m pip install -e ".[dev]"     # 或使用 README 的离线 vendor 方式
python scripts/reset_demo.py
python -m pytest
python scripts/run_scenarios.py
python -m cli.main health
python -m cli.main serve --port 8000
```

## 3. 建议的验证重点（按 B 的测试组）

1. **数据一致性**：CLI 与 HTTP 对同一患者返回同一状态、同一任务、同一 run 轨迹
   （`python -m cli.main patient state P001` vs `GET /api/patients/P001/state`）。
2. **自动触发真实性**：只调用 `POST /patients/{id}/records`，不点击任何"运行"接口，
   确认 `agent_runs` 新增且 `trigger_type=record_created|event_detected`。
3. **幂等**：同一记录重复提交 → `duplicate=true` 且不新增 run；`automation/tick` 连点两次
   → 第二次 `processed` 中无 `review_due`。
4. **三分支**：完成任务 → `CLOSED`；推进时钟不完成 → `MISSING_DATA`；低血糖/危险症状 → `HUMAN_REVIEW`。
5. **安全**：要求停药/改剂量/开药/诊断 → `status=blocked`，`audit_log` 有 reject，
   `GET /api/system/audit` 的 `forbidden_executed` 应为 0。
6. **证据约束**：知识问答必须带 `anchor` 与 `source_url`；无关问题必须出现 `NO_EVIDENCE`。
7. **偏好**：改时间后偏好 `08:00` 生效于新任务；`pref clear` 后不再影响。
8. **real 模式**：配置真实端点后跑 `python -m cli.main run P001`，确认 `agent_runs.llm_mode=real`；
   若无法配置，请在报告中记录为"未验证"，不要用 mock 结果替代。

## 4. 已知风险（请优先构造场景）

- 低血糖升级依据"最近 3 天记录"，数据断档可能漏报（构造断档场景）。
- 任务去重窗口 72h，跨窗口同类任务可能重复（构造边界场景）。
- 偏好只应影响非医疗任务时间，若影响用药类任务属 P0。
- SQLite 单写锁，并发写入未压测。

## 5. 交接件清单

- 代码：`backend/`、`cli/`、`config/`、`knowledge/`、`data/`、`scripts/`
- 契约：`docs/api_contract.yaml`、`docs/data_dictionary.md`
- 地图：`docs/PROJECT_FILE_MAP.md`（文件、路由、功能映射、调用链）
- 测试：`tests/`（A 提供）+ `evaluation/scenarios/`（B 扩充）+ `evaluation/README.md`（格式）
- 运行证据：`docs/setup_and_run.md`（本次真实输出）、`evaluation/reports/*.json`
- 协作规则：`AGENTS.md`
