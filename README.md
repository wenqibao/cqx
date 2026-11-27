# 糖衡智管 · diabetes-agent

## 直接体验当前工作台

仓库已附带本地工作台的14位患者、73条健康记录，以及随访、任务、复评和完整运行历史。首次启动会导入体验数据，后续启动保留操作进度。

```powershell
python -m pip install -e ".[dev]"
python scripts/start_patient_experience.py
```

另开终端：

```powershell
cd frontend
npm ci
$env:VITE_API_MODE="http"
$env:VITE_API_BASE_URL="http://127.0.0.1:8000/api"
npm run dev -- --host 127.0.0.1 --port 5180 --strictPort
```

打开 [监管工作台](http://127.0.0.1:5180)。患者入口、真实模型配置、数据恢复与核对步骤见 [患者体验数据包](data/patient_experience_pack/README.md)。本入口使用v0.3.7后端；下方早期开发记录保留作为历史参考。

面向**稳定期成年 2 型糖尿病患者**的日常健康管理 Agent（参赛演示作品）。

> ⚠️ 本项目是比赛演示系统，**不是医疗器械软件**：不诊断、不开处方、不更改用药或胰岛素剂量；
> 所有患者都是 `data/demo_patients/` 下的合成虚构病例；高风险情况一律升级人工专业复核。

## 1. 这个项目做了什么

一个 Agent（不是多个）在后台持续完成健康管理闭环：

```
患者数据/反馈 → Patient State → 事件检测 → Agent 读取状态/知识/历史
→ 缺信息时主动询问 → 多事件综合与优先级 → 证据约束规划 → 安全门与自检
→ 真实工具调用 → 任务/偏好持久化 → 到期自动复评 → 执行轨迹（run_id）
```

F01–F26 全部业务能力由成员 A 实现：数据库、Agent Core、工具、记忆、知识检索、安全校验、
自动调度、CLI、HTTP API 与后续给 Web 前端使用的接口。

## 2. 快速开始

要求：Python 3.11+（本机验证用 3.13.1），Windows / macOS / Linux 均可。

```powershell
# 1) 安装依赖（正常联网环境）
python -m pip install -e ".[dev]"

# 2) 写入 3 个合成演示患者 + 知识索引
python scripts/reset_demo.py

# 3) 检查
python -m cli.main health
python -m cli.main --help

# 4) 启动 HTTP API
python -m cli.main serve --port 8000
# 或：uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/docs 可见交互式 API 文档，`GET /api/health` 返回真实健康检查。

> **离线/受限环境**：若 `pip` 无法写入临时目录，可使用仓库内的离线引导脚本
> （纯 Python wheel 直接解包，不经过 pip 的临时目录）：
> ```powershell
> python tools/getpkg.py fastapi==0.115.6 starlette==0.41.3 uvicorn==0.32.1 anyio sniffio idna h11 typing_extensions typing-inspection annotated-types annotated_doc
> python tools/install_wheels.py vendor
> $env:PYTHONPATH="$PWD/vendor"
> ```
> 该目录已在 `.gitignore` 中，不会进入仓库。

## 3. 一分钟演示（CLI）

```powershell
# 录入一条血糖记录 → 自动检测事件 → 自动启动 Agent（不需要点击任何按钮）
python -m cli.main record add P001 fasting_glucose 9.6
python -m cli.main patient state P001        # 状态/趋势/缺失字段
python -m cli.main task list P001            # Agent 真实创建的任务

# 查看这次运行的完整轨迹（输入、计划、工具调用、数据库核对、拒绝码）
python -m cli.main trace RUN-xxxxxxxxxxxx

# 知识问答：必须带可定位出处
python -m cli.main run P003 --message "为什么需要连续记录血糖"

# 计划协商：把记录任务改到早上，并保存为偏好
python -m cli.main run P003 --message "我19:00上班，改成08:00记录步数"

# 演示时钟推进 2 天 → 后台复评自动执行（CLOSED / MISSING_DATA / HUMAN_REVIEW）
python -m cli.main clock --advance 172800
python -m cli.main automation tick
python -m cli.main review list P001
```

## 4. 测试与验收

```powershell
python -m pytest                     # 单元 + 集成 + API + 场景回放，共 149 项（33 个场景 e2e + 7 项并发回归）
python scripts/run_scenarios.py      # 回放 evaluation/scenarios/*.json 并生成报告
```

- `tests/`：A 提供的单测与集成测试（F01–F26 均可追溯到用例）。
- `evaluation/scenarios/`：固定合成场景与预期（成员 B 按同一格式扩充到 ≥30 个）。
- `evaluation/reports/`：场景回放报告（含 `llm_mode`、run_id、通过/失败）。

## 5. 运行模式：mock 与 real 必须分清

| 模式 | 说明 | 记录字段 |
| --- | --- | --- |
| `mock`（默认） | 由 `planning/planner.py` 的**确定性策略**决策，无模型调用，可离线复现 | `agent_runs.llm_mode = mock`，模型名 `deterministic-planner` |
| `real` | OpenAI 兼容 `/chat/completions` 端点 + 原生 tool calling | `agent_runs.llm_mode = real`，模型名为实际配置 |

`mock` 模式**不冒充**真实模型输出：每次运行都会把模式写进数据库，API/CLI/报告都会透出。
`real` 模式在缺少 `AGENT_LLM_BASE_URL / API_KEY / MODEL` 时直接报错，**不会静默降级**。

```powershell
$env:AGENT_LLM_MODE="real"
$env:AGENT_LLM_BASE_URL="https://your-endpoint/v1"
$env:AGENT_LLM_API_KEY="sk-..."
$env:AGENT_LLM_MODEL="your-model"
python -m cli.main run P001
```

## 6. 目录结构

```
backend/app/            业务后端（A 负责）
  api/                  HTTP 路由（患者/记录/事件/Agent/任务/复评/偏好/调度）
  schemas/              Pydantic 输入输出
  db/                   SQLite 连接、建表 SQL、演示时钟
  services/             患者、记录、状态、通知
  events/               F05 事件检测
  automation/           F06 触发、F07 调度
  agent/                F08/F10 Agent、工具、模型接入
  planning/             F09/F22 规划与优先级
  tasks/                F11/F23 任务与版本
  reviews/              F12 复评三分支
  safety/               F13/F26 安全门与自检
  questioning/          F21 主动询问
  knowledge/            F24 检索与证据
  memory/               F25 偏好
  audit/                F14 轨迹
cli/                    F17 命令行
config/                 事件/任务/安全/复评规则（YAML，可调）
knowledge/              有限知识包（带来源与版本）
data/demo_patients/     仅合成演示病例
evaluation/scenarios/   B 的场景与预期
tests/                  A 的单测/集成/API/场景回放
docs/                   契约、字段、文件地图、测试计划、演示脚本
frontend/               C 的独立前端（本仓库只留接口约定）
scripts/                重置演示数据、场景回放
```

## 7. 安全边界（B 的发布闸门与此对应）

- 禁止动作：诊断、处方、改药、停药、调整胰岛素剂量、终止治疗 —— 命中即拒绝并写入 `audit_log`。
- 红旗信号（低血糖 <3.9、显著高血糖 ≥16.7、危险症状）只升级人工复核，不给处置建议。
- 无证据结论会被 `NO_EVIDENCE` 拦截；工具失败/数据库不一致会被 `POSTCHECK_MISMATCH` 记录，
  不会写成"已成功执行"。
- 所有患者 `is_synthetic=1`；本服务只应绑定 `127.0.0.1` 用于本机演示。

## 8. 已知限制

- 不是临床有效性验证；测试只说明特定合成场景下的系统行为。
- 知识包只有 4 篇摘要（中文改写），检索为词频/IDF 打分，不含向量检索。
- `real` 模式已端到端验证（本地 OpenAI 兼容 stub → 原生 tool calling → 安全校验 → 真实写库，
  见 `tests/integration/test_real_mode_stub.py`），但本机没有真实厂商模型密钥，因此
  **尚未产出真实模型 smoke test 记录**；B 接入真实端点后需补该报告。
- 前端（C 负责）不在本仓库内实现，仅提供 API 契约与 Mock 约定。

## 9. 文档索引

- [`docs/setup_and_run.md`](docs/setup_and_run.md)：从零安装、启动、验证命令与本次真实输出
- [`docs/mvp_spec.md`](docs/mvp_spec.md)：F01–F26 需求合同与验收口径
- [`docs/api_contract.yaml`](docs/api_contract.yaml)：API 契约
- [`docs/data_dictionary.md`](docs/data_dictionary.md)：数据表字段说明
- [`docs/PROJECT_FILE_MAP.md`](docs/PROJECT_FILE_MAP.md)：真实文件地图与功能映射
- [`docs/test_plan.md`](docs/test_plan.md)：测试计划骨架（交给 B）
- [`docs/handover_to_b.md`](docs/handover_to_b.md)：A→B 交接清单与验证重点
- [`docs/demo_script.md`](docs/demo_script.md)：5 段演示脚本（交给 C 录制）
- [`evaluation/README.md`](evaluation/README.md)：场景文件格式
- [`AGENTS.md`](AGENTS.md)：三人协作与代码边界规则
