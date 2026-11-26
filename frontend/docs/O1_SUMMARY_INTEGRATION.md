# O1 前端 summary 接入交接

2026-11-27，成员 C。开发自验记录，待 B 对候选提交独立核验。

## 代码与范围

- 后端基线 `dc383482a8de4e94009f27bb7d1659a48efc3a41`。
- 前端分支 `feature/frontend-agent-2day-outcomes`，从上述提交建立。
- 该后端提交已经包含 main `91e6c8d40c969d58d988bcebd8c0b502adabf82d`，仍位于 A 的分支。正式合并前需确认 A 的发布状态及目标 main。
- 本提交只修改 frontend/。A/B 后端、独立测试、场景和契约源文件保持原有归属。
- 候选完整 SHA 通过 `git rev-parse HEAD` 获取，并随提交交接。B 的结论绑定该实际代码树。

## 展示规则

运行详情读取顶层 summary，保持现有 URL。

| 字段 | 业务展示 |
| --- | --- |
| goal | 本次处理目标 |
| trigger.label / reason | 触发原因与来源说明 |
| completed | 已完成业务动作的唯一来源，工具名称沿用现有中文业务映射，保留 detail |
| unfinished | 未完成事项及实际失败原因，拒绝码只在必要时映射为中文提示 |
| waiting | 当前等待事项 |
| next_owner | 下一步责任人与具体动作 |
| partial_success | 部分处理未完成的提示 |
| refs / 原始 summary | 完整保留在运行日志，支持复制 |

waiting.kind 为 question 且有 id 时，顶部入口使用 `/followups?patient=实际患者&tab=questions&question=实际问题`。回答页沿用既有排序、滚动和回答框自动聚焦。入口直接使用运行详情已确认的对象，独立问题列表读取故障不会抹掉这个来源。

管理动作已在 summary 中展示时，下方仅展示其他工具返回记录，完整管理工具调用仍保留在技术日志。已有工具结果且都在上方表达时隐藏空区。真正没有工具轨迹的运行继续保留原有空提示。

Agent 原始回复作为沟通内容展示，业务全文保留一次。它不参与判断业务动作成功。summary 缺失或为 null 的历史响应继续使用已有展示与问题查询兼容路径。结构错误仍返回契约错误。

## 测试环境与方法

Node 24.22.3。当前机器默认 Node 22.11.0，首次安装缺少原生可选绑定，改用 Node 24 后重新执行 `npm ci --include=optional`，锁文件保持一致。

后端通过 `python frontend/tools/start-test-backend.py` 启动，使用本工作区独立的 `frontend/.runtime/workbench-test.db`，端口 8020，后端 Mock、真实 FastAPI/SQLite，关闭后台轮询。前端常规 E2E 使用 5180。

契约专项通过已有 contract-server.py 在 v0.3.6 源码快照和新库中运行，端口 8037，前端 5187，写入超时 60000ms。该组验证缺少 summary 的旧响应兼容。新增 run-summary.spec.ts 对 dc38348 的实际 summary 进行联调。

所有本机回环请求设置 `NO_PROXY=127.0.0.1,localhost,::1`。首次 pytest 因本机代理影响回环 HTTP 有 5 个失败，调整环境后完整重跑通过。

本轮未调用真实 DeepSeek 厂商。UI 受控反例明确使用 Playwright 路由覆盖，验证结构化结果与不一致回复、工具故障等展示行为。生产数据来源始终为真实接口。

## 检查结果

| 检查 | 实际结果 |
| --- | --- |
| npm ci / Node24 可选依赖安装 | 通过，审计 0 漏洞 |
| npm run typecheck | 通过 |
| npm test | 59 passed |
| npm run build | 通过 |
| python -m pytest | 572 passed |
| python scripts/run_scenarios.py --report D:/cqx-deliverables/o1-scenarios.json | 33/33 PASS |
| CLI 与 API health | ok，隔离后端 Mock，版本 0.3.6 |
| npm run test:contract | 14 passed，旧响应兼容 |
| 常规 E2E | 最终代码 27 passed（3.5 分钟），包含 3 条 O1 专项 |
| 新 summary 已纠正 warning 补查 | FAIL，O1-SUMMARY-WARN-01，来源待 A 修复 |
| 审计 | forbidden_executed=0，查询时 checked_tool_results=100 |

第一次全量 E2E 为 26 passed / 1 failed，失败来自 O1 新区未沿用既有“接下来”和工具中文映射。修正展示文案后 27/27 通过，原业务用例预期保持。随后修正空提示时发现真正无工具轨迹的旧用例需要保留原空提示，已按真实工具轨迹区分处理，原预期保持。

既有构建大于 500kB 的包体积提示、Ant Design 弃用提示仍可见。

## 本机可追踪证据

实际 API 录入并运行的证据患者 `O1-PROOF-a8470f16`，run_id 为 `RUN-68a89466edac`，问题为 `Q-bde2ad14d841`。读取详情确认 waiting.kind=question，并通过真实页面跳转确认对应回答框聚焦。

运行数据和测试产物位于当前工作区的忽略目录，完整复验时重新生成。

