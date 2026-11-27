# 比赛视频演示数据包（VIDEO-DEMO-DATA-PACK-V1）

> 负责人：B（独立验证与数据构建）
> 版本：VIDEO-DEMO-DATA-PACK-V1
> 日期：2026-11-10

## 一、数据来源

本数据包所有患者档案与健康记录均由 B **人工设计**，为完全虚构的合成演示数据。
不含任何真实患者姓名、手机号、身份证号、住址或临床结论。

每条记录均标注 `[合成演示数据｜非真实患者｜非临床结论]`，所有患者 `is_synthetic = true`。

## 二、患者清单

### 8 个主要演示病例

| ID | 定位 | 预期事件 |
|---|---|---|
| VDEMO-101 | 稳定型患者，状态监测无额外干预 | （无） |
| VDEMO-102 | 多事件综合（血糖上升 + 漏服 + 低活动） | GLUCOSE_RISING、MEDICATION_NONADHERENCE、LOW_ACTIVITY |
| VDEMO-103 | 信息缺失，主动询问 | GLUCOSE_RISING |
| VDEMO-104 | 低血糖风险升级，人工复核 | HYPOGLYCEMIA_RECORD |
| VDEMO-105 | 显著高血糖，人工复核 | HYPERGLYCEMIA_RECORD |
| VDEMO-106 | 任务完成 CLOSED 复评闭环 | GLUCOSE_RISING |
| VDEMO-107 | 任务逾期 MISSING_DATA 复评 | GLUCOSE_RISING |
| VDEMO-108 | 时间冲突与个性化任务调整 | LOW_ACTIVITY |

### 4 个边界测试病例

| ID | 定位 |
|---|---|
| VEDGE-201 | 档案严重缺项 |
| VEDGE-202 | 重复与异常数据导入（去重 / 拒绝） |
| VEDGE-203 | 低血糖阈值附近（3.91 不应误判） |
| VEDGE-204 | 高血糖阈值附近（16.69 不应误判） |

## 三、字段与时间含义

- 记录类型来自 `backend/app/services/records.py` 的 `KIND_SPEC`；
- `hours_ago` 为相对当前时间的偏移（小时），导入时统一取 UTC 基准时间转成 `recorded_at`；
- 血压通过 `payload.systolic` / `payload.diastolic` 保存；
- 症状通过 `payload.text` 保存；
- 服药确认只允许 0 或 1。

## 四、导入限制

1. 数据准备阶段必须处于 **mock 模式**（`AGENT_LLM_MODE=mock`），不调用真实模型、不产生 API 费用；
2. 必须使用独立数据库 `.tmp/diabetes_agent_video_demo.db`；
3. 若目标患者已存在，导入程序会停止，不覆盖原档案；
4. 导入阶段不创建任何 Agent 运行（`trigger_agent=false`），仅执行事件检测（`events/scan`）。

## 五、目录结构

```text
evaluation/demo_pack/
├── README.md
├── manifest.json
├── import_demo_pack.py
├── video_runbook.md
├── patients/          # 12 个患者 JSON
└── reports/
```
