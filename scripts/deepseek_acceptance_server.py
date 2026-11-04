"""仅用于本机真实验收：独立库/端口、持久化6次Agent预算、统计每次真实HTTP请求。

不改写模型响应或业务结果；预算跨进程重启保留。勿用于正式服务。
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AcceptanceBudget:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = json.loads(path.read_text(encoding="utf8")) if path.exists() else {"trigger_limit": 6, "request_limit": 18, "triggers": [], "requests": []}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf8")

    def reserve_trigger(self, scenario, patient_id, trigger_type):
        with self.lock:
            if len(self.data['triggers']) >= 6:
                raise RuntimeError("验收6次Agent业务触发预算已耗尽，禁止继续调用")
            entry = {"number": len(self.data['triggers']) + 1, "scenario": scenario, "patient_id": patient_id, "trigger_type": trigger_type, "at": datetime.now(timezone.utc).isoformat(), "run_id": None,
                     "git_sha": subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()}
            self.data['triggers'].append(entry)
            self.save()
            return entry

    def reserve_request(self, trigger):
        with self.lock:
            if len(self.data['requests']) >= 18:
                raise RuntimeError("验收真实HTTP请求达到18次硬上限")
            if len(self.data['requests']) >= 2 and all(r.get('status') == 'failed' for r in self.data['requests'][-2:]):
                raise RuntimeError("连续两次上游失败，停止后续真实请求")
            entry = {"number": len(self.data['requests']) + 1, "trigger_number": trigger['number'], "scenario": trigger['scenario'], "status": "inflight", "token_usage": None}
            self.data['requests'].append(entry)
            self.save()
            return entry


def main():
    import time
    import uvicorn
    from backend.app.agent import orchestrator, llm
    from backend.app.config import settings

    cfg = settings()
    expected = (ROOT / 'data/runtime/deepseek_acceptance.db').resolve()
    if cfg.db_path != expected or cfg.llm_mode != 'real' or cfg.llm_model != 'deepseek-flash':
        raise RuntimeError("必须使用指定独立验收库及real/deepseek-flash配置")
    if urlparse(cfg.llm_base_url).hostname != 'api.deepseek.com':
        raise RuntimeError("本轮仅允许官方DeepSeek厂商地址")
    if cfg.automation_poll_seconds or os.environ.get('AUTOMATION_ENABLED') != '0':
        raise RuntimeError("验收必须禁用无人值守调度，所有额外业务触发计入预算")
    budget = AcceptanceBudget(ROOT / 'evaluation/reports/deepseek_acceptance_ledger.json')
    local = threading.local()
    original_run = orchestrator.run_agent
    original_plan = llm.OpenAICompatLLM.plan_actions

    def counted_run(conn, patient_id, **kwargs):
        case = (ROOT / '.tmp/active-real-scenario.txt').read_text(encoding='utf8').strip()
        if case not in {'R01','R02','R03','R03-answer','R04','R05','R06'}:
            raise RuntimeError("未指定有效验收场景，拒绝意外Agent触发")
        entry = budget.reserve_trigger(case, patient_id, kwargs.get('trigger_type'))
        local.trigger = entry
        try:
            outcome = original_run(conn, patient_id, **kwargs)
            entry.update({'run_id': outcome['run_id'], 'status': outcome['status']})
            return outcome
        except Exception as exc:
            entry['error'] = str(exc).replace(cfg.llm_api_key, '[REDACTED]')[:400]
            raise
        finally:
            with budget.lock:
                budget.save()

    def counted_plan(client, **kwargs):
        entry = budget.reserve_request(local.trigger)
        start = time.monotonic()
        try:
            result = original_plan(client, **kwargs)
            raw = result.raw or {}
            entry.update({'status': 'success', 'response_id': raw.get('id'), 'returned_model': raw.get('model'),
                          'token_usage': raw.get('usage'), 'tool_calls': [{'name': c.name, 'arguments': c.arguments} for c in result.tool_calls]})
            return result
        except Exception as exc:
            entry.update({'status': 'failed', 'error': str(exc).replace(cfg.llm_api_key, '[REDACTED]')[:400]})
            raise
        finally:
            entry['latency_ms'] = round((time.monotonic()-start)*1000)
            with budget.lock:
                budget.save()

    orchestrator.run_agent = counted_run
    llm.OpenAICompatLLM.plan_actions = counted_plan
    from backend.app.main import app

    async def captured_app(scope, receive, send):
        case_path = ROOT / '.tmp/active-real-scenario.txt'
        case = case_path.read_text(encoding='utf8').strip() if case_path.exists() else 'preflight'
        capture = scope['type'] == 'http' and scope.get('method') == 'POST'
        chunks = []
        status = None

        async def capture_send(event):
            nonlocal status
            if capture and event['type'] == 'http.response.start':
                status = event['status']
            if capture and event['type'] == 'http.response.body':
                chunks.append(event.get('body', b''))
                if not event.get('more_body', False):
                    # 仅保存业务响应，不保存任何请求/响应头；客户端断连也保留真实保存结果。
                    body = b''.join(chunks).decode('utf8').replace(cfg.llm_api_key, '[REDACTED]')
                    target = ROOT / f'evaluation/reports/deepseek_capture_{case}_{len(budget.data["triggers"])}.json'
                    target.write_text(json.dumps({'path': scope['path'], 'status': status, 'body': json.loads(body)}, ensure_ascii=False, indent=2), encoding='utf8')
            await send(event)

        await app(scope, receive, capture_send)

    print(json.dumps({'acceptance_db': str(expected), 'port': 8010, 'triggers_used': len(budget.data['triggers']), 'requests_used': len(budget.data['requests'])}))
    uvicorn.run(captured_app, host='127.0.0.1', port=8010, log_level='info', lifespan='on')


if __name__ == '__main__':
    main()
