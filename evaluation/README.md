# evaluation/ —— 固定合成场景与预期（成员 B 主责）

## 目录

```
evaluation/
  scenarios/    场景文件（JSON，一个文件一个场景）
  reports/      回放报告（脚本生成，默认不入库）
```

## 执行

```powershell
python scripts/run_scenarios.py            # 全部
python scripts/run_scenarios.py S01 S05    # 指定场景（按前缀或文件名）
python scripts/run_scenarios.py --report my-report.json
```

脚本每次使用 `.tmp/scenarios-*/scenario.db` 独立数据库，不会污染演示库；所有场景共用一个库，
因此患者 ID 必须全局唯一（建议按场景段分配，如 `P200` 起）。

## 场景文件格式

```jsonc
{
  "id": "S10",                       // 必填，唯一
  "title": "一句话描述",              // 必填
  "features": ["F21", "F26"],        // 覆盖的功能编号
  "allow_rejections": false,         // 是否允许本轮出现被拦截的动作（如故意测试越权）
  "steps": [ /* 见下 */ ]
}
```

### 支持的 step

| action | 参数 | 说明 |
| --- | --- | --- |
| `patient` | `data`（患者档案） | 创建/复用合成患者，后续 step 使用该 `id` |
| `record` | `kind`, `value`, `hours_ago`, `payload`, `trigger` | 写一条健康记录；`trigger=true` 时立即触发事件检测与 Agent |
| `run_agent` | `message`, `trigger_type` | 运行 Agent |
| `answer` | `text`, `resume` | 回答最新一条等待中的问题；`resume=true` 时执行后续恢复 |
| `complete_task` | `task_type` | 完成指定类型（或第一个）待办任务，并评估复评 |
| `tick` | `advance_seconds` | 推进演示时钟并执行到期作业 |
| `state` | — | 读取状态快照（用于校验偏好/缺失字段） |

### 支持的 expect

| key | 含义 |
| --- | --- |
| `run.status` / `run.intent` | 运行状态/意图精确匹配 |
| `run.evidence.0.doc_id` | 第一条证据的知识文档编号 |
| `tasks_min` | 该患者任务总数下限 |
| `events_include` | 事件码集合必须包含这些值 |
| `review_branches_include` | 复评分支集合必须包含这些值 |
| `rejections_include` | 本次运行的拒绝码必须包含这些值 |
| `waiting_questions_min` | 等待中问题数量下限 |
| `resume.recorded.kind` | 答复是否落成真实记录及其类型 |
| `state.preferences.0.value` | 状态中的偏好值 |

## 预期文件必须独立维护

- 场景与 `expect` 由 B 在 `qa/tests-*` 分支编写，A 的实现不能反过来修改 `expect`。
- 修改 `expect` 必须附理由（例如产品口径变更），并在 `docs/bug_log.md` 关联 BUG-ID。

## 当前示例场景

| ID | 覆盖 | 说明 |
| --- | --- | --- |
| S01 | F03/F05/F06/F08/F10/F11/F14 | 录入后自动触发，产生任务与 run_id |
| S02 | F21 | 缺信息 → 提问 → 回答 → 恢复 |
| S03 | F22/F09/F11 | 多事件合并、优先级 |
| S04 | F23/F25 | 协商改期 + 偏好保存 |
| S05 | F12/F07 | CLOSED 与 MISSING_DATA 分支 |
| S06 | F13/F12 | 低血糖 → 人工复核 |
| S07 | F24 | 知识引用带出处 |
| S08 | F24/F26 | 无证据 → NO_EVIDENCE |
| S09 | F13/F26 | 禁止动作被拦截 |
