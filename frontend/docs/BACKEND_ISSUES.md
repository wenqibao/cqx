# A/B 联调问题

## C-API-001：ASGI 并发 GET 导致 SQLite 跨线程异常

基线 e1674e2101bc7d1111191737626ad818aab75fda；Python3.13.5、FastAPI0.115.14、Starlette0.46.2、AnyIO4.7.0；标准uvicorn真实演示库。未改后端。

请求：GET /api/patients/P001/state、/tasks、/runs，各3次并发。预期9次200。

实际9次中8次500，正文Internal Server Error，错误响应缺少Access-Control-Allow-Origin，浏览器表现为CORS失败。逐请求响应在evidence/concurrent-reads.json；原始堆栈evidence/server.log。

异常：`sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.`

定位：backend/app/api/deps.py的get_conn创建/关闭，以及routes_agent.list_tasks→tasks.service.list_tasks→patients.get_patient_or_none的conn.execute。同步依赖与路由在线程池中可跨线程，单TestClient串行测试未暴露。

前端缓解：同一HttpAdapter所有请求串行排队；重新启动原版后端后闭环实测通过。不修改SQLite配置或后端逻辑，**不能关闭后端缺陷**；多标签页/多客户端仍可能触发。需A修复、B对标准uvicorn并发、连接关闭/回滚、患者隔离复验，发布前解决。

## C-ENV-001：终端 Git 认证失败

普通clone/ls-remote/fetch尝试遇到Empty reply；禁用交互后明确报could not read Username、terminal prompts disabled。GitHub连接可访问私有库，因此通过已授权Git数据API取得main引用、树和全部143个blob，逐对象校验并恢复SHA完全一致的原始浅提交；结束前再次核对main仍为e1674e2。不冒充成功常规fetch；补全Git历史与push待终端认证配置。

## C-ENV-002：模型 stub 走代理导致502

首次后端回归的两个real-mode stub测试因本机代理得到502，设置NO_PROXY=127.0.0.1,localhost后相同源码142项通过。未改测试预期；真实厂商模型仍未测试。
