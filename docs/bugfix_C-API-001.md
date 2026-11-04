# C-API-001 修复记录（A 提交）

| 项 | 内容 |
| --- | --- |
| 缺陷编号 | C-API-001 |
| 等级 | P0（真实演示下并发读必失败，前端被阻断） |
| 报告人 | C（前端联调） |
| 基线 | `e1674e2`（main），Python 3.13.5 / FastAPI 0.115.14 / Starlette 0.46.2 |
| 现象 | `state` / `tasks` / `runs` 各 3 次并发，9 次中 8 次 500，响应无 CORS 头，浏览器显示为 CORS 失败 |
| 异常 | `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.` |
| 状态 | 已修复，A 本地回归通过，等待 B 复验 |

## 1. 根因

`backend/app/api/deps.py::get_conn` 是**同步生成器依赖**。Starlette 对同步依赖和同步路由分别调用
`run_in_threadpool`，两次分派**不保证落在同一个线程**：

```
线程 A: get_conn()            -> sqlite3.connect(...)   建立连接（绑定线程 A）
线程 B: 路由函数执行           -> conn.execute(...)      跨线程使用 -> ProgrammingError
线程 C: 依赖退出 conn.close()  -> 同样跨线程
```

单请求串行时线程池可能复用同一线程，所以 `TestClient` 的串行用例**从未暴露**这个问题；
一旦并发，线程池扩到多个 worker，必然踩中。

次生现象：Starlette 的 `ServerErrorMiddleware` 在 CORS 中间件**外层**，未捕获异常返回的 500
不带 `Access-Control-Allow-Origin`，浏览器把它显示成 CORS 错误，掩盖了真实原因。

## 2. 修复

| 文件 | 改动 |
| --- | --- |
| `backend/app/db/connection.py` | `sqlite3.connect(..., check_same_thread=False)`，并加 `PRAGMA busy_timeout=30000`、`PRAGMA synchronous=NORMAL`。每个请求持独立连接，同一连接上的"依赖进入 → 路由 → 依赖退出"是串行过程，因此关闭线程绑定安全；`busy_timeout` 避免并发写直接抛 `database is locked` |
| `backend/app/main.py` | 新增 `Exception` 兜底处理器：500 时回填该请求来源的 CORS 头并返回结构化 JSON（`{detail, error, path}`，不含堆栈），避免"后端报错、浏览器显示 CORS 失败" |
| `tests/unit/test_db_threading.py`（新增） | ① 在另一个线程里使用连接；② 校验 PRAGMA；③ 两个连接并发使用 |
| `tests/integration/test_concurrent_api.py`（新增） | 起**真实 uvicorn**：① 9 个并发 GET 全 200；② 6 个并发写全 201 且真实落库；③ 非 2xx 响应仍带 CORS 头 |

## 3. 复现与验证（A 本地实测）

修复前（真实 uvicorn，`state`/`tasks`/`runs` 各 3 次并发）：

```
200: 0 / 9
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
The object was created in thread id 20060 and this is thread id 20700.
```

修复后：

```
200: 9 / 9
```

回归：

```
python -m pytest                 # 122 passed（airace 基线 116 + 新增 6）
python scripts/run_scenarios.py  # 9/9 PASS（airace 基线）
```

> 在正式仓库（含 B 的 24 个场景）上应为 **148 passed**、**33/33 PASS**，由 B 在合并后的分支上复验。

## 4. 请 B 复验

1. 在真实 uvicorn（非 TestClient）下并发请求 `state`/`tasks`/`runs`，9/9 返回 200；
2. 并发写入不出现 `database is locked`，且每条记录真实落库；
3. 连接关闭/回滚正常：并发后进程退出无残留锁文件（`-wal`/`-shm` 可回收）；
4. 患者隔离：并发请求不同患者，响应中的 `patient_id` 不串号；
5. 全量 `pytest` 与 33 个场景无回归。

## 5. 已知限制

- SQLite 仍是单写者模型：并发写靠 `busy_timeout` 排队，高并发下吞吐有限；本项目为单机演示，可接受。
- 内存数据库（`":memory:"`）与 `check_same_thread=False` 组合时仍是"每个连接一个库"，测试中不要用内存库做跨连接断言。
