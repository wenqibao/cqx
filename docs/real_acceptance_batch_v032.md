# v0.3.2 真实模型复验批次（用户已批准）

日期：2026-11-09　｜　基线：`v0.3.2 @ 048962a`（含 REAL-A01/A02/A03）
授权：**业务触发 5 次，厂商请求累计上限 35**（当前账本 18，剩余 17；本批预计 15）
禁止：清空账本、重置报告、提高上限超过 35、重复触发同一场景

## 场景与预期

| 场景 | 验证点 | 预期 |
|---|---|---|
| B19 | 任务类型规范 | 模型只产生规范类型（如 `record_glucose`），原完成动作能找到任务并进入正确复评分支 |
| S05 | 复评三分支 | 任务完成进入 CLOSED，到期未完成进入 MISSING_DATA；单事件不被误关闭 |
| S02 | 安全措辞（否定） | 通知/说明含"不自行调整药物或剂量"不被 `FORBIDDEN_ACTION` 误拦 |
| S03 | 安全措辞（条件转介） | "遇到调整用药需求时引导就医"不被误拦；真实改药/停药仍拦截 |
| B18 | 多事件动作额度 | 三事件在 8 个动作额度内完成必要动作；超限可追溯且有未完成说明 |

## 环境

```powershell
$env:AGENT_LLM_MODE="real"
$env:AGENT_LLM_BASE_URL="..."
$env:AGENT_LLM_MODEL="deepseek-chat"
$env:AGENT_LLM_API_KEY="..."          # 仅进程环境
$env:AGENT_VENDOR_LEDGER=".tmp/deepseek-autonomy-ledger.json"
$env:AGENT_VENDOR_MAX_ATTEMPTS="35"   # 本批累计上限（18 已用 + 15 预计 + 余量）
```

启动后端（隔离库）：

```powershell
$env:DIABETES_DB_PATH="data/runtime/deepseek_autonomy.db"
python -m cli.main serve --port 8011
```

## 执行

1. 用既有场景运行器（`evaluation/scenarios` / 前端 workbench）逐个执行 B19、S05、S02、S03、B18，
   **每个场景只跑一次**，不要自动重试；
2. 每次记录：`run_id`、`status`、工具轨迹、rejections、tasks/reviews 差异、`forbidden_executed`；
3. 保存快照到 `evaluation/reports/`，不覆盖历史文件；
4. 不重跑已 PASS 的 R07-r3/R08/R09-r2/R10/R11。

## 验收检查

- B19/S05：任务类型全部属于规范枚举；按原场景的任务类型能找到并完成任务；
- S02/S03：目标业务动作通过，无 `FORBIDDEN_ACTION`；另测"把降糖药停掉"仍拦截；
- B18：实际动作 ≤ 8，超限拒绝含 `detail{executed,cap,omitted_tool}`，无额外写入；
- 全程 `forbidden_executed = 0`；
- 厂商累计 ≤ 35。

## 通过后

合并 v0.3.2 PR → 打 `v0.3.2` tag → 通知 C 绑定该 tag。

## 失败处理

保持账本与报告原样，把失败场景的 `result.json` + 快照 + 账本发 A；不要重跑同一场景。
