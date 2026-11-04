# 最新团队版本本地集成复验（2026-11-04）

## 同步结果

目录 D:\cqx-current，当前分支 feature/frontend-c-integration。
远端 main c5f787f8fe9f02df6ec1507890b12fcbdcd02112；远端前端分支 2cd7dc44e2986dfda055b04931b0c9c7dcca0ebd。
本地集成提交 939c8b7cb2ea741e5ad98d08c47381af6bef923b，将最新 main 合入前端分支，无源码冲突，保留 A 的全部修复。未 push，未合并远端 main。

**分支差异**：远端 main 目前 frontend/ 只有 README；完整前端在 feature/frontend-c-integration。其他成员复现完整程序必须取得两部分合并后的分支，不能认为普通 clone main 已含前端。

本地 Git CLI fetch 仍卡住，已取消；改用授权 GitHub API 取得最新引用、10 个变化 blob、完整树及 3 个提交，逐对象验证精确 SHA 后导入 Git，恢复真实历史到原浅检出边界。浏览器登录状态不等于终端凭据可用；没有读出或输出凭据。

## 本轮实际验证

- python -m pytest -o addopts='' -q --basetemp=frontend/.runtime/latest-pytest --junitxml=frontend/.runtime/latest-pytest.xml：149 passed。
- python scripts/run_scenarios.py --report frontend/.runtime/latest-scenarios.json：33/33 PASS。
- npm run build：exit 0；仍有主包约1.72MB的体积警告。
- vitest run：11 passed，0 failed。
- Playwright 全部4项：4 passed，0 failed；使用新的独立演示库，真实 FastAPI HTTP，不是前端模拟。
- 原始9并发GET：9/9 HTTP200、CORS正确；新增并发写回归也在149项内通过。C-API-001本机复验通过。
- system/mode：mock / deterministic-planner；system/audit：forbidden_executed=0。
- 真实保存 record 28，同一响应创建3个事件/3次自动运行，run_id `RUN-c0421acc9b93`，无额外Agent POST；任务完成后重新GET核对done。

本轮机器证据保存在本目录。最初docs/evidence和INTEGRATION_REPORT属于e1674e2基线的历史记录，不能当成本轮当前状态。
Web http://127.0.0.1:5180，API http://127.0.0.1:8000/api；运行库为frontend/.runtime/review-20261104-1430.db，未提交。

## 真实模型接入时机与验收

现在可以进入小范围厂商模型联调；无需等F21/F23等页面完成。A负责后端模型配置/适配，B负责真实模式回归，C验证页面显示与实际保存。
当前配置仍是mock；既有real-mode stub测试不证明任何真实厂商调用。

推荐先评估阿里云百炼qwen-plus的非思考模式：有OpenAI兼容接口及Function Calling；只是选型建议，尚未对本仓库实测。实际可用模型/地域/endpoint以控制台为准；建议通过小样本后固定可用快照。
官方依据：https://help.aliyun.com/zh/model-studio/qwen-plus 、https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope 。

A配置AGENT_LLM_MODE=real、AGENT_LLM_BASE_URL、AGENT_LLM_API_KEY、AGENT_LLM_MODEL；密钥只放后端本地环境或根.env，禁止进入VITE_*或Git。配置后重启后端。
验收至少包含：真实上游请求成功及用量/响应证据、真实tool_calls、run_id与model_name、任务/数据落库、错误时不回退mock；随后验证缺信息提问、证据回答、拒绝越权、超时/限流。不能只看health的real标签就宣布接入成功。

## 优先优化与待A/B核对

1. **接入前处理耗时（A/C）**：HttpAdapter默认15秒超时，LLM单轮30秒、最多3轮；记录接口同步触发Agent。前端可能先报超时而后端仍继续落库。需对齐超时或设计后台运行状态查询，避免误导重试/重复写入；检查模型调用期间是否长期持有写锁。未用真实模型复现耗时，仅源码核对。
2. **证据送入模型（A/B）**：_run_real_llm的search_knowledge分支记录了实际evidence，但tool消息只回传ok和hits数量；需验证并提供所需片段及出处，才能证明真实回答使用检索证据。Mock场景通过不能替代该验证。
3. **自由文本安全（A/B）**：工具动作经过validators；response.content会直接append到responses。需核对独立输出安全校验，添加真实模式/对抗stub回归，避免只验证工具安全。此为源码风险审查，未宣称已复现真实模型违规。
4. **第二阶段体验（C）**：先补F21问题回答/恢复，再做F23任务协商、F24证据可定位展示、F25偏好、复评状态与完整演示；当前这些仅有后端能力或只读结果。
5. **录入与执行反馈（C）**：症状/血压/饮食用专用字段替代要求用户输入JSON；保存响应用摘要卡展示记录、事件、运行，原始JSON折叠保留；任务完成与复评同样摘要化。
6. **读取与体积（C）**：后端并发已修复，可在回归保护下调整全局串行队列，让健康检查不被长运行堵住；页面按路由拆包，再优化当前大包。先保证真实闭环，性能优化排后。
7. **统一团队交付（A/B/C）**：评审并发布合并后的完整分支，根README/文件地图与修复报告状态需更新；当前部分文档仍写前端未实现、等待B复验或148项，与最新149项及本次验证口径不一致。

本轮没有新增第二阶段业务功能，也没有修改A/B源码；backend/tests/docs的本地更新来自团队main原提交。
