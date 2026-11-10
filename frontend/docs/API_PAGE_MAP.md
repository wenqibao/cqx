# 第一阶段 API 与页面映射

依据main e1674e2的api_contract、models、routes和tests/api/test_api.py。只有src/api/httpAdapter.ts发业务HTTP请求。

| 方法与路径（/api前缀） | 用途 | 实际状态 |
|---|---|---|
| GET /health | 全局连接、database.ok、llm_mode | 通过 |
| GET /patients | 患者选择items[] | 通过 |
| GET /patients/{id}/state | 档案、latest、事件、任务、待回答问题、缺失与趋势 | 串行通过 |
| GET /patients/{id}/records?days=7 | 图表与记录历史，保留实际值/单位/时间 | 串行通过 |
| POST /patients/{id}/records | RecordCreate；record及automation事件/runs | 通过，本次响应包含新事件与run_id |
| GET /patients/{id}/tasks | 状态、优先级、期限、来源 | 串行通过 |
| POST /tasks/{task_id}/complete | changed_by=patient,run_agent=false；task/reviews | 通过，重新读取done |
| GET /patients/{id}/runs | 运行列表，触发来源、状态、模式 | 串行通过 |
| GET /runs/{run_id} | run/steps/evidence/tasks/questions/reviews | 通过 |

RecordCreate：kind为fasting_glucose/postprandial_glucose/steps/weight/medication_taken/symptom/meal/bp；value、unit、recorded_at、note、payload、trigger_agent按后端模型提交。前端只做格式与必填验证，业务范围由后端决定。

404/422/502保留状态与原始错误，非JSON错误也保留HTTP码。超时/网络/取消/结构错误/空数据明确区分；取消旧患者请求并丢弃过期结果，写入时锁定患者及按钮，不自动重试或回退Mock。

第二阶段主动回答、协商、偏好与动态复评入口未开发。本阶段复评仅展示任务完成实际响应。并发API仍有未修复问题，见BACKEND_ISSUES.md。
