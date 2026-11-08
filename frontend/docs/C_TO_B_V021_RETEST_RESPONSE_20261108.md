# C → B：v0.2.1 复验报告回复与过期用例修订

日期：2026-11-08。对应 B 报告 `B_TO_C_V021_CONTRACT_RETEST_A025E343_20261108.md`。

## 结论与版本对应

认可 B 对 `a025e343` 的独立结果：基础检查通过，专项 9/10，过期场景有 1 项失败；不以 C 本机历史成绩替代 B 的复验结论。

60 秒/404 补充已在后续提交 `3a318b0c09f124d91472d490bd8a84ceb18552ba` 推送到 `feature/frontend-c-workbench` 与 PR #4。该提交的 56 项单测、13 项专项、补充报告和证据均已存在。B 报告所检出的 `a025e343` 不包含这些后续文件，版本差异由此产生。

本次再修订过期场景的测试前置条件，增加 Edge 通道配置。最新完整前端 SHA 以本次交付消息及 PR #4 head 为准；运行代码可核对 [源码摘要](evidence/contract-v021-b-retest/source-manifest.json)。后端仍固定 `v0.2.1 / 694be88c541eb9ee2f6d9c02152a65a09546fe2d`。

| 前端提交 | 对应内容 |
| --- | --- |
| `a025e3433aedff2b9e7c34b202100e03a54c188a` | 旧 10 项专项；B 实测 9/10。该提交默认写超时仍为 180 秒 |
| `3a318b0c09f124d91472d490bd8a84ceb18552ba` | 60 秒写超时、404、明确回答闭环，13 项专项及报告 |
| 本次交付的新 SHA | 已过期与提交时过期两条场景，专项增加至 14 项；支持 Edge，无产品业务逻辑或后端改动 |

## 为什么需要明确两种前置状态

后端 `list_questions` 返回当前持久化状态；到达 `expires_at` 后，问题可能仍为 waiting，直到过期扫描或回答接口处理时才变为 expired。原用例使用过去的到期时间，却未明确验证首次读取的 status，随后直接查找输入框，依赖了具体状态转换时点。

B 报告没有提供首次 GET 的原始状态，无法还原那一次状态转换时点。本次将两种合法前置分开固定，不改变“不保存、不恢复、非法回答返回 422”的验收要求。

1. **打开前已过期**。专用夹具调用既有过期服务使状态明确为 expired；先核对真实 GET，再打开页面，断言无答复框和过期提示；直接 HTTP 答复仍为 422，API 中 answer=null、无运行和记录。
2. **打开后才过期**。独立问题初始 waiting，先确认答复框存在；通过已有隔离演示时钟推进至到期后，从页面提交；真实 POST 返回 422，前端重读后隐藏表单，answer=null，记录与恢复运行均为 0。finally 复位演示时钟。

没有删除 422 验证，没有让测试接受过期答案，也没有修改 A 的后端。新增一项竞态场景，因此总数从 13 增至 14。

## C 本轮实际验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| `npm run build`（含 TypeScript） | PASS，退出码 0 | [构建日志](evidence/contract-v021-b-retest/build.log) |
| Vitest | 56/56 PASS | [单测 JSON](evidence/contract-v021-b-retest/unit-results.json) |
| `npm run test:contract`，Edge | 14/14 PASS，69.42 秒，0 skip/retry/flaky | [浏览器 JSON](evidence/contract-v021-b-retest/browser-results.json) |
| 两种过期场景的实际 API | expired、answer=null、0 记录、0 恢复运行 | [API 证据](evidence/contract-v021-b-retest/api-proof.json) |
| 演示时钟 / 安全审计 | 时钟 offset 已归零，forbidden_executed=0 | 同上 |

本轮使用新的独立后端快照和合成库，端口 8040、前端生产预览 5187；没有覆盖此前 8037/8039 的库。警告样本 `RUN-88f9278958d4`，明确答复恢复样本 `RUN-de71050456d9`。

本轮为真实 HTTP/FastAPI/SQLite 的 Mock、明示脚本模型及故障注入验证，新增 DeepSeek 请求 0。Chrome 本轮没有重跑，Edge 通过不代表 B 已完成独立复验。后端全量测试与原有交互组合本轮未重跑，旧报告保留各自版本结果。

## B 最终定向复验

1. 接收交付消息中的新完整 SHA，核对 `refs/heads/feature/frontend-c-workbench` 与 `refs/pull/4/head`。检出该 SHA，确认专项为 14 项，存在本文件和 `V021_60S_404_REGRESSION_REPORT.md`。不要继续在 `a025e343` 上寻找后续文件。
2. 按 [完整执行书](C_TO_B_V021_CONTRACT_REGRESSION.md) 使用新的 v0.2.1 后端快照和数据库。专项服务拒绝覆盖已有库；不要复用上一轮已经消费过的一次性故障夹具。
3. 构建设置 `VITE_API_WRITE_TIMEOUT_MS=60000`，API 基址与后端端口一致；前端固定 5187，对应专用后端的 CORS。先启动预览，再在 `frontend/` 执行专项。

```powershell
$env:WORKBENCH_API_BASE='http://127.0.0.1:8037/api' # 对应本轮新隔离后端
$env:CONTRACT_UI_BASE='http://127.0.0.1:5187'
$env:CONTRACT_BROWSER_CHANNEL='msedge'
$env:NO_PROXY='127.0.0.1,localhost'
npm run typecheck
npm test
npm run test:contract
```

4. 重点确认两种过期行为、60 秒不重发、404 日志、补偿和重复完成无额外副作用。确认每个测试均实际执行；不得同时运行另一套会推进同一库时钟的用例。
5. 返回新 SHA、浏览器版本、14 项实际结果，以及 C-DS-01/03 的独立关闭结论。原先已验收的 C-UX-01/02 和其他已通过组合保持其原版本结论，无需因这次测试前置修订重复执行。

PR #4 保持 Draft，尚未合并 main；C 不代替 B 宣布关闭问题。
