"""有预算的真实模型UI冒烟服务器：不替换模型响应；仅本机、独立库，2次触发/6次HTTP。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

FRONT = Path(__file__).resolve().parents[1]
DB = FRONT / '.runtime/workbench-real.db'
LEDGER = FRONT / '.runtime/workbench-real-ledger.json'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend-root', type=Path, required=True, help='已审查的后端检出；不修改该检出')
    args = parser.parse_args()
    backend = args.backend_root.resolve()
    assert (backend / 'backend/app/main.py').is_file()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 8021))
    os.environ.update(DIABETES_DB_PATH=str(DB), AGENT_LLM_MODE='real', AUTOMATION_ENABLED='0',
                      AUTOMATION_POLL_SECONDS='0', FRONTEND_ORIGIN='http://127.0.0.1:5192')
    sys.path.insert(0, str(backend))
    from backend.app.config import settings
    cfg = settings()
    assert cfg.llm_api_key and cfg.llm_model == 'deepseek-flash'
    assert urlparse(cfg.llm_base_url).hostname == 'api.deepseek.com'
    assert cfg.db_path == DB
    from backend.app.agent import orchestrator, llm
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
    data = json.loads(LEDGER.read_text(encoding='utf8')) if LEDGER.exists() else {'triggers': [], 'requests': []}
    lock = threading.Lock()
    local = threading.local()
    original_run = orchestrator.run_agent
    original_plan = llm.OpenAICompatLLM.plan_actions
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=backend).decode().strip()

    def save():
        LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')

    def run(conn, patient_id, **kwargs):
        with lock:
            if len(data['triggers']) >= 2:
                raise RuntimeError('本轮UI真实冒烟2次业务预算已用完，禁止追加收费调用')
            entry = {'number': len(data['triggers'])+1, 'patient_id': patient_id, 'backend_sha': sha,
                     'trigger_type': kwargs.get('trigger_type'), 'started_at': time.time()}
            data['triggers'].append(entry)
            local.number = entry['number']
            save()
        try:
            result = original_run(conn, patient_id, **kwargs)
            entry.update(run_id=result.get('run_id'), status=result.get('status'))
            return result
        finally:
            with lock:
                entry['finished_at'] = time.time()
                save()

    def plan(client, **kwargs):
        with lock:
            if len(data['requests']) >= 6:
                raise RuntimeError('本轮UI真实冒烟6次厂商HTTP预算已用完')
            if data['requests'] and data['requests'][-1].get('status') == 'failed':
                raise RuntimeError('上游调用已失败，先分析，不自动重试')
            entry = {'number': len(data['requests'])+1, 'trigger': local.number}
            data['requests'].append(entry)
            save()
        start = time.monotonic()
        try:
            result = original_plan(client, **kwargs)
            raw = result.raw or {}
            entry.update(status='success', response_id=raw.get('id'), returned_model=raw.get('model'),
                         usage=raw.get('usage'), tools=[c.name for c in result.tool_calls])
            return result
        except Exception as exc:
            entry.update(status='failed', error=type(exc).__name__)
            raise
        finally:
            with lock:
                entry['latency_ms'] = round((time.monotonic()-start)*1000)
                save()

    orchestrator.run_agent = run
    llm.OpenAICompatLLM.plan_actions = plan
    from backend.app.main import app
    import uvicorn
    print(json.dumps({'db': str(DB), 'backend_sha': sha, 'triggers_used': len(data['triggers']),
                      'requests_used': len(data['requests']), 'limits': [2, 6]}))
    uvicorn.run(app, host='127.0.0.1', port=8021)

if __name__ == '__main__':
    main()
