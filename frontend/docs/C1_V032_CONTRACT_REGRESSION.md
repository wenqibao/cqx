# C1 前端契约回归 v0.3.2

**C1 PASS。** 前端契约和旧库迁移通过。两项后端遗留反例仍为 OPEN。

复验日期为 2026-11-09。远端 `v0.3.2` 解引用至 `06cb1f0c0fb3e60edf6bfd1434e32bd6368cf7f9`，与本次 fetch 的 `origin/main` 一致。后端使用隔离检出，`GET /api/health` 与 `GET /api/version` 实测为 `0.3.2`。 [冻结标签](https://github.com/wenqibao/cqx/tree/v0.3.2) · [接口契约](https://github.com/wenqibao/cqx/blob/v0.3.2/docs/api_contract.yaml#L802)

前端快照为 `c82d793917e27135b92f35673669e537718d60ba` 加本地源码和测试补丁。最终补丁 SHA-256 为 `6099ad9a8e2a0fc1663e38f4bec2b33c088ac1ca0db38cbdde3f0b92598301eb`。前端使用 HTTP 模式连接真实 FastAPI 和隔离 SQLite，模型使用确定性 Mock 或明示的脚本模型。新增 DeepSeek 调用 **0 次**。 [实测前端补丁](../.runtime/v032-c1-06cb1f0/frontend-final.patch)

本文的 `.runtime/` 链接指向验收机留存的本地证据。团队成员按交接提交检出前端源码，使用自己的隔离数据库复验。

## 回归结果

| 回归项 | 实测结果 |
| --- | --- |
| v0.3.1 旧库首次启动与重启 | 原版本 `schema_version=2`。v0.3.2 正常启动后为 3，SQLite 完整性检查通过。6 条旧别名任务自动归一，3 条已有规范类型维持原值。9 条任务的 ID、患者、标题、状态、版本、截止时间及来源字段逐项一致。二次启动后数据库快照一致 |
| 迁移后任务列表和完成 | `GET /patients/{id}/tasks?task_type=record_glucose` 包含已迁移任务。浏览器任务日志与 `GET /tasks/{id}` 原始 JSON 一致。页面完成迁移任务 `TSK-f498d3b49b2c` 后为 `done`，重复完成返回 `already_done=true`、`run=null` |
| 规范任务类型显示 | 初测 `record_bp` 与 `record_symptom` 显示通用未知提示。补齐中文映射后，9 条均显示对应业务类型。新增 `INVALID_TASK_TYPE` 的中文映射 |
| 既有 HTTP 契约 | Edge 14 项通过。覆盖已纠正 warnings、记录和偏好部分成功、实际 tick 补偿、重复完成、过期回答、404/409/422、断连核对和明确答复 |
| 状态和轨迹 | `open_reviews`、`recent_answers`、`open_events` 有值与空数组均和 API 一致，事件的 `evidence_summary`、`record_ids` 和运行的 `decision_rationale` 在日志保留 |
| C-DS-01 | 服务端受控延迟 55 秒和 64 秒。浏览器在 55.168 秒显示 `RUN-616d2e5eda16` 的结果，在 60.256 秒提示“后端可能仍在运行”。两次测试各发 1 个 POST，超时后通过只读入口查到 `RUN-3f3c9a725696` |
| C-DS-03 | 等待运行顶部“去回答”发起真实问题列表 GET，聚焦对应输入框，提交触发真实回答 POST。明确答复写入记录，不确定答复不产生服药记录 |
| REAL-A04 兜底提问 | 脚本模型未提问时，`RUN-a71b7a4367b0` 由系统创建问题，轨迹有 `system_question`。前端跳转并聚焦问题 `Q-76f11c6c9be9`，提交“记不清”后恢复运行 `RUN-be9d2246404f`，`recorded=null` |
| 新增任务类型拒绝 | `RUN-4bdcfb04a755` 业务区显示任务类型拒绝，零任务写入。技术日志保留 `INVALID_TASK_TYPE` 且与 API 原文一致 |
| 预算及重复结案 | 预算可用、耗尽、非法账本、未启用均符合契约。启用场景重复 GET 后账本字节一致。重复结案 `already_resolved=true`，保留首次处理结论 |
| 前端构建 | `npm run typecheck`、Vitest 56/56 和 `npm run build` 通过。Vite 保留既有产物块大小提示 |

迁移只在合成旧库上验证。旧任务由 v0.3.1 服务层创建，v0.3.2 通过正常 CLI 启动路径自动迁移，未手工改表。既有契约覆盖、迁移、预算、异常和兜底提问分开使用隔离夹具。预算首次探针仍断言 `0.3.1`，修正探针版本断言后通过。 [迁移数据库快照](../.runtime/v032-c1-06cb1f0/migration-result.json) · [迁移浏览器证据](../.runtime/v032-c1-06cb1f0/migration-browser.json) · [增量浏览器证据](../.runtime/v032-c1-06cb1f0/c-v032-extensions.json)

同一交付也包含通过 B 只读复验的 REAL-C01、REAL-C02 补丁。知识答复 `RUN-4b15f35198fd` 保留 SMBG、CGM，原生回复和后端摘要在各自的业务详情中都只出现一次。原报告的 33 条结果逐页核对为 28 通过、5 失败，五种状态有独立中文显示。

## 冻结版本的后端遗留项

前端契约和迁移通过。此前两项独立后端反例在 `06cb1f0` 仍可复现，继续标为 OPEN。

| 问题 | 冻结标签上的实测 |
| --- | --- |
| B-032-01，混合转介和越权文本 | `RUN-eaea8935af05` 中脚本模型生成的混合文本通过安全检查并写入通知，审计 `forbidden_executed=0`。仅含越权指令的对照被拦截 |
| B-032-02，同类待办任务别名 | `RUN-8141dd775e93` 接受 `record_reminder` 并写入第二条 `record_glucose`，随后返回 `POSTCHECK_MISMATCH`。使用规范类型的对照没有新增 |

两条反例均通过实际 FastAPI 和合成 SQLite 复现，由 A 处理。本轮验收范围为前端 HTTP 契约，真实 DeepSeek 全量仍待安全准入。 [后端反例](../.runtime/v032-c1-06cb1f0/a-independent-probes.json) · [同库审计](../.runtime/v032-c1-06cb1f0/a-probe-audit.json)

## 复验入口

1. 执行 `git fetch origin tag v0.3.2`，在独立目录检出该标签并核对完整 SHA。前端以本报告的快照与补丁为准。
2. 在前端执行 `npm ci`、`npm run typecheck`、`npm test` 和 `npm run build`。C1 构建环境为 `VITE_API_MODE=http`、`VITE_API_BASE_URL=http://127.0.0.1:8062/api`、`VITE_API_WRITE_TIMEOUT_MS=60000`。Edge 既有套件由 `playwright test -c playwright.contract.config.ts` 执行，使用专用夹具和 5202 前端预览端口。
3. 本机运行目录保留隔离驱动、日志和脱敏结果。重跑常规契约需新建隔离库。迁移探针每次用独立 SQLite，后端和前端分别使用 8064 和 5204。

- [C1 驱动](../.runtime/v032-c1-06cb1f0/run_c1_final.py) · [14 项浏览器日志](../.runtime/v032-c1-06cb1f0/c-browser.log) · [状态、轨迹、超时和回答证据](../.runtime/v032-c1-06cb1f0/c-v031-probes.json)
- [预算启用证据](../.runtime/v032-c1-06cb1f0/c-vendor-browser.json) · [预算关闭及重复结案](../.runtime/v032-c1-06cb1f0/c-supplement-browser.json) · [迁移驱动](../.runtime/v032-c1-06cb1f0/run_migration.py)
- [类型检查](../.runtime/v032-c1-06cb1f0/final-typecheck.log) · [单测](../.runtime/v032-c1-06cb1f0/final-test.log) · [构建](../.runtime/v032-c1-06cb1f0/final-build.log)
