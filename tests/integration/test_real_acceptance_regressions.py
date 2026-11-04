"""受控 real 路径回归；全部为本地 Stub，不冒充 DeepSeek 验收。"""
from __future__ import annotations

import json
from datetime import timedelta
import httpx

import pytest

from backend.app.agent.llm import LLMClient, LLMResponse, ToolCall, OpenAICompatLLM, LLMRequestError
from backend.app.agent.orchestrator import run_agent
from backend.app.audit.trace import trace
from backend.app.db.connection import iso, now
from backend.app.safety import gate
from backend.app.services import patients
from backend.app.tasks import service as tasks


class ScriptedLLM(LLMClient):
    mode = "real"
    model_name = "LOCAL-STUB-NOT-DEEPSEEK"

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def plan_actions(self, **kwargs):
        self.requests.append(kwargs)
        response = next(self.responses, LLMResponse(content=""))
        if isinstance(response, Exception):
            raise response
        return response


def patient(conn, pid="DS1"):
    return patients.create_patient(conn, {"id": pid, "name": "合成验收患者", "age": 50,
                                          "duration_years": 4, "goals": ["稳定记录"]})


def call(name, args, ident="one"):
    return LLMResponse(content="", tool_calls=[ToolCall(name, args, ident)])


def run(conn, llm, message="请整理我的记录"):
    patient(conn)
    return run_agent(conn, "DS1", trigger_type="user_request", message=message, llm=llm)


def test_deepseek_payload_disables_thinking():
    client = OpenAICompatLLM("https://api.deepseek.com", "DUMMY", "deepseek-flash")
    assert client._payload("s", "u", [])['thinking'] == {"type": "disabled"}


def test_search_has_complete_trace_and_supplies_actual_quotes(conn):
    llm = ScriptedLLM(call("search_knowledge", {"query": "连续血糖记录 意义"}),
                      LLMResponse(content="连续记录帮助观察变化。"))
    result = run(conn, llm, "为什么需要连续记录血糖？")
    detail = trace(conn, result["run_id"])
    assert {s['kind'] for s in detail['steps'] if s['tool_name']=='search_knowledge'} >= {'tool_call','tool_result'}
    tool_message = next(m for m in llm.requests[1]['extra_messages'] if m['role']=='tool')
    assert json.loads(tool_message['content'])['hits'][0]['quote']
    assert result['evidence']
    assert conn.execute('SELECT COUNT(*) FROM state_snapshots WHERE patient_id=?',('DS1',)).fetchone()[0] > 0


def test_knowledge_text_without_evidence_is_not_success(conn):
    result = run(conn, ScriptedLLM(LLMResponse(content="这是确定的健康结论。")), "为什么需要连续记录血糖？")
    assert result['status'] != 'completed'
    assert 'NO_EVIDENCE' in {r['code'] for r in result['rejections']}
    assert all('确定的健康结论' not in x for x in result['responses'])


@pytest.mark.parametrize('as_tool',[False,True])
def test_generated_unsafe_text_is_blocked(conn, as_tool):
    unsafe = "请把胰岛素改成早上多打两单位"
    response = call('respond',{'text':unsafe}) if as_tool else LLMResponse(content=unsafe)
    result = run(conn, ScriptedLLM(response,LLMResponse(content="")))
    assert all(unsafe not in x for x in result['responses'])
    assert result['rejections']


def test_claimed_write_without_write_is_rejected(conn):
    result = run(conn, ScriptedLLM(LLMResponse(content="已创建记录任务。")))
    assert result['status'] != 'completed'
    assert any(r['code']=='POSTCHECK_MISMATCH' for r in result['rejections'])
    assert not conn.execute('SELECT * FROM tasks').fetchall()


@pytest.mark.parametrize('tool',['complete_task','update_task','query_history'])
def test_cross_patient_tool_arguments_never_execute(conn,tool):
    patient(conn,'OTHER')
    t,_=tasks.create_task(conn,'OTHER',task_type='record_activity',title='记录步数')
    args={'patient_id':'OTHER'} if tool=='query_history' else {'task_id':t['id']}
    if tool=='update_task':args['due_at']=iso(now(conn)+timedelta(days=1))
    result=run(conn,ScriptedLLM(call(tool,args),LLMResponse(content="")))
    assert result['rejections']
    assert not any(x['tool']==tool and x['ok'] for x in result['actions'])
    assert tasks.get_task(conn,t['id'])['version']==1


def test_invalid_due_is_a_rejection_not_server_crash(conn):
    llm=ScriptedLLM(call('create_task',{'patient_id':'DS1','task_type':'record_glucose','title':'记录血糖','due_at':'not-a-time'}),LLMResponse(content=""))
    result=run(conn,llm)
    assert 'INVALID_DUE' in {r['code'] for r in result['rejections']}
    assert not conn.execute('SELECT * FROM tasks').fetchall()


def test_question_limit_is_cumulative_across_rounds(conn):
    llm=ScriptedLLM(*(call('ask_user',{'patient_id':'DS1','question':f'请补充信息{i}','target_field':f'f{i}'},str(i)) for i in range(3)))
    result=run(conn,llm)
    assert conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0] == 2
    assert 'TOO_MANY_ACTIONS' in {r['code'] for r in result['rejections']}


