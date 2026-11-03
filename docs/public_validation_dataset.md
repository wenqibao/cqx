# CGMacros 公共验证数据集登记与验证报告

> 角色 B · 辅助验证（B 任务书第六节）。本报告不产生任何临床疗效结论。

## 数据源

- 名称：CGMacros: a scientific dataset for personalized nutrition and diet monitoring
- 版本：1.0.0
- 官方页面：<https://physionet.org/content/cgmacros/1.0.0/>
- 官方文件目录：<https://physionet.org/files/cgmacros/1.0.0/>
- DOI：`10.13026/3z8q-x658`
- 许可：Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International

## 完整性核验

本地目录含官方压缩包、数据字典 CSV/PDF、`LICENSE.txt` 与 `SHA256SUMS.txt`。已用 SHA-256 对清单 7 个文件逐一核验，结果为 `ALL_MATCH=True`。机器可读登记见 `data/public/cgmacros_manifest.json`。

## 实际验证结果（已执行）

验证脚本：`evaluation/cgmacros_validate.py`；机器报告：`data/public/cgmacros_validation_result.json`。

以参与者 `CGMacros-039`（17205 行，Libre GL 连续血糖）执行真实回放：

| 验证点（B 任务书第六节） | 结果 |
| --- | --- |
| 真实血糖数据导入 | 17205 条成功导入隔离命名空间患者 `CGV-039`；`mg/dL → mmol/L`（÷18.0182）转换后 0 条超出系统合理范围 (2.0–35.0) |
| Patient State 趋势/缺失 | 7 天聚合 count=9960, mean=7.69, min=3.27, max=17.82；趋势判定 `falling`；缺失字段如实识别：`steps`、`medication_taken`、`age`、`goals` |
| 事件检测 | 触发 `HYPOGLYCEMIA_RECORD`(high)、`GLUCOSE_RISING`(medium)、`GLUCOSE_VARIABILITY`(medium) |
| 回放触发 Agent | `run_agent` → `intent=escalation` → `request_human_review`（高危升级人工复核） |
| 信息不足处理 | 缺失字段进入 `missing_fields`，未插值、未伪造 |
| 安全 | 禁止动作实际执行数（`audit_log.decision='reject'`）= 0 |

## 字段映射说明

- `Libre GL` / `Dexcom GL`（mg/dL，40–400）→ `fasting_glucose`（mmol/L，÷18.0182）。**语义限制**：CGMacros 是连续血糖（CGM），并非空腹血糖，此处仅为导入/回放/缺失验证的字段载体，已在记录 `note` 与 `payload.sensor` 中标注。
- CGMacros 的 `HR`/`METs` 为心率/活动强度，**没有步数（steps）与服药确认（medication_taken）**，因此这两项会出现在缺失字段中——这正对应「CGMacros 不具备完整 Agent 对话、用药确认及任务反馈标签」的边界。

## 允许用途

1. 验证真实数据是否能按字典导入、解析和隔离。
2. 回放选定时间窗口，观察系统对趋势、缺失和重复输入的处理。
3. 为 F03、F04、F05、F06、F18、F19、F20、F21、F24、F26 提供辅助证据。

## 明确限制

- CGMacros 没有完整的 Agent 对话、用药确认、任务反馈和复评标签；这些能力必须由合成场景验证。
- 不得把人工编写的患者回答、任务反馈或用药信息写回官方数据副本并冒充真实数据。
- 不得将数据集的观察值、参与者分组或模型回放结果解释为个体诊断、处方或临床疗效证明。
- 不得为了适配演示规则而修改官方压缩包或原始数据文件；如需构造缺失/损坏输入，只能复制到独立测试目录并显式标记为测试副本。
- 时间戳存在日期偏移语境，回放时通过「末尾对齐 + 相对间隔平移」重放到演示时钟附近，原始日期不作为现实患者就诊时间。

## 对应场景

- CASE-031：目录、版本、许可和 SHA-256 核验。
- CASE-032：真实记录导入和患者命名空间隔离。
- CASE-033：缺失字段处理。
- CASE-034：按版本化演示规则回放，报告触发但不宣称疗效。
- CASE-035：来源登记的词条检索。
- CASE-036：损坏副本导入失败、可恢复且不伪报成功。
