# AGENTS.md —— 本项目的工作规则（三人 + Codex）

项目：`diabetes-agent`（糖衡智管）。单 Agent 架构，演示作品，非临床软件。

## 1. 不可违反的边界

1. **只开发一个 Agent**。F21–F26 是同一个 Agent 的状态机、工具集、记忆层与校验层扩展，
   不得拆成多个"会聊天的 Agent"。
2. **禁止医疗动作**：不诊断、不开处方、不更改用药/胰岛素剂量、不终止治疗。
   高风险只升级人工专业复核（`reviews.branch=HUMAN_REVIEW`）。
3. **所有患者必须是合成虚构数据**（`patients.is_synthetic=1`）。不得接入真实患者信息，
   不得把服务公开部署为真实患者服务。
4. **不许造假**：
   - 不得把 mock 规划结果写成真实模型输出；
   - 不得硬编码演示结果或静态 JSON 冒充真实执行；
   - 工具失败、数据库不一致必须显式记录（`TOOL_EXECUTION_FAILED` / `POSTCHECK_MISMATCH`）；
   - 测试未通过就写未通过，不得改 `Expected` 迁就实现。

## 2. 文件所有权

| 成员 | 可修改目录 | 交接物 |
| --- | --- | --- |
| A（功能开发） | `backend/`、`cli/`、`config/`、`scripts/`、`knowledge/`、`data/`、`tests/unit`、`tests/integration`、`tests/api`、`docs/` | 提交版本 + 文件地图 + 可执行命令与输出 |
| B（验证纠错） | `evaluation/`、`tests/e2e`、`docs/test_plan.md`、`docs/bug_log.md`、`docs/release_report.md`；`bugfix/*` 分支可改后端 | BUG-ID + 输入 + Expected/Actual + 根因 + 回归报告 |
| C（前端与材料） | `frontend/`、`presentations/`、`media/` | Web 操作说明、截图/录屏、PPT 与视频 |

跨目录修改必须先沟通：**接口变更由 A 提案，B/C 共同确认**。

## 3. Git 规则

- 分支：`main`（经 B 验收可发布）、`feature/backend-*`（A）、`feature/frontend-*`（C）、
  `qa/tests-*`（B）、`bugfix/BUG-*`、`presentation/*`。
- 未验收不合并 `main`。
- 提交前确认 `git status` 中没有 `.env`、`*.db`、`vendor/`、`wheels/`。

## 4. 每次给 Codex 下达功能任务的固定要求

1. 先读 `docs/mvp_spec.md`、`docs/api_contract.yaml`、`docs/PROJECT_FILE_MAP.md` 与当前代码。
2. 明确本次允许修改的目录。
3. 必须有真实实现、可复现命令、实际输出、数据库或日志证据。
4. 新增/修改/重命名文件后，同步更新 `docs/PROJECT_FILE_MAP.md`（不能写不存在的路径）。
5. 完成后给出：命令、输出摘要、`run_id`、涉及文件、未完成项。

## 5. 质量门槛（合并前）

- `python -m pytest` 全绿；`python scripts/run_scenarios.py` 全绿。
- 新增功能至少 1 个正常用例 + 1 个异常用例。
- 禁止动作实际执行次数为 0（`GET /api/system/audit` 的 `forbidden_executed`）。
- `python -m cli.main health` 与 `GET /api/health` 真实可用。

## 6. 代码风格

- Python 3.11+，类型标注优先，模块内注释用中文。
- 业务规则放 `config/*.yaml`，不要散落在代码里。
- 写数据库必须带上 `patient_id` 过滤，避免跨患者串数据。
- 任何写操作都要能被重复调用而不产生重复副作用（幂等）。