- `frontend/.runtime/o1-summary-api.json`。
- `frontend/.runtime/o1-summary-waiting.png`。
- `frontend/.runtime/o1-e2e-final.json`。
- `frontend/.runtime/v021/browser-results.json`。
- `D:/cqx-deliverables/o1-scenarios.json`。

普通 E2E 会更新既有历史截图和 JSON。提交前恢复这些自动生成的历史文件，交付本轮源码、测试和说明。

## B 的独立核验

1. 记录候选完整 SHA 和目标 main，确认后端基线。
2. 使用新的隔离测试数据库，执行 README 中依赖安装和启动。
3. 运行 `npm run typecheck`、`npm test`、`npm run build`。
4. 执行 `npm run test:e2e -- e2e/run-summary.spec.ts` 及常规全量 E2E。
5. 核查实际 API 的 summary 与页面，重点检查完成来源、未完成原因、partial_success 和问题定位。
6. 展开运行日志，确认完整 refs、编号、参数、回复及工具结果保留。
7. 对旧后端缺少 summary 的响应执行原契约专项，确认兼容。
8. 组合代码树或目标 main 改变时，对实际候选重新完成规定验收，通过后交维护者合并。

A 按文件所有权将 `frontend/docs/FILE_MAP_V2.md` 的本轮增量同步至根文件地图。B 独立核验和 main 合并仍待执行。

## O1-SUMMARY-WARN-01 · 后端来源问题 · OPEN

补查 dc38348 的新 summary 发现一项真实来源问题。旧契约 14 项通过代表旧响应兼容，本问题需要 A 修复后针对新 summary 再验。

复现使用独立合成数据库及受控 Python LLM Stub，model_name 为 controlled-stub-no-provider，无真实厂商请求。同一患者有两个普通任务，第一轮 schedule_review 未带 task_id 导致不能唯一确定任务，第二轮补上正确 task_id 后成功，第三轮正常收尾。

实际运行 `RUN-b474c6c83772` 返回以下状态。

| 字段 | Actual |
| --- | --- |
| run.status | completed |
| output.warnings 对应项 | resolved=true |
| summary.completed | 存在成功 schedule_review 和实际复评对象 |
| summary.unfinished | 仍包含已纠正的同一 TOOL_EXECUTION_FAILED |
| summary.partial_success | true |

Expected 为已被同一次运行成功纠正的错误只保留在原始轨迹和 resolved warning，对应原因不再作为最终 unfinished，也不单独导致 partial_success。未纠正失败、安全拒绝和 postcheck 不一致继续保留实际失败。

实际输出保存于 `frontend/docs/evidence/o1/summary-warning-source.json`，附验证模式、后端 SHA 和完整轨迹。前端按用户约定忠实显示该字段，本轮不自行过滤后端 unfinished。

源码定位为 `backend/app/agent/run_summary.py::build`。当前把 output.rejections 全量加入 unfinished，并从失败步骤再次补入错误。A 应复用执行器最终拒绝/纠正的语义，统一处理这两个来源，同时区分同一工具的不同错误及不同尝试，保持原始日志完整。

可在仓库根目录复现。

```python
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.audit import trace
from backend.app.db.connection import connect, iso, now
from backend.app.services import patients
from backend.app.tasks import service as tasks

with TemporaryDirectory() as directory:
    conn = connect(Path(directory) / "summary-warning.db")
    pid = "O1-WARNING"
    patients.create_patient(conn, {
        "id": pid, "name": "周明远", "age": 52,
        "duration_years": 5, "goals": ["保持记录"],
    })
    due = iso(now(conn) + timedelta(hours=24))
    first, _ = tasks.create_task(
        conn, pid, task_type="record_glucose", title="核实血糖记录",
        due_at=due, schedule_review=False,
    )
    tasks.create_task(
        conn, pid, task_type="record_activity", title="核实活动记录",
        due_at=due, schedule_review=False,
    )

    class Scripted:
        mode = "real"
        model_name = "controlled-stub-no-provider"
        calls = 0

        def plan_actions(self, **kwargs):
            self.calls += 1
            arguments = {"patient_id": pid, "delay_hours": 24}
            if self.calls == 2:
                arguments["task_id"] = first["id"]
            if self.calls <= 2:
                return LLMResponse(content="", tool_calls=[
                    ToolCall("schedule_review", arguments, f"c{self.calls}")
                ])
            return LLMResponse(content="已安排复评。")

    run = orchestrator.run_agent(
        conn, pid, trigger_type="user_request", message="安排复评", llm=Scripted(),
    )
    conn.commit()
    detail = trace.trace(conn, run["run_id"])
    conn.close()
    assert run["status"] == "completed"
    assert detail["run"]["output"]["warnings"][0]["resolved"] is True
    assert detail["summary"]["unfinished"] == []
    assert detail["summary"]["partial_success"] is False
```

在当前后端基线上，关于 unfinished 的断言失败，复现本问题。A 的回归同时加入已纠正、未纠正、同工具不同错误和 postcheck 真失败四类，再由 B 复验。该项修复前，O1 整体发布保留 OPEN。
