# v0.2.1 前端契约回归报告

日期：2026-11-08。C 实现与自验通过，等待 B 独立复验；没有合并 main。

本文件保留上一轮 `a025e3433aedff2b9e7c34b202100e03a54c188a` 的验证快照。后续按用户要求将写超时改为 60 秒并补充 404，当前交付请读 [60 秒与 404 补充回归报告](V021_60S_404_REGRESSION_REPORT.md)。下方测试数量与证据仍对应上一轮。

后端固定 `v0.2.1` / `694be88c541eb9ee2f6d9c02152a65a09546fe2d`；前端基于 `89646bc1cfe49767cf3eca8a7ba61c5d22cc560a` 修改，最终提交 SHA 以交付消息及 PR #4 head 为准。可按 [源码清单](evidence/contract-v021/source-manifest.json) 核对实际运行的代码。

## 结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| TypeScript `tsc --noEmit` | PASS | 实际退出码 0 |
| Vitest | 54/54 PASS | [单测 JSON](evidence/contract-v021/unit-results.json) |
| Vite production build | PASS | 实际退出码 0，保留大块体积提示 |
| 契约浏览器专项 | 10/10 PASS，35.64 秒，0 skip/retry/flaky | [浏览器 JSON](evidence/contract-v021/contract-browser-results.json) |
| 原有浏览器回归 | 23/23 PASS，107.99 秒，0 skip/retry/flaky | [浏览器 JSON](evidence/contract-v021/browser-results.json) |
| 后端全量 pytest | 403/403 PASS，24.72 秒 | [JUnit](evidence/contract-v021/backend-pytest.xml) |
| 后端场景 | 33/33 PASS | [场景 JSON](evidence/contract-v021/scenarios.json) |
| API、CORS 与数据库 | PASS，禁止动作执行数 0 | [API/SQLite 证据](evidence/contract-v021/api-db-proof.json) |

普通业务为后端 Mock，HTTP 调用和数据库读写均实际执行。纠正拒绝使用明示脚本模型，故障使用一次性注入；超时浏览器用例在实际保存后暂缓响应，并推进浏览器时钟触发真实 AbortController。**本轮新增 DeepSeek 请求为 0，不能据此更新厂商模型验收成绩。**

## 关键契约结论

- `warnings`：复评工具首次缺少关联任务被拒，补齐后成功；整体 completed。前端显示已纠正，首次失败和原拒绝完整保留在日志。
- `partial_success`：记录、偏好已保存，副作用失败时提示待补偿；不会把 `automation=null` 当作“没有事件”。实际 tick 后 4 条专用患者 outbox 为 done。
- `already_done`：陈旧任务视图再次提交返回 true、run=null；前端兼容没有 reviews 的响应，任务版本共 2 条，没有重复完成版本。
- `422`：过期回答不保存答案、不运行恢复，重读后移除答复表单；非合成患者、非法记录类型也实际返回 422。
- `409`：重复患者实际返回 409；客户端单测同时核对中文提示、状态码和原始 detail 保留。
- C-DS-01：18 秒处理仍正常等待并成功返回，期间连接探测继续；响应丢失或超时后只发送一次记录，工作台阻止后续写入并提供只读核对。
- C-DS-03：实际问题选项、自动聚焦、回答恢复和顶部结果通过；“记不清”的 recorded=null、uncertain=true，数据库服药记录新增数为 0。

追踪样本：纠正拒绝 `RUN-580a140da5c6`；过期问题 `Q-4da58902a3ce`；不确定回答问题 `Q-8f8585651a50`；重复完成任务 `TSK-ee7de5f7ea52`。恢复 run 的实际编号见 API/SQLite 证据中的 `answer_runs` 及原始回答结果。

最后对已纠正运行增加依据当前复评状态的跟进提示和“首次尝试未完成，后续已纠正”的明确业务说明，重新完成类型检查、54 项单测、构建和该浏览器用例。此单项复测单列 [最终说明复测](evidence/contract-v021/warning-followup-browser-results.json)，不累计成额外场景。

## 过程发现与处理

旧 schema 要求 complete 响应必有 reviews，会把幂等成功误判为格式错误；旧 schema 还会丢弃记录/偏好的补偿字段，均已修正。旧业务判断将历史工具失败和 resolved warning 一并判整次失败，已结合后端明确标记修正，未抹除失败步骤。

开发环境中，运行目录生成的测试 HTML 曾触发 Vite 热更新，造成一次页面仍在加载时的断言失败。现已排除运行/测试目录监听，最终使用生产构建预览通过 23 项回归。后端首轮全量测试遇本机代理返回的本地请求 502；设置 `NO_PROXY=127.0.0.1,localhost` 后全量 403 项通过，未修改后端源码或测试预期。初轮记录保留在本机 `.runtime/v021/`。

## B 下一步

按 [完整复验执行书](C_TO_B_V021_CONTRACT_REGRESSION.md) 固定后端标签和新前端提交，在新隔离库独立执行。重点复核真实失败未被 resolved warning 掩盖、补偿最终状态、重复完成零额外副作用、过期答复零恢复和回复全文只出现一次。

本次实现完成不等于 B 已关闭 C-DS-01/03。新增收费 DeepSeek 验证仍按团队新预算安排。同步接口不能证明超时后原请求已经停止，需先查询再人工确认；工作台内存保护不覆盖浏览器整页刷新。现有 Ant Design 弃用提示和大包提示继续作为后续维护项。
