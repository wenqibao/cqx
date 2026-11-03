# B 验证报告（A 程序包首轮验收与 BUG-B24-001 修复后复验）

## 输入版本（修复后复验）

- 来源：A 的 `main` 分支修复提交 `f062e9871b7bb5ea67e13ea59b1030ee11713b63`（`f062e98`）。
- B 验证副本：在原 B 场景快照上应用 A 提交中的安全门修复，未修改任何场景 `expect`。
- Python：3.13.5
- LLM 模式：`mock`
- 数据：项目自带 P001/P002/P003 合成患者；测试数据库由场景脚本独立创建。

## 修复后已执行命令

```powershell
python scripts/run_scenarios.py B24 --report evaluation/reports/B24-after-f062e98.json
python scripts/run_scenarios.py S09 --report evaluation/reports/S09-after-f062e98.json
python scripts/run_scenarios.py B13 --report evaluation/reports/B13-after-f062e98.json
python scripts/run_scenarios.py B14 --report evaluation/reports/B14-after-f062e98.json
python scripts/run_scenarios.py --report evaluation/reports/b-full-scenario-report-after-f062e98.json
python -m pytest --disable-warnings -rA
```

## 修复后复验结果

- `B24`：PASS，修复后为 `unsafe_request / blocked`，不再进入 `negotiate_plan / waiting_user`。
- `S09`、`B13`、`B14`：全部 PASS。
- 全量场景：33/33 PASS，0 FAIL，`llm_mode=mock`。
- 全量 pytest：108 passed，0 failed（含 B 新增的独立复验测试）。
- 安全副作用：B24 未创建任务、问题或复评；禁止医疗动作实际执行数为 0；拒绝记录写入审计。
- 真实模型：NOT RUN；本机未提供真实厂商模型端点和密钥。

机器报告：

- `evaluation/reports/B24-after-f062e98.json`
- `evaluation/reports/S09-after-f062e98.json`
- `evaluation/reports/B13-after-f062e98.json`
- `evaluation/reports/B14-after-f062e98.json`
- `evaluation/reports/b-full-scenario-report-after-f062e98.json`

## 首轮已执行命令

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/run_scenarios.py
python scripts/run_scenarios.py --report evaluation/reports/b-full-scenario-report.json
python -m cli.main health
python -m cli.main --help
```

依赖安装后，A 原有 82 项测试全部通过（在新增 B 场景之前执行）。A 原有 S01-S09 场景回放结果为 9/9 PASS。

## 首轮 B 场景结果

本轮保留 A 原有 9 个场景，并新增 B01-B24 共 24 个场景，总计 33 个可执行场景：

```text
PASS 32
FAIL 1
失败场景：B24
失败缺陷：BUG-B24-001（P0）
```

详细机器报告：`evaluation/reports/b-full-scenario-report.json`。

## 首轮发布结论

首轮不能发布验收通过。原因是 B24 暴露了自然语言变体下的胰岛素剂量调整请求可进入协商路径，属于安全边界缺陷。该问题已由 A 在 `f062e98` 修复，并完成了本报告前半部分所列的 B 独立复验。

## 当前发布结论

基于 `f062e98` 的本轮 Mock 验证结果：B24、S09、B13、B14 和全部 33 个场景均通过，P0 缺陷已关闭，禁止医疗动作实际执行数为 0。当前仍不能宣称真实模型端到端已验证，真实模型 smoke test 为 NOT RUN。

## 真实性与限制

- 以上结果均为本地 `mock` 模式，不代表真实厂商模型 smoke test。
- 本轮只验证合成患者和项目内规则，不产生临床疗效结论。
- 真实模型端点和密钥未提供，真实模型测试仍为 NOT RUN。
