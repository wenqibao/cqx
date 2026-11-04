# C 第一阶段真实联调交付报告

日期2026-11-04；检出目录D:\cqx-current；前端D:\cqx-current\frontend。
基线main e1674e2101bc7d1111191737626ad818aab75fda，分支feature/frontend-c-integration。旧D:\cqx独立Mock保留。只修改frontend，未改A/B业务或文档。

## 实际运行

Web http://127.0.0.1:5180；FastAPI http://127.0.0.1:8000/api；仅本机。专用SQLite位于frontend/.runtime/integration.db（忽略提交），按README的reset_demo初始化P001/P002/P003。

HTTP真实接入，后端llm_mode=mock：确定性规划器，真实工具和SQLite，不是前端模拟HTTP，不宣称真实厂商模型调用。

## 本次真实闭环证据

POST records实际保存record.id=28，automation创建3个事件、3次运行。
本次运行标识：`RUN-427667729e53`。未额外POST /agent/runs，浏览器采集agentPosts=[]。
GET trace包含真实tool_call、tool_result、阶段、证据和关联任务。完成任务`TSK-c371b472c713`后响应status=done，GET tasks再次核对done，收到1条复评结果。P002最新数据在P001操作前后保持一致。

补充浏览器实测：P003步数4000与服药确认1均201保存，响应kind/value/patient_id核对通过，原始结果record-types-api.json。修复记录类型切换残留数值/单位及服药选择被清空的问题；先复现断言失败，修正后通过。
结束时串行GET health、patients、P001/state及system/audit均200，forbidden_executed=0，见final-health-audit.json。

原始请求结果：evidence/real-api.json；服务日志server.log；实际截图overview/records/tasks/runs/trace-1440.png、tasks-completed-1440.png、laptop-1366.png、backend-offline.png。

## 构建与测试（实际执行）

- npm install：npm12+Node24安装成功，锁文件已提供，审计0个已报告漏洞。
- npm run build：TypeScript严格检查及Vite8.3.5构建通过，原始输出build.log。
- npm test：11通过，0失败，见unit-results.json。覆盖404/422/502、非JSON502、网络、超时、空列表、模式隔离、记录唯一请求、串行排队。
- npm run test:e2e：核心3通过、0失败；实际浏览器连接FastAPI，覆盖核心闭环、患者切换/笔记本1366px与断连无回退。原始browser-results.json。
- playwright test e2e/record-types.spec.ts --reporter=json：补充1通过、0失败；真实步数/服药保存及切换类型回归，见record-types-results.json。浏览器共4项，分两次执行。
- python -m pytest：142通过、0失败、0错误；XML及日志已保存。NO_PROXY配置后通过，未改测试。
- python scripts/run_scenarios.py --report frontend/.runtime/scenarios.json：33/33通过；复制原报告到evidence/scenarios.json，未修改evaluation。

## 并发限制，未关闭

9个只读并发GET中8个HTTP500，SQLite跨线程错误，详见BACKEND_ISSUES.md及concurrent-reads.json、server.log。前端串行客户端下上述闭环通过，不等于后端并发验收通过；多标签页或多个客户端仍可能失败。需A修复、B复验再发布，未改后端参数或测试预期。

首次前端联调修正fetch的this绑定；测试隔离修正断网拦截范围（仅8000/api，避免拦截前端src/api模块）、中文确认按钮空格匹配；记录响应中的新事件和run_id严格校验，未用历史运行替代。

## Git 与协作

普通git fetch/clone因本机私有仓库认证失败。通过已授权GitHub API取得并再次核对最新main，143个blob及完整树逐对象SHA校验，恢复原始commit的完全相同SHA浅检出。不是常规git fetch成功，终端认证与完整历史仍待配置。

本地实际commit见git log -1或交付聊天；未push、未合并main。变更文件清单见FILE_MAP.md，供A更新主工程PROJECT_FILE_MAP（按本次指令不改A文档）。

## 范围与后续

已完成四个核心页面：健康总览、健康数据、健康任务、Agent轨迹。全部通过统一API客户端，模式/合成/连接状态常驻，状态与失败来自真实接口。
主动回答F21、协商F23、知识证据交互增强F24、偏好F25、动态复评与演示脚本整合留到第二阶段；当前只展示后端返回的待回答问题、轨迹证据及完成响应中的复评。
当前主包约1.72MB，有体积警告；未做生产拆包优化。未测试真实厂商LLM或临床效果。A/B协助重点为SQLite并发修复与标准ASGI复验。
