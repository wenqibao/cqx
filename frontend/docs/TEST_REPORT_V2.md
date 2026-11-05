# 本轮测试报告 V2

日期2026-11-05；实现提交52c966b，环境Node24.22.1/npm12/Python3.13.5，Chromium（本机Chrome）。证据目录`evidence/workbench/`。

| 执行 | 实际结果 | 证据 |
| --- | --- | --- |
| npm ci | 安装131包，审计132包，0已报告漏洞；旧Vite占用原生绑定问题解除后成功 | npm-ci.log |
| npm run typecheck | PASS | typecheck.log |
| npm test | 30/30 PASS，保留原11项，新增19项 | unit-results.json、unit.log |
| npm run build | PASS；路由懒加载，仍有两个超过500KB块提示 | build.log |
| npm run test:e2e | 15/15 PASS，约2分钟，真实隔离FastAPI/SQLite、mock规划器 | browser-results.json、e2e-final.log |
| Python兼容性回归 | 原149项通过，0失败/错误；未改后端测试预期 | backend-pytest.xml、backend-pytest.log |
| 合成场景回放 | 33/33 PASS，明确mock模式 | scenarios.json、scenarios.log |
| 并发预检 | 9/9只读200 | 见本轮联调记录；主代码已含A并发修复 |
| 实际重启持久化 | 停止并重启专用8020进程；患者/记录/任务/版本一致 | persistence-restart.json |
| 视觉/可访问性 | 1920×1080、1440×900、1366×768实际截图，无文档横向溢出；reduce下选择患者通过；7/7主色对比度AA | dashboard-*.png、contrast.log |
| DeepSeek浏览器冒烟 | 1 PASS / 1 FAIL；2触发、6HTTP、21,924 tokens，未重试 | real-smoke.json、real-*.png |

## 覆盖与边界

E2E覆盖：八个一级模块、创建患者、档案、八类录入与重复、CSV/JSON错误行、自动触发、真实run查询、工具与版本、人工完成、三分支复评、人工结案、模拟记不清回答恢复、偏好覆盖清除、通知已读、多事件priority_order、知识无结果、CLI复制不执行、真实报告导入、非法报告、断连/502/无工具与跨患者拒绝。只对错误和无工具显示使用受控Playwright响应，明确属于UI边界测试，不冒充厂商响应。

单测覆盖原有HTTP错误/空数据/网络/取消/模式隔离/单一records请求，新增写入长超时不重试、staff_demo来源、取消不发送、500、JSON导入、报告模式与不一致汇总、非法格式、通知患者链接、日志脱敏。

E2E启动守卫仅允许backend mock与frontend/.runtime/workbench-test.db；它不会发起收费模型调用。Real冒烟不在npm自动测试内，使用独立账本和预算；原始完整响应保留`.runtime/real-smoke-raw.json`，不把它与Mock测试混算通过率。

## 失败与限制

- **产品待解决**：F03不同BP被去重、F06 Real三轮只读失败；详见BACKEND_DEPENDENCIES.md。全绿前端测试不覆盖/不掩盖这两项真实后端业务失败。
- **修正后的测试问题**：编码URL匹配、导入文件后才出现选项、恢复ID嵌套路径、装饰图标参与导航名称；跨模块tab串入和reduce动画也已修正。早期失败日志保留，不以它们替代最终结果。
- **未验证**：Real随访答复/协商全闭环、后台持续轮询、生产负载、真实患者、临床有效性、机构认证授权。未给这些项写PASS。
- 仍有现有Ant Design组件弃用提示和构建大块提示，不影响本轮功能运行，不宣称生产性能优化已完成。

本轮完整F矩阵24 PASS/2 FAIL；因此只能交付“完整前端入口和已验证的本机业务能力”，不能宣称“完整真实模型参赛验收通过”。

全量15项E2E在核心实现6cfb273上通过。52c966b随后仅增加默认显示真实运行拒绝摘要；已用只读浏览器核验真实失败及证据，0个POST，并再次通过typecheck、30项单测和build。没有为此重跑收费模型。

仓库忽略原始*.log，原始命令日志保留本机；供clone核验的成功命令输出统一在evidence/workbench/commands-output.json，未强制添加日志。公开pytest XML仅脱敏hostname，原XML在.runtime/backend-pytest-original.xml。
