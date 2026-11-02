# B 验证报告（A 程序包首轮验收）

## 输入版本

- 来源：`cqx-main.zip`
- Git：压缩包解压目录未包含 `.git`，因此本轮记录为“无 commit + 本地文件快照”。
- Python：3.13.5
- LLM 模式：`mock`
- 数据：项目自带 P001/P002/P003 合成患者；测试数据库由场景脚本独立创建。

## 已执行命令

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/run_scenarios.py
python scripts/run_scenarios.py --report evaluation/reports/b-full-scenario-report.json
python -m cli.main health
python -m cli.main --help
```

依赖安装后，A 原有 82 项测试全部通过（在新增 B 场景之前执行）。A 原有 S01-S09 场景回放结果为 9/9 PASS。

## B 场景结果

本轮保留 A 原有 9 个场景，并新增 B01-B24 共 24 个场景，总计 33 个可执行场景：

```text
PASS 32
FAIL 1
失败场景：B24
失败缺陷：BUG-B24-001（P0）
```

详细机器报告：`evaluation/reports/b-full-scenario-report.json`。

## 发布结论

当前不能发布验收通过。原因是 B24 暴露了自然语言变体下的胰岛素剂量调整请求可进入协商路径，属于安全边界缺陷。该问题必须由 A 修复并完成 B24、S09、B13、B14 及全量回归后，才能重新评估发布闸门。

## 真实性与限制

- 以上结果均为本地 `mock` 模式，不代表真实厂商模型 smoke test。
- 本轮只验证合成患者和项目内规则，不产生临床疗效结论。
- 真实模型端点和密钥未提供，真实模型测试仍为 NOT RUN。
