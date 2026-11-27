# 患者体验数据包

本目录保存当前工作台使用的14位患者及其业务历史。导入后可查看档案、健康记录、事件、随访答复、任务版本、复评结果、知识依据和运行轨迹。

## 安装与启动

环境要求：Python 3.11以上、Node.js 24及npm。以下命令在Windows PowerShell执行，其他系统按对应Shell设置环境变量。

在仓库根目录安装后端依赖，然后启动体验服务：

```powershell
python -m pip install -e ".[dev]"
python scripts/start_patient_experience.py
```

首次启动恢复至 `data/runtime/patient-experience.db`；后续启动保留当前体验进度，不覆盖已有数据库。默认不运行后台到期作业；需要体验自动调度时，加上 `--automation`。导入与浏览历史不会调用模型。

在另一个终端启动前端：

```powershell
cd frontend
npm ci
$env:VITE_API_MODE="http"
$env:VITE_API_BASE_URL="http://127.0.0.1:8000/api"
npm run dev -- --host 127.0.0.1 --port 5180 --strictPort
```

打开 [监管工作台](http://127.0.0.1:5180)。后端和前端分别使用8000与5180端口；端口被占用时请先检查已有服务。

模型配置沿用本机环境或根目录 `.env`，启动脚本不会改写密钥或切换模式。已有轨迹保留原来的 `llm_mode`、模型名及成功或失败结果。需要发起新的真实模型请求时，在本机填写 `AGENT_LLM_MODE=real`、`AGENT_LLM_BASE_URL`、`AGENT_LLM_MODEL` 和 `AGENT_LLM_API_KEY`；密钥不随数据包分发。

## 体验入口

| 患者 | 可查看的业务内容 |
| --- | --- |
| 林泽远 VDEMO-102 | 多事件、管理任务、长期偏好、同一任务版本3到4的时间调整、正常关闭复评 |
| 周承安 VDEMO-104 | 缺少数据与人工复核两个复评分支 |
| 梁书恒 VDEMO-301 | “记不清”的答复、回答后的恢复处理、核实任务与复评 |
| 陆文欣 VDEMO-302 | 知识问答、检索片段与完整执行记录 |
| 其他10位患者 | 档案、不同记录组合及数据边界情况 |

记录保留原始日期，历史记录不会改写为今日测量。已过期的问题可通过新请求发起下一轮随访；既有失败、拒绝与等待状态按原样保留。

## 单独恢复与校验

```powershell
python scripts/patient_experience_pack.py restore --db data/runtime/patient-experience.db
python scripts/patient_experience_pack.py verify --db data/runtime/patient-experience.db
```

`verify` 用于核对刚恢复的数据是否与快照完全一致。体验操作会改变数据库，之后校验可能报告差异；恢复命令不会因此重置用户的操作。要重新开始，可指定新的 `--db` 文件并用同一路径启动服务。

`snapshot.json` 是可审查的文本数据，包含SHA-256与逐表数量。知识索引从仓库内 `knowledge/` 重建。运行数据库、密钥、厂商额度账本和机器环境配置不进入数据包。平台界面不因本数据包增加额外标注。

## 本次验证

- 新增恢复专项：10项通过，覆盖导入、重复启动、已有库保护、5类坏包及API读取。
- 全量pytest：613项通过；场景回放33/33。
- Edge只读检查：监管总览、患者列表、随访答复、复评、任务版本对照、回答恢复与审计，共7个入口通过，浏览器写请求为0。
- API健康检查、CLI健康检查均正常；`forbidden_executed=0`。
- 浏览后再次核对16张表，数据校验和仍与快照一致。本次未新增厂商调用，保留的20次历史运行均按原始模式与状态展示，其中3次失败未被改成成功。

本机首次全量回归有5个localhost HTTP测试受代理影响返回502；在测试进程中设置`NO_PROXY=127.0.0.1,localhost,::1`并移除该进程的代理变量后，613项全部通过。未因此修改后端或测试预期。