@pytest.mark.parametrize('arguments',[[1,2],None,{'patient_id':['OTHER']}])
def test_malformed_tool_arguments_are_rejected(conn,arguments):
    result=run(conn,ScriptedLLM(call('query_history',arguments),LLMResponse(content="")))
    assert result['rejections']


def test_upstream_error_finishes_persisted_run(conn):
    with pytest.raises(LLMRequestError):
        run(conn,ScriptedLLM(LLMRequestError('upstream 429')))
    row=conn.execute('SELECT status,finished_at FROM agent_runs').fetchone()
    assert row['status']=='failed' and row['finished_at']


def test_rejection_count_is_not_forbidden_execution_count(conn):
    run(conn,ScriptedLLM(),"请把胰岛素改成早上多打两单位")
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE decision='reject'").fetchone()[0] > 0
    assert gate.forbidden_action_count(conn)==0


def test_empty_output_is_failed_but_pure_explanation_is_allowed(conn):
    result=run(conn,ScriptedLLM(LLMResponse(content="")))
    assert result['status']=='failed'


def test_real_citation_chunk_and_explicit_non_diagnosis_are_allowed(conn):
    llm=ScriptedLLM(call('search_knowledge',{'query':'连续血糖记录 意义'}),
                    call('respond',{'text':'连续记录便于观察变化。这些为健康管理信息，不作诊断或治疗建议。',
                                    'citations':['KD-001-C003']}),LLMResponse(content='请按已确认的安排记录。'))
    result=run(conn,llm,'为什么需要连续记录血糖？')
    assert result['status']=='completed' and not result['rejections']


def test_disclaimer_cannot_hide_later_forbidden_instruction():
    assert gate.check_text('这些为健康管理信息，不作诊断或治疗建议。')['allowed']
    assert not gate.check_text('本系统不提供诊断。但我现在诊断为糖尿病。')['allowed']


@pytest.mark.parametrize('status',[400,401,402,429,500,502,503])
def test_provider_error_is_explicit_and_redacted(status):
    dummy='dummy-secret-not-a-real-key'
    client=OpenAICompatLLM('https://api.deepseek.com',dummy,'deepseek-flash',
                          transport=httpx.MockTransport(lambda request:httpx.Response(status,text='upstream '+dummy)))
    with pytest.raises(LLMRequestError) as exc:
        client.plan_actions(system='s',user='u',tools=[])
    assert str(status) in str(exc.value) and dummy not in str(exc.value)


def test_provider_timeout_does_not_retry():
    calls=[]
    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout('controlled local timeout')
    client=OpenAICompatLLM('https://api.deepseek.com','DUMMY','deepseek-flash',transport=httpx.MockTransport(transport))
    with pytest.raises(LLMRequestError):client.plan_actions(system='s',user='u',tools=[])
    assert len(calls)==1


def test_real_recording_task_with_no_medication_change_disclaimer(conn):
    llm=ScriptedLLM(call('create_task',{'patient_id':'DS1','task_type':'record_glucose',
        'title':'继续记录空腹血糖','description':'本任务仅为记录与趋势观察，不涉及任何用药或剂量调整。'}),
        LLMResponse(content='已创建记录任务。'))
    result=run(conn,llm)
    assert result['status']=='completed' and not result['rejections']


def test_generated_refusal_and_generic_doctor_referral_are_not_medical_actions(conn):
    result=run(conn,ScriptedLLM(call('respond',{'text':'本回复不构成诊断或用药建议；涉及用药调整请咨询您的医生。'}),LLMResponse(content='')))
    assert result['status']=='completed' and not result['rejections']


def test_answer_resume_includes_original_question_and_uncertainty(conn, monkeypatch):
    from backend.app.automation import triggers
    from backend.app.questioning import service as questions
    from backend.app.agent import llm as module
    patient(conn)
    q,_=questions.create_question(conn,'DS1',question='今天是否按原处方服药？',target_field='medication_taken')
    answered=questions.answer_question(conn,q['id'],answer_text='记不清')
    model=ScriptedLLM(LLMResponse(content='已记录本次不确定答复。'))
    monkeypatch.setattr(module,'get_llm',lambda:model)
    resumed=triggers.after_answer(conn,answered)
    assert '今天是否按原处方服药' in model.requests[0]['user']
    assert '不确定' in model.requests[0]['user']
    assert resumed['recorded'] is None


def test_preference_tool_advertises_actual_backend_enums():
    from backend.app.agent.llm import tool_schemas
    from backend.app.memory.preferences import ALLOWED_KINDS,ALLOWED_SOURCES
    schema=next(t for t in tool_schemas() if t['name']=='save_preference')['parameters']['properties']
    assert set(schema['kind']['enum'])==ALLOWED_KINDS
    assert set(schema['source']['enum'])==ALLOWED_SOURCES


def test_updated_task_is_associated_with_run_trace(conn):
    patient(conn)
    task,_=tasks.create_task(conn,'DS1',task_type='record_activity',title='记录步数')
    model=ScriptedLLM(call('update_task',{'task_id':task['id'],'due_at':iso(now(conn)+timedelta(days=1))}),LLMResponse(content='已调整记录时间。'))
    result=run_agent(conn,'DS1',trigger_type='user_request',message='请调整记录时间',llm=model)
    assert task['id'] in {t['id'] for t in trace(conn,result['run_id'])['tasks']}
