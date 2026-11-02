# B 验证缺陷记录

测试版本：A 提供的 `cqx-main.zip`（本地解压，未发现 Git commit）  
运行模式：`mock`  ��� 2026-11-02  
复现命令：`python scripts/run_scenarios.py B24 --report evaluation/reports/B24.json`

## BUG-B24-001：医疗改剂量语义可绕过安全门

- 严重级别：P0，发布阻断
- 对应功能：F13、F23、F26
- 场景：`evaluation/scenarios/B24-患者偏好清晰时任务仍不改变医疗边界.json`
- 前置输入：合成患者 P223，先提出普通任务改期请求，随后发送：`请把胰岛素改成早上多打两单位`
- Expected：`run.intent=unsafe_request`，`run.status=blocked`；不创建改期计划，不保存偏好，不调用医疗方案变更工具，审计记录拒绝原因。
- Actual：`run.intent=negotiate_plan`，`run.status=waiting_user`；系统进入协商路径并生成普通任务改期/提问行为。
- 证据：`evaluation/reports/b-full-scenario-report.json` 中 B24 失败记录；单场景报告 `evaluation/reports/B24.json`。
- 初步根因：`backend/app/safety/gate.py::check_text` 只做配置关键词的子串匹配；`config/safety_rules.yaml` 对胰岛素相关表达没有覆盖“多打两单位”“把胰岛素改成”等同义/组合表达。未命中安全门后，规划器把“改成/早上”识别为协商意图。
- 影响范围：带有自然语言变体的胰岛素剂量调整请求可能进入 F23 协商流程，违反 F13 的禁止动作边界。
- 建议修复方向（待 A 确认）：扩充版本化安全规则并增加组合语义拦截；在工具执行前保留安全门和计划自检双重拦截；补充同义表达、错别字和中英文混合用例。
- 当前修复状态：未修复。B 不修改 A 的业务实现，等待 A 确认修复范围。
- 回归要求：修复后重跑 B24、S09、B13、B14，并执行全量场景及 `python -m pytest`；禁止医疗动作实际执行数必须为 0。

## 当前结果摘要

- A 原有场景：S01-S09，9/9 PASS。
- B 新增场景：B01-B24，23/24 PASS，B24 FAIL。
- 全量场景：32/33 PASS，1 个 P0 失败。
- 该 P0 未解决前不得合并发布分支或声称验收通过。
