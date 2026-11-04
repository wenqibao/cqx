"""验收工具的费用闸门测试，不调用模型。"""
import pytest
from scripts.deepseek_acceptance_server import AcceptanceBudget


def test_trigger_limit_survives_restart(workdir):
    path=workdir/'ledger.json'
    budget=AcceptanceBudget(path)
    for _ in range(6):budget.reserve_trigger('R02','P1','event_detected')
    restarted=AcceptanceBudget(path)
    with pytest.raises(RuntimeError,match='6次'):
        restarted.reserve_trigger('R03','P1','answer_received')


def test_failed_request_is_counted_and_consecutive_failures_stop(workdir):
    budget=AcceptanceBudget(workdir/'ledger.json')
    trigger=budget.reserve_trigger('R01','P1','user_request')
    for _ in range(2):
        request=budget.reserve_request(trigger)
        request['status']='failed'
        budget.save()
    with pytest.raises(RuntimeError,match='连续'):
        budget.reserve_request(trigger)
    assert len(budget.data['requests'])==2
