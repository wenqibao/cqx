# C → B：v0.2.1 前端契约回归与 C-DS-01/03

日期：2026-11-08。负责人 C。后端冻结标签 `v0.2.1`，完整 SHA `694be88c541eb9ee2f6d9c02152a65a09546fe2d`，依据该提交 `docs/api_contract.yaml` 的 `x_contract_notes`。

## 交付范围

只修改 `frontend/`，继续使用 `feature/frontend-c-workbench`。后端使用该标签的独立源码快照，数据库为快照中的 `frontend/.runtime/workbench-test.db`，没有覆盖团队演示库或修改后端业务源码。

本次为实际 HTTP、FastAPI、SQLite 契约回归。普通业务使用后端 Mock；已纠正拒绝使用脚本模型 `contract-scripted-no-provider` 执行真实工具。该运行的 `llm_mode=real` 来自脚本模型的接口路径，**没有调用 DeepSeek**。副作用异常使用测试服务一次性注入，随后恢复原函数验证实际 outbox 补偿。

## 前端变更与验收口径

| 项目 | 实现与核验 |
| --- | --- |
| `warnings` | 依据后端明确返回的 `resolved=true` 和对应拒绝判断；纠正后显示提示，保留原始拒绝、失败步骤、参数和 JSON。未解决拒绝、最终 failed、安全拒绝、数据库核对失败继续明确显示失败 |
| `partial_success` | 记录、偏好和任务完成响应保留 `partial_success/outbox_id/error`；显示业务已保存、自动化待补偿。`automation=null` 不解释为没有事件或已完成自动化 |
| `already_done` | 无 `reviews` 的重复完成响应可读取；显示此前已完成，本次未重复复评/运行；后端实际 `run=null` 保留在日志 |
| `already_resolved` | 再次复核结案显示保留首次决定；日志保留响应 |
| HTTP 422 | 保留服务端响应，提示核对输入/状态；回答被拒后重读问题状态，过期问题不继续展示答复表单 |
| HTTP 409 | 资源重复使用中文说明，原始 detail 留在错误日志；不重试创建 |
| C-DS-01 | 写超时默认 180 秒，可通过 `VITE_API_WRITE_TIMEOUT_MS` 配置；显示已等待秒数和长等待说明；连接探测独立于业务队列。超时、断连或响应无法确认时阻止后续写入，提供只读核对；人工确认后解除保护，不重发原请求 |
| C-DS-03 | 沿用现有回答 API 和深链接自动聚焦；真实选项可点击填入，仍需确认提交；结果置顶，展示 uncertain、实际记录与恢复运行；“记不清”不补记确定服药记录 |

## B 的定向复验

1. 固定上述后端标签与本次前端完整 SHA，检查 PR #4 head 和本地提交一致。不要用旧 f906e323/89646bc1 代替新修复。
2. 在新的隔离源码/数据库启动下述专用测试服务。后台轮询和厂商密钥均关闭。脚本拒绝覆盖已有数据库，第二次完整运行应换新快照。
3. 执行 `npm run typecheck`、`npm test`、`npm run build` 和 `npm run test:contract`。
4. 契约浏览器专项逐项核对：纠正 warning 的顶部结论和日志；记录/偏好部分成功；陈旧视图重复完成；不确定回答；过期 422；资源重复 409；18 秒慢处理；保存后响应丢失；tick 补偿；保存后等待超时。
5. 核对数据库：记录/偏好已持久化；补偿 outbox 为 done；任务重复完成不新增运行/版本；过期问题无答案和恢复 run；不确定回答没有新增服药事实。查询 `/api/system/audit` 的 `forbidden_executed` 必须为 0。
6. 原有 23 项浏览器回归包含 C-UX-01、C-UX-02。确认回复仍只在业务顶部出现一次，日志原文不删减。
7. 分开报告 Mock/脚本模型结果与 DeepSeek 验收。若需新增收费复验，应先按团队已批准预算执行，不将本次结果写成新的真实厂商通过。

## 从新快照复现

仓库根目录，首次准备专用后端源码。不要重复向同一目录展开，也不要复用已运行过专项的数据库。

```powershell
git fetch origin --tags
New-Item -ItemType Directory -Force frontend/.runtime/v021 | Out-Null
git archive --format=zip --output=frontend/.runtime/v021/backend.zip v0.2.1
Expand-Archive frontend/.runtime/v021/backend.zip frontend/.runtime/v021/backend-clean
python frontend/tools/contract-server.py --backend-root frontend/.runtime/v021/backend-clean --port 8037
```

另一个终端，`frontend/` 目录。

```powershell
npm ci
$env:VITE_API_MODE='http'
$env:VITE_API_BASE_URL='http://127.0.0.1:8037/api'
$env:VITE_API_WRITE_TIMEOUT_MS='180000'
npm run typecheck
npm test
npm run build
npx vite preview --host 127.0.0.1 --port 5187 --strictPort
```

再一个终端，`frontend/` 目录。

```powershell
$env:WORKBENCH_API_BASE='http://127.0.0.1:8037/api'
$env:CONTRACT_UI_BASE='http://127.0.0.1:5187'
$env:NO_PROXY='127.0.0.1,localhost'
npm run test:contract
```

Playwright 使用已安装的 Chrome。专项配置不自动启动前端，先确认 5187 为本次构建、8037 为隔离后端。输出位于 `frontend/.runtime/v021/`，默认普通 E2E 排除契约专项，避免没有注入夹具时误运行。

常规 23 项回归应在隔离前端源码副本中运行，以免其历史截图/证据覆盖工作区文档。使用 `WORKBENCH_API_BASE` 指向专用后端，浏览器 baseURL 指向本次预览；不要同时运行会推进演示时钟的两个测试套件。

## 当前限制

接口仍为同步请求，没有新增后台运行、取消、请求状态或 outbox 查询端点。超时后的查询不能证明原请求停止，页面要求人工核对后解除提交保护。当前保护保存在工作台内存，刷新整个浏览器页面后仍需先人工查询原请求结果。

后端补偿需调度实际运行；本次隔离测试禁用了后台轮询，因此使用既有 `POST /automation/tick` 验证。前端不会为制造成功而自动调用 tick 或额外启动 Agent。

构建体积和 Ant Design 既有弃用提示单列维护，不作为本次契约通过的替代证据。根 `docs/PROJECT_FILE_MAP.md` 归 A 维护，本次 C 文件地图更新在 `frontend/docs/FILE_MAP_V2.md`。
