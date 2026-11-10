# v0.2.1 前端补充回归：60 秒超时、404 与回答入口

日期：2026-11-08。C 实现及自验通过，等待 B 独立复验。

本文件保留 `3a318b0c09f124d91472d490bd8a84ceb18552ba` 的 13 项验证快照。后续根据 B 对 `a025e343` 的反馈拆分过期场景，当前 14 项 Edge 复验结果见 [回复 B 的交接](C_TO_B_V021_RETEST_RESPONSE_20261108.md)。

后端固定 `v0.2.1`，SHA `694be88c541eb9ee2f6d9c02152a65a09546fe2d`，契约依据 `docs/api_contract.yaml` 的 `x_contract_notes`。前端基于 `a025e3433aedff2b9e7c34b202100e03a54c188a` 增量修改，最终完整 SHA 见交付消息及 PR #4 head；实际源码可按 [文件摘要](evidence/contract-v021-60s/source-manifest.json) 核对。

## 三项交付

| 要求 | 实现与实际核验 |
| --- | --- |
| warnings / partial_success / already_done / 422 / 409 / 404 | 全部纳入本轮浏览器专项。纠正 warning 不误报整次失败；部分成功保留保存结果与补偿信息；重复完成不重复触发；422/409 原始响应保留；新增 5 条缺失资源 GET、缺失患者记录 POST、缺失运行及任务页面的 404 验证 |
| C-DS-01 | `HttpAdapter` 与客户端默认写超时统一为 `60000ms`，环境示例同步。超时/断连提示“后端可能仍在运行”，不自动重发，提供只读查询并保留提交保护。GET 读取仍为 15 秒，健康探测独立于业务写队列 |
| C-DS-03 | 已接 `GET /patients/{id}/questions` 和 `POST /questions/{id}/answer`，路径统一位于 API 客户端。页面读取真实问题/选项，深链接聚焦，提交实际答复并展示恢复结果。明确回答、记不清、过期三条路径均通过 |

“可能仍在运行”用于超时或连接中断后的未知结果；不能据此确认后端运行状态。后端明确返回的 failed、拒绝或部分成功仍按真实结果展示。

## 本轮测试

| 命令/验证 | 实际结果 | 证据 |
| --- | --- | --- |
| `npm run typecheck` | PASS，退出码 0 | TypeScript 校验实际完成 |
| `vitest run --reporter=json` | 56/56 PASS | [单测](evidence/contract-v021-60s/unit-results.json) |
| `npm run build` | PASS，退出码 0 | [构建输出](evidence/contract-v021-60s/build.log) |
| `npm run test:contract` | 13/13 PASS，37.51 秒，0 skip/retry/flaky | [浏览器结果](evidence/contract-v021-60s/browser-results.json) |
| API / CORS / SQLite | PASS，禁止动作执行数 0 | [原始响应与数据库核对](evidence/contract-v021-60s/api-db-proof.json) |

专用后端位于 `frontend/.runtime/v021-60s/backend`，端口 8039，数据库为该快照下新建的 `frontend/.runtime/workbench-test.db`。浏览器使用生产构建预览 5187，构建设置 `VITE_API_WRITE_TIMEOUT_MS=60000`，没有覆盖旧 8037 隔离库或团队演示库。

后端是实际 FastAPI/SQLite，规划使用 Mock 和明确标注的脚本模型；副作用失败为一次性测试注入。慢请求实际等待 18 秒，超时场景在实际保存后暂缓响应并推进浏览器时钟，单测另验证 59,999ms 尚未结束、60,000ms 超时。**本轮新增 DeepSeek 请求数为 0**，不能当作新的真实厂商模型验收。

## 关键证据

- 60 秒边界：浏览器 59 秒时继续等待，越过 60 秒后出现“后端可能仍在运行”；保存接口只发送一次，SQLite 仅一条对应记录，未自动重发。
- 404：缺失患者、状态、问题列表、运行与任务实际 GET 404；缺失患者记录 POST 404；任务/运行详情显示“资源不存在”，错误日志保留 `HTTP_404` 与服务端 detail，没有模拟成功或空数据回退。
- 明确回答：选择实际选项“已按时完成”，API 返回 answered、uncertain=false、recorded.kind=medication_taken、value=1；恢复运行 `RUN-66cf61cde4e7`，实际记录新增一条。
- 不确定回答：“记不清”返回 uncertain=true、recorded=null，服药记录新增数 0。
- 过期回答：实际 422，无答案、无恢复运行，重读后移除回答表单。
- 补偿与幂等：4 条专用患者 outbox 为 done；重复完成任务后仍仅 2 条任务版本，run=null；`forbidden_executed=0`。

## B 复验与边界

执行步骤见 [B 完整复验说明](C_TO_B_V021_CONTRACT_REGRESSION.md)。用新的源码快照和隔离库运行 13 项专项，固定新前端 SHA + 上述后端 SHA，独立判断是否关闭 C-DS-01/03。

上一轮 23 项常规浏览器、403 项后端 pytest 和 33 个场景的结果保留在 [上一轮报告](V021_REGRESSION_REPORT.md)，本轮没有将其重复计为新测试。本轮未修改后端源码、后端契约或 A/B 文档，也未合并 main。

仍需注意同步接口无法确认客户端超时后服务端是否停止；提交保护保存在工作台内存，整页刷新后应先查原结果。构建仍有原有大块体积提示。
