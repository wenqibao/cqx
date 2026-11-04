# 糖衡智管最新复验报告：DeepSeek 接入准备版

更新时间：2026-11-04（北京时间）。用户已确定DeepSeek API并已获取Key，不再进行供应商选型。

## 1. 当前结论

**下一工作批次立即进入DeepSeek真实API联调，不等待第二阶段页面。**先完成协议/耗时适配，再执行真实上游、Agent和浏览器三层联调；B验收通过后，将团队演示配置默认切到real。

用户已在本机完成配置，并授权当前代理联调。**本次首次真实DeepSeek最小调用已通过**；项目内Agent工具调用、业务落库和浏览器real闭环尚未验证，尚无DeepSeek Agent run_id。

本次重生成重新检查了远端引用、源码、配置字段存在性和HTTP状态，并执行一次真实DeepSeek最小调用；完整回归结果引用同日上一轮机器证据，未重复运行未受文档变化影响的测试。

## 2. 版本与分支

| 项目 | 核对结果 |
|---|---|
| 工作目录/分支 | D:\cqx-current；feature/frontend-c-integration |
| 报告更新前本地HEAD | fa4a9cc，包含集成提交939c8b7 |
| 再次核对的远端main | c5f787f8fe9f02df6ec1507890b12fcbdcd02112 |
| 再次核对的远端前端分支 | 2cd7dc44e2986dfda055b04931b0c9c7dcca0ebd |
| 本地完整版本 | 最新main后端与完整前端已合并；A/B源码与main一致 |
| 待办 | main尚只有前端README，完整前端在功能分支；本地集成和报告未push |

上轮终端fetch卡住后已取消，通过授权GitHub API逐对象核对SHA同步；本次通过该连接重新核对引用，没有声称常规fetch成功。此前D:\cqx为旧独立展示目录。

## 3. 验证状态

| 检查 | 结果 | 证据与边界 |
|---|---|---|
| 后端回归 | 149项通过 | 同日上一轮pytest，含7项新增并发回归 |
| 场景 | 33/33通过 | 上轮独立脚本；mock模式 |
| 前端单测 | 11项通过 | 上轮Vitest原始报告 |
| 浏览器闭环 | 4项通过 | 上轮2026-11-04 15:50北京时间；真实FastAPI HTTP，后端mock规划器 |
| 构建 | 通过 | 上轮TypeScript+Vite；主包约1.72MB，体积警告仍在 |
| C-API-001 | 本机复验通过 | 9并发GET全200，6并发写回归通过；不代表高并发压测 |
| 本次health/mode/audit | 全部HTTP200 | 当前mock/deterministic-planner；禁止动作执行数0 |
| 本次Key存在性 | 已配置 | 用户本机设置；未输出或保存密钥值 |
| DeepSeek真实上游最小调用 | PASS | HTTP200，返回deepseek-flash与OK；详见下一节 |
| 平台Agent及浏览器real闭环 | NOT RUN | 尚无DeepSeek Agent run_id、真实工具执行/落库证据 |

上轮保存record 28，同一响应创建3事件/3自动运行，`RUN-c0421acc9b93`；完成任务后重新GET核对done，没有额外Agent POST。**该run属于mock规划器，不能当作DeepSeek调用证据。**

- [上轮机器证据](reviews/2026-11-04-main-c5f787f/)：XML、场景、浏览器、单测、构建及业务响应。
- [本次准备状态快照](reviews/2026-11-04-deepseek/readiness.json)：时间、配置存在性、运行HTTP状态和payload检查。
- [首次DeepSeek真实调用证据](reviews/2026-11-04-deepseek/upstream-probe.json)：北京时间2026-11-04 16:10:01，官方api.deepseek.com，deepseek-flash，显式thinking disabled；HTTP200，返回OK；0.911秒，输入8/输出1/总计9 tokens，响应ID `b9ab0d2d-68dd-438f-84a6-060ec1081fd1`。仅一次最小请求，无tools或数据库写入，不代表Agent端到端通过或性能统计。

## 4. 已确定的DeepSeek接入方案

已使用DeepSeek官方OpenAI Chat Completions兼容API完成首次真实连通；首轮使用 **deepseek-flash，显式关闭思考模式**。本机配置的官方地址和模型已由这次响应核对。

官方当前列出deepseek-flash与deepseek-v4-pro，均支持Tool Calls。本阶段不依赖升级高级模型；记录首次实际返回版本以便复现。[官方模型信息](https://api-docs.deepseek.com/quick_start/pricing/)

关键兼容差异：官方当前默认启用思考模式；非思考请求须发送 `"thinking":{"type":"disabled"}`。当前OpenAICompatLLM没有该字段，LLMResponse及编排器重建的assistant消息也没有保留reasoning_content。官方要求思考模式多轮工具请求回传reasoning_content，否则可能返回400。**仅填写四个env不能证明现代码兼容多轮DeepSeek。**

首轮由A修改适配层，显式关闭思考模式，沿用现有非流式工具循环。未来启用思考模式时另行补全协议回传与回归，前端不展示内部思考文本。
依据：[非思考Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。最小探针已显式传入非思考字段；项目适配层仍未实现该字段，多轮工具兼容尚待验证。

## 5. 接入前必须处理

| 项目 | 当前事实及下一动作 | 负责人 |
|---|---|---|
| 模型协议 | 显式发送非思考选项，验证多轮工具；保留脱敏模型、请求标识、用量与耗时 | A修改；当前代理联调；B复验 |
| 耗时与写入状态 | 前端15秒，模型单轮30秒且最多3轮；需分开读写超时与健康检查，超时先读状态核对，不自动重发写入 | A/C |
| 证据与文本安全 | search_knowledge给模型回传ok与命中数量，需补受控片段/出处；工具有校验，content直接进入responses，需输出安全回归 | A/B |

以上兼容与安全项属于源码/文档审查，未宣称已经复现真实模型失败或违规输出。

## 6. 正式启用real的验收条件

1. 真实DeepSeek响应成功，保存实际模型、用量、耗时及请求标识（若提供），证据脱敏。
2. 至少一次真实模型tool_calls经本系统执行并落库；真实run_id、轨迹和任务/问题/复评相互核对。
3. 浏览器录入由后端自动触发，任务完成后重新读取状态，不用额外运行接口冒充自动触发。
4. 证据问答、缺信息恢复、安全拒绝、患者隔离、超时/限流处理通过，禁止动作0。
5. 失败不静默退回mock，不显示虚假成功；B确认后发布整合分支与说明。

第1项中的最小上游连通、模型/用量/耗时证据已取得，其余正式启用条件尚未满足。正在运行的平台仍返回mock，未在工具循环未验收时切换。下一步顺序、配置与交接以 [DeepSeek执行计划](DEEPSEEK_NEXT_PLAN.md) 为准。
