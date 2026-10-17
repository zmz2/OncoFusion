"""Costs retain partial failures and distinguish reported from estimated usage."""
import pytest
from oncofusion.datasets import GoldRecord
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate
from oncofusion.examples import examples
from oncofusion.providers import MockProvider, ProviderError
from oncofusion.schemas import RunConfig


class PricedProvider(MockProvider):
    def __init__(self, *, estimated=False, attempts=1, fail_at=None):
        super().__init__()
        self.simulated = False
        self.input_price = 1.0
        self.output_price = 2.0
        self.estimated = estimated
        self.attempts = attempts
        self.fail_at = fail_at
        self.n = 0

    def complete(self, *args):
        self.n += 1
        if self.n == self.fail_at:
            raise ProviderError('synthetic transport failure')
        reply = super().complete(*args)
        reply.input_tokens, reply.output_tokens = 100, 50
        reply.estimated, reply.attempts = self.estimated, self.attempts
        return reply


def report(provider, tmp_path=None, **kwargs):
    case = next(iter(examples().values()))
    gold = [GoldRecord(case_id=case.id, label='SUPPORTS', group_id=case.patient_id)]
    return evaluate([case], gold, Engine(provider), RunConfig(), tmp_path, **kwargs)


def test_failed_run_counts_prior_reported_usage_and_known_cost(tmp_path):
    result = report(PricedProvider(fail_at=3), tmp_path)
    cost = result['efficiency']
    assert result['failed_or_incomplete'] == 1
    assert cost['total_input_tokens'] == 200
    assert cost['total_output_tokens'] == 100
    assert cost['total_calls'] == 3
    assert cost['known_cost_usd'] == pytest.approx(.0004)
    assert cost['usage_incomplete_runs'] == 1
    assert not cost['cost_complete']
    resumed = report(PricedProvider(fail_at=3), tmp_path, resume=True)
    assert resumed['efficiency'] == cost


@pytest.mark.parametrize('estimated,attempts', [(True, 1), (False, 2), (True, 2)])
def test_incomplete_real_usage_not_reported_as_complete(estimated, attempts):
    result = report(PricedProvider(estimated=estimated, attempts=attempts))
    cost = result['efficiency']
    assert result['failed_or_incomplete'] == 0
    assert cost['usage_incomplete_runs'] == 1
    assert not cost['cost_complete']
    if estimated:
        assert cost['known_cost_usd'] == 0
        assert cost['estimated_cost_usd'] > 0
    else:
        assert cost['known_cost_usd'] > 0


def test_fully_reported_cost_is_complete():
    cost = report(PricedProvider())['efficiency']
    assert cost['cost_complete']
    assert cost['usage_incomplete_runs'] == 0
    assert cost['known_cost_usd'] == pytest.approx(cost['total_calls'] * .0002)


def test_mock_cost_is_explicitly_zero_and_simulated():
    result = report(MockProvider())
    assert result['simulated'] and result['efficiency']['cost_complete']
    assert result['efficiency']['known_cost_usd'] == 0
