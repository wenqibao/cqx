# demo_script.md —— 5 段演示脚本（供 C 录屏/剪辑，A 提供真实命令）

> 前提：`python scripts/reset_demo.py` 已执行；终端使用 UTF-8 输出
> （PowerShell：`[Console]::OutputEncoding=[Text.Encoding]::UTF8; $env:PYTHONIOENCODING="utf-8"`）。
> 每个镜头都要把 `run_id` 录进画面，答辩时可现场用 `trace` 复现。

---

## 场景 1：数据录入 → 无点击触发 → 自动创建任务（F03/F05/F06/F08/F10/F11/F14）

```powershell
python -m cli.main record add P001 fasting_glucose 9.6
```

**画面要点**

- 只输入了一条记录，没有点任何"运行 Agent"的按钮；
- 输出里出现 `automation.events_created`（例如 `GLUCOSE_RISING`）与 `runs[0].run_id`；
- 接着展示任务：

```powershell
python -m cli.main task list P001
```

```powershell
python -m cli.main trace <上一步的 run_id>
```

**讲解词**：保存数据 → 规则检测到事件 → 后台自动启动 Agent → 真实写库创建任务 →
每一步都有轨迹（`tool_call` / `tool_result` / 数据库核对）。

---

## 场景 2：信息缺失 → 主动询问 → 回答后恢复（F21）

```powershell
python scripts/reset_demo.py       # 回到初始状态
python -m cli.main record add P003 fasting_glucose 9.5
python -m cli.main ask list P003
python -m cli.main ask answer P003 <question_id> --text "已按时完成"
```

**画面要点**

- Agent 状态为 `waiting_user`，问题内容包括具体字段（服药情况）；
- 回答后：`recorded` 出现一条真实的 `medication_taken=1` 记录，并产生新的 `run_id`；
- 追问"记不清"时，系统记录"不确定"，**不替患者编造事实**：

```powershell
python -m cli.main ask answer P003 <另一个question_id> --text "记不清"
```

---

## 场景 3：多事件 → 合并排序 → 证据与偏好（F22/F24/F25/F26）

```powershell
python -m cli.main run P001
```

**画面要点**

- `priority_order` 显示事件按严重度排序（`GLUCOSE_RISING` → `MEDICATION_NONADHERENCE` → `LOW_ACTIVITY`）；
- 同类任务只入库一次（`task list` 中 `confirm_medication` 只有一条）；
- `evidence` 显示引用来源与段落锚点，例如
  `中国2型糖尿病防治指南（2020年版）核心要点摘编·中华医学会糖尿病学分会·#1-自我血糖监测的意义-2`；
- 知识问答演示：

```powershell
python -m cli.main run P003 --message "为什么需要连续记录血糖"
```

- 无证据拒答演示（会被 `NO_EVIDENCE` 拦截，并给出"没有足够资料"的话术）：

```powershell
python -m cli.main run P003 --message "量子纠缠和超导材料能谱是什么"
```

---

## 场景 4：患者提出时间冲突 → 协商改期 → 旧/新版本（F23/F25）

```powershell
python -m cli.main run P003 --message "我19:00上班，早上没时间，改成08:00记录步数"
python -m cli.main task list P003
python -m cli.main task show <task_id>
```

**画面要点**

- `parse_constraint` 解析出 08:00 与目标任务类型；
- 任务版本从 v1 变成 v2，`versions` 里能看到改期原因与旧时间；
- 偏好被保存为 `preferred_time_window=08:00`（`python -m cli.main pref list P003`）；
- 强调：**只能改非医疗任务的时间**，涉及用药/剂量的表述会被安全门拦截。

---

## 场景 5：演示时钟到期 → 三分支复评（F07/F12/F13）

```powershell
python scripts/reset_demo.py
python -m cli.main run P001                    # 先让 Agent 建任务
python -m cli.main clock --advance 172800      # 推进 2 天（演示时钟）
python -m cli.main automation tick             # 后台调度到期作业
python -m cli.main review list P001
```

**画面要点**

- `automation tick` 的 `processed` 里同时出现 `overdue_check` 与 `review_due`；
- 复评分支真实入库：`MISSING_DATA`（到期未完成）/ `CLOSED`（已完成且数据齐备）；
- 高风险分支：

```powershell
python scripts/reset_demo.py
python -m cli.main run P002                     # 低血糖记录 → escalation
python -m cli.main review list P002             # branch=HUMAN_REVIEW, status=pending_human
python -m cli.main review resolve <review_id> --decision "已电话联系并建议就诊"
```

**讲解词**：系统不判断、不处置，只把高风险升级为人工复核事项并留痕。

---

## 收尾镜头（安全证据）

```powershell
python -m cli.main health
```

以及在浏览器打开 `http://127.0.0.1:8000/api/system/audit`：

- `forbidden_executed` 应为 0（没有任何禁止动作真的被执行）；
- 列表里只应有被拦截（reject/escalate）的记录。
