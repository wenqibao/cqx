# media/ —— 演示视频与录屏素材（成员 C 主责）

## 录制原则

- **只录真实界面与真实终端输出**，不得后期合成 Agent 决策、任务或运行轨迹。
- 演示前先执行 `python scripts/reset_demo.py`，保证每次都从同一初始状态开始。
- 每个关键画面请把 `run_id` 录进镜头（`trace` 输出里有），方便答辩时现场复现。
- 若演示机未接入真实模型，画面/旁白必须说明"当前为确定性策略（mock）模式"。

## 建议素材清单

| 文件（C 命名） | 内容 | 对应场景 |
| --- | --- | --- |
| `s1-auto-trigger.mp4` | 录入血糖 → 自动触发 → 任务生成 + run_id | 场景 1 |
| `s2-ask-answer.mp4` | Agent 提问 → 患者回答 → 恢复同一流程 | 场景 2 |
| `s3-multi-event.mp4` | 多事件合并排序 + 知识引用 + 偏好 | 场景 3 |
| `s4-negotiate.mp4` | 时间冲突协商 + 旧/新版本对比 | 场景 4 |
| `s5-review-branches.mp4` | 推进时钟 → 三分支复评 | 场景 5 |
| `safety-block.mp4` | 要求停药/改剂量 → 被拦截 + 审计记录 | 安全门 |

## 录屏前检查

```powershell
python scripts/reset_demo.py
python -m cli.main health
python -m pytest -q          # 应全绿
python scripts/run_scenarios.py
```

## 素材路径

视频与截图统一放在本目录，`docs/demo_script.md` 中的镜头编号可直接引用这里的文件名。
