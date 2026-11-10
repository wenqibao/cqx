"""只启动隔离的前端联调后端；保留已有数据库，不删除、不重置、不调用收费模型。"""
from pathlib import Path
import os
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'frontend/.runtime/workbench-test.db'
sys.path.insert(0, str(ROOT))
os.environ.update(DIABETES_DB_PATH=str(DB), AGENT_LLM_MODE='mock', AGENT_LLM_API_KEY='',
                  AUTOMATION_ENABLED='0', AUTOMATION_POLL_SECONDS='0', FRONTEND_ORIGIN='http://127.0.0.1:5180')

if __name__ == '__main__':
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 8020))
    from backend.app.db.connection import connect
    from scripts.reset_demo import seed
    if not DB.exists():
        DB.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(DB)
        try:
            seed(conn)
            conn.commit()
        finally:
            conn.close()
    import uvicorn
    print(f'前端隔离后端：{DB}；mock；保留已有数据；127.0.0.1:8020')
    uvicorn.run('backend.app.main:app', host='127.0.0.1', port=8020)
