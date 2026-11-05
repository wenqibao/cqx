# 页面与实际API映射 V2

2026-11-05。基于实际routes/models/service及本轮联调，不根据端点名称猜字段。下表统一省略`/api`前缀。所有HTTP仅由`src/api/httpAdapter.ts`发送；`workbench.ts`集中路由和Zod契约，旧基础接口保留在types/client适配器。

| 页面/路由 | 实际接口 | 使用与验证 |
| --- | --- | --- |
| 全局 | GET health、system/mode、patients | 连接/数据库/模型/患者；30秒轻量心跳，写入中暂停，失败无Mock回退 |
| 监管总览 `/` | 每患者GET state、reviews、runs、notifications | 有界读取、失败患者单独标记，部分加载统计不冒充全量 |
| 患者管理 `/patients` | GET/POST patients | POST强制is_synthetic=true，重新GET确认；不提供不存在的删除/修改 |
| 档案 `/patients/:id` | GET patients/{id}、state、records?days=3/7/14、state/history、events、tasks、questions、preferences?include_history=true | 基础资料/缺失字段/观测趋势/历史版本；history仅版本时间 |
| 录入 `/monitoring` | POST patients/{id}/records、GET records/events | RecordCreate八类字段；读取record与automation，不补一次agent/runs |
| 导入 `?tab=import` | POST patients/{id}/records/import | CSV原文或JSON对象数组；将嵌套payload平铺为后端import实际支持字段；显示imported/duplicates/failed/errors |
| 事件 `?tab=events` | GET events、POST events/scan | 后端规则级别、原因和状态；手动扫描明确标识，不冒充自动化 |
| 随访 `/followups` | GET questions、POST questions/{id}/answer | answer_text、trigger_agent=true；恢复位置为`resume.run.run_id`，不确定性及recorded以原响应为准 |
| 偏好 `?tab=preferences` | GET/POST preferences、DELETE preferences/{kind} | kind/source严格使用已支持值；显示active/superseded/cleared及历史 |
| 任务 `/tasks` | GET tasks、GET tasks/{id}、POST complete、POST reschedule、GET versions | 完成及直接改期staff_demo；complete run_agent=false，后端仍执行复评；重新读取实际状态 |
| 复评 `?tab=reviews` | GET reviews、POST reviews/{id}/resolve | 三分支记录、reason/detail；人工decision/note由工作人员填写 |
| Agent `/agent` | POST patients/{id}/agent/runs、GET patients/{id}/runs、GET runs/{run_id} | 发起一次请求、按run查询实际工具和结果；Real有费用确认，失败/等待/拦截不伪装成功 |
| 协商 `?tab=negotiate` | POST agent/runs | 模拟患者时间约束；与直接reschedule分开标示，版本关联run可核查 |
| 知识 `/agent/knowledge` | GET knowledge、GET knowledge/search?q= | 来源/机构/版本/段落/匹配文本；独立检索不伪装成运行证据 |
| 审计 `/audit` | GET system/audit?limit=200 | 实际拒绝/升级、run跳转；原样展示计数及已知口径限制 |
| 通知 `/notifications` | GET notifications、POST notifications/{id}/read | 未读及对象深链，已读重新GET，保留患者ID |
| 系统 `/system` | GET health、system/mode、version、automation/jobs?limit=100 | 当前配置和实际作业，不以mode.ok当厂商调用证明 |
| 维护 `?tab=maintenance` | POST automation/clock、POST automation/tick | 合成数据库确认后手动推进/执行，明确全库影响，不作为权限保护 |
| CLI与报告 | 浏览器File API，本地真实日志与JSON | 不执行Shell、pytest或场景脚本；复制只复制，上传只本地解析，不发HTTP |

未暴露`admin/reset`；未增加后端接口；知识重建是可选维护功能，本轮不提供入口。`scan`只进行规则检测，`tick`可能根据实际作业触发业务，不能把两者说成模型一直自主运行。

读取默认15秒、写入180秒；串行在途队列控制请求量。患者变化的第一帧即隐藏旧数据，并取消旧读取；任务/run所属患者不一致时拒绝展示。写入使用全局同步锁和按钮禁用，不自动重试，无幂等保证时超时先查询。

404/422/500/502、网络、超时、响应结构错误均有明确提示；非JSON错误保留HTTP码。Zod根据真实可选字段保留缺项，不给患者补年龄、服药事实、目标或临床判断。
