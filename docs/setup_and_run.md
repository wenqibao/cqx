# setup_and_run.md —— 从零安装、启动与本次真实运行结果

> 环境：Windows 11 + Python 3.13.1；命令为 PowerShell 形式。macOS/Linux 把 `$env:X=...` 换成 `export X=...` 即可。
> 所有输出都是本次实际执行结果，没有伪造。

## 1. 安装

```powershell
python -m pip install -e ".[dev]"
```

安装的版本（本次实测）：

```
fastapi 0.115.6 | starlette 0.41.3 | uvicorn 0.32.1 | pydantic 2.13.4
PyYAML 6.0.1 | python-dotenv 1.0.0 | httpx 0.28.1 | pytest 8.1.1
```

### 受限环境（pip 临时目录被策略拦截时）

本机 pip 在写临时目录时被安全策略拒绝，因此改用仓库内的**纯 Python wheel 直接解包**引导（不经过 pip 临时目录）：

```powershell
python tools/getpkg.py fastapi==0.115.6 starlette==0.41.3 uvicorn==0.32.1 anyio sniffio idna h11 typing_extensions typing-inspection annotated-types annotated_doc
python tools/install_wheels.py vendor
$env:PYTHONPATH="$PWD/vendor"
```

`vendor/` 与 `wheels/` 已在 `.gitignore` 中，不进入仓库。正常联网环境直接 `pip install -e ".[dev]"` 即可，不需要这一步。

## 2. 初始化演示数据

```powershell
python scripts/reset_demo.py
```

实际输出（节选）：

```json
{
  "db": "...\\data\\runtime\\diabetes_agent.db",
  "patients": [
    {"patient": "P001", "records": 13, "skipped": false},
    {"patient": "P002", "records": 8,  "skipped": false},
    {"patient": "P003", "records": 6,  "skipped": false}
  ],
  "knowledge": {"indexed": 4, "unchanged": 0, "documents": 4}
}
```

## 3. 健康检查

```powershell
python -m cli.main health
```

```json
{
  "status": "ok",
  "version": "0.1.0",
  "db": "...\\data\\runtime\\diabetes_agent.db",
  "llm_mode": "mock",
  "patients": 3
}
```

## 4. 启动 HTTP API

```powershell
python -m cli.main serve --port 8000
# 等价：uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

```json
{
  "status": "ok",
  "service": "diabetes-agent",
  "version": "0.1.0",
  "time": "2026-11-02T04:51:12Z",
  "database": {"ok": true, "path": "...\\diabetes_agent.db", "error": null},
  "llm_mode": "mock",
  "disclaimer": "演示作品，不提供诊断或用药建议；患者均为合成虚构数据。"
}
```

其他实测请求：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/patients"                     # count = 3
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/patients/P003/agent/runs" `
  -ContentType "application/json" -Body '{"message":"为什么需要连续记录血糖"}'
# run_id=RUN-5d3cca11603b | status=completed | intent=knowledge_question | evidence=4
Invoke-RestMethod "http://127.0.0.1:8000/api/patients/P001/tasks"           # count = 3
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/search?q=低血糖"     # hits = 4
```

## 5. CLI 全链路演示（本次实测）

```powershell
python -m cli.main record add P003 fasting_glucose 9.5
# → 事件 GLUCOSE_RISING 自动产生 → Agent 自动运行 → 因缺少服药信息进入 waiting_user
# → 创建 1 条待答复问题 Q-b0a0fc575445

python -m cli.main ask list P003
python -m cli.main ask answer P003 Q-b0a0fc575445 --text "已按时完成"
# → 答复转成真实记录 medication_taken=1 → 恢复执行（run RUN-ebc778f8888e，status=completed）

python -m cli.main run P001
# → intent=event_response；GLUCOSE_RISING / MEDICATION_NONADHERENCE / LOW_ACTIVITY 三个事件
#   按严重度合并为 3 个任务；证据引用 KD-001

python -m cli.main trace RUN-RUN...
```

复评三分支：

```powershell
python -m cli.main clock --advance 172800
python -m cli.main automation tick
python -m cli.main review list P001
# → branch=MISSING_DATA（任务到期未完成），status=completed
```

## 6. 测试

```powershell
python -m pytest
```

```
149 passed in 11.39s
```

其中 7 项为并发回归：`tests/unit/test_db_threading.py`（3 项，跨线程使用连接）与
`tests/integration/test_concurrent_api.py`（4 项，真实 uvicorn 下 9 并发读 / 6 并发写 / 500 带 CORS）。

场景回放：

```powershell
python scripts/run_scenarios.py
```

```
[PASS] S01 录入健康数据后无需点击即自动触发 Agent 并创建任务 (242ms) mode=mock
[PASS] S02 信息缺失时 Agent 主动提问，患者回答后恢复同一管理流程 (111ms) mode=mock
[PASS] S03 多个事件并发时合并同类任务并按优先级排序 (101ms) mode=mock
[PASS] S04 患者提出时间冲突后协商修改任务并保存版本与偏好 (54ms) mode=mock
[PASS] S05 复评三分支：完成任务正常关闭，到期未完成进入数据缺失分支 (428ms) mode=mock
[PASS] S06 低血糖记录触发安全门：不处置、升级人工复核 (93ms) mode=mock
[PASS] S07 知识问答必须引用可定位来源 (49ms) mode=mock
[PASS] S08 知识包无相关资料时拒绝臆测并记录 NO_EVIDENCE (49ms) mode=mock
[PASS] S09 禁止的医疗动作被安全门拦截并留痕 (50ms) mode=mock

合计 33 个场景，通过 33，失败 0
报告: evaluation/reports/scenario-report-*.json
```

## 7. 切换到 real 模型模式

```powershell
Copy-Item .env.example .env
# 编辑 .env：
#   AGENT_LLM_MODE=real
#   AGENT_LLM_BASE_URL=https://your-endpoint/v1
#   AGENT_LLM_API_KEY=sk-xxxx
#   AGENT_LLM_MODEL=your-model
python -m cli.main health        # llm_mode 应为 real
python -m cli.main run P001      # agent_runs.llm_mode 必须是 real
```

配置缺失时 `get_llm()` 会抛 `LLMConfigError` 并在 `/api/system/mode` 返回 `ok=false`，**不会静默降级为 mock**。

## 8. 重置与清理

```powershell
python scripts/reset_demo.py          # 删库重建 + 重新写入演示数据
python scripts/reset_demo.py --keep   # 只补建缺失患者，保留现有数据
```

## 9. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `ModuleNotFoundError: fastapi` | 未安装依赖：`pip install -e ".[dev]"`，或使用 `vendor/` 并设置 `PYTHONPATH` |
| `/api/health` 返回 `degraded` | 数据库不可写：检查 `data/runtime/` 权限或 `DIABETES_DB_PATH` |
| `llm_mode=real_misconfigured` | `.env` 缺少 BASE_URL/API_KEY/MODEL，见第 7 节 |
| 端口被占用 | `python -m cli.main serve --port 8010` |
| 想重复演示同一场景 | `python scripts/reset_demo.py` 后重跑；调度作业与事件都有幂等键，重复执行不会重复生效 |
