# 视频演示数据包验收报告（VIDEO_DEMO_DATA_ACCEPTANCE）

> B 角色独立验证，2026-11-10。基线 `main @ 0284107`（v0.3.5）。

## 一、代码基线

- main SHA：`02841073219fdc2912ecbbcfeeb0bbc91df163aa`（PR #15 合并，v0.3.5）

## 二、数据包

- 数据包版本：`VIDEO-DEMO-DATA-PACK-V1`
- 主要患者：8 个（VDEMO-101 ~ VDEMO-108）
- 特殊患者：4 个（VEDGE-201 ~ VEDGE-204）
- 原始记录总数：57 条

## 三、导入结果（mock 模式，0 厂商消耗）

| 项 | 数量 |
|---|---|
| 成功创建患者 | 12 |
| 成功导入记录 | 55 |
| 重复跳过 | 1（VEDGE-202 血糖 7.2 重复） |
| 预期坏行拒绝 | 1（VEDGE-202 血糖 99.9 超范围） |
| 意外失败 | 0 |

## 四、事件检测结果

| 患者 | 实际事件 | 预期 | 一致 |
|---|---|---|---|
| VDEMO-101 | LOW_ACTIVITY | （无） | ❌ |
| VDEMO-102 | GLUCOSE_RISING + LOW_ACTIVITY + MEDICATION_NONADHERENCE | 同 | ✅ |
| VDEMO-103 | GLUCOSE_RISING | 同 | ✅ |
| VDEMO-104 | GLUCOSE_RISING + HYPOGLYCEMIA_RECORD | HYPOGLYCEMIA_RECORD | ❌ |
| VDEMO-105 | GLUCOSE_RISING + HYPERGLYCEMIA_RECORD | HYPERGLYCEMIA_RECORD | ⚠️ 合理 |
| VDEMO-106 | GLUCOSE_RISING + LOW_ACTIVITY | GLUCOSE_RISING | ❌ |
| VDEMO-107 | GLUCOSE_RISING | 同 | ✅ |
| VDEMO-108 | LOW_ACTIVITY | 同 | ✅ |
| VEDGE-201 | （无） | 同 | ✅ |
| VEDGE-202 | （无） | 同 | ✅ |
| VEDGE-203 | （无） | 同 | ✅ |
| VEDGE-204 | （无） | 同 | ✅ |

## 五、特殊边界验证

- 档案缺项（VEDGE-201）：正常创建，无崩溃 ✅
- 重复记录（VEDGE-202）：去重 1 ✅
- 不同血压（VEDGE-202）：120/80 与 128/82 均保留 ✅
- 非法记录（VEDGE-202 99.9）：拒绝 1，不影响其他合法记录 ✅
- 低阈值边界（VEDGE-203 3.91）：不触发 HYPOGLYCEMIA ✅
- 高阈值边界（VEDGE-204 16.69）：不触发 HYPERGLYCEMIA ✅

## 六、系统安全

- 全部患者 is_synthetic：✅（后端强制为 1）
- 默认数据库影响：无（使用 `.tmp/diabetes_agent_video_demo.db`）
- Agent 运行数（导入阶段）：**0** ✅
- forbidden_executed：0
- 真实 DeepSeek 调用：**否**（mock 模式）

## 七、发现的问题（BUG）

事件检测发现 **2 个 bug**，位于 `backend/app/events/detector.py` 的 `_eval_trend`：

1. **LOW_ACTIVITY 误触发**：`_eval_trend` 对无 `delta_threshold` 的规则，`threshold` 默认 0，`abs(delta) >= 0` 恒成立，导致 `daily_mean_threshold` 逻辑永远不执行。VDEMO-101（步数 6800/7200/6900 平稳）也误触发 LOW_ACTIVITY。

2. **GLUCOSE_RISING 误触发（下降）**：`abs(delta) >= threshold` 使用绝对值，血糖下降也被判为"上升趋势"。VDEMO-104（血糖 7.1→3.5 下降）误触发 GLUCOSE_RISING。

建议 A：`GLUCOSE_RISING` 改用 `delta >= threshold`（仅上升）；`LOW_ACTIVITY` 跳过 delta 分支直接走 `daily_mean` 逻辑。

## 八、测试

- 数据包结构测试：`test_video_demo_pack.py` 10/10 ✅
- 导入 dry-run：通过（12 患者 57 记录）
- 原有 33 场景：不受影响（本次未改动 evaluation/scenarios）

## 九、交付物

- `evaluation/demo_pack/patients/*.json`（12 个患者）
- `evaluation/demo_pack/README.md`
- `evaluation/demo_pack/manifest.json`
- `evaluation/demo_pack/import_demo_pack.py`
- `evaluation/demo_pack/video_runbook.md`
- `tests/e2e/test_video_demo_pack.py`
- `docs/VIDEO_DEMO_DATA_ACCEPTANCE.md`（本文件）

## 十、结论

数据包构建与导入验证**完成**：12 个患者数据可正常导入、边界测试全部符合预期、导入阶段 0 厂商消耗、Agent 运行 0。

**遗留 2 个事件检测 bug 需 A 修复**（不影响数据包交付，但影响部分患者的预期事件展示）。修复后可重新导入验证。
