"""Transport contracts used by future browser clients; model outputs stay simulated."""
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from fastapi.testclient import TestClient
from oncofusion.api import create_app
from oncofusion.providers import MockProvider
from oncofusion.schemas import RunConfig
from oncofusion.store import Store
from test_api_store_cli import wait_for

PAYLOAD = {'example_id': 'synthetic-support'}
HEADERS = {'Idempotency-Key': 'browser-request-1'}


def test_idempotent_replay_keeps_run_case_and_model_call_count(client):
    original = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
    rid = original.json()['run_id']
    result = wait_for(client, rid)
    replay = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
    assert replay.status_code == 202
    assert original.headers['Idempotency-Replayed'] == 'false'
    assert replay.headers['Idempotency-Replayed'] == 'true'
    assert replay.json()['run_id'] == rid
    assert replay.json()['status'] == 'succeeded'
    assert len(client.get('/v1/cases').json()) == len(client.get('/v1/runs').json()) == 1
    assert client.get('/v1/runs/' + rid).json()['result'] == result['result']


def test_idempotency_changed_request_is_a_conflict(client):
    client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
    changed = {**PAYLOAD, 'config': {'max_calls': 1}}
    assert client.post('/v1/runs', json=changed, headers=HEADERS).status_code == 409


def test_idempotency_parallel_requests_create_one_job(client):
    def submit(_):
        return client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(submit, range(24)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()['run_id'] for r in responses}) == 1
    assert sum(r.headers['Idempotency-Replayed'] == 'false' for r in responses) == 1


def test_replay_does_not_need_an_available_queue_slot(tmp_path):
    release, entered = threading.Event(), threading.Event()
    class Blocking(MockProvider):
        def complete(self, *args):
            entered.set()
            assert release.wait(5)
            return super().complete(*args)
    with TestClient(create_app(tmp_path/'queue.db', Blocking(), max_workers=1, max_pending=1)) as client:
        try:
            rid = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS).json()['run_id']
            assert entered.wait(2)
            assert client.post('/v1/runs', json=PAYLOAD).status_code == 429
            replay = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
            assert replay.status_code == 202 and replay.json()['run_id'] == rid
        finally:
            release.set()


def test_idempotency_survives_restart_and_completed_case_deletion(tmp_path):
    path = tmp_path / 'restart.db'
    with TestClient(create_app(path, MockProvider())) as client:
        first = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS).json()
        wait_for(client, first['run_id'])
    with TestClient(create_app(path, MockProvider())) as client:
        replay = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
        assert replay.json()['run_id'] == first['run_id']
        assert client.delete('/v1/cases/' + first['case_id']).status_code == 204
        fresh = client.post('/v1/runs', json=PAYLOAD, headers=HEADERS)
        assert fresh.json()['run_id'] != first['run_id']


@pytest.mark.parametrize('key', ['', 'a b', 'a/b', 'x'*129])
def test_idempotency_header_boundary(client, key):
    assert client.post('/v1/runs', json=PAYLOAD, headers={'Idempotency-Key':key}).status_code == 422


def test_without_idempotency_key_runs_are_independent(client):
    a = client.post('/v1/runs', json=PAYLOAD).json()
    b = client.post('/v1/runs', json=PAYLOAD).json()
    assert a['run_id'] != b['run_id']


@pytest.mark.parametrize('cursor', [0, 5, 10, 10000])
def test_sse_last_event_id_replays_only_new_events(client, cursor):
    rid = client.post('/v1/runs', json=PAYLOAD).json()['run_id']
    wait_for(client, rid)
    response = client.get(f'/v1/runs/{rid}/stream', headers={'Last-Event-ID':str(cursor)})
    ids = [int(line.removeprefix('id: ')) for line in response.text.splitlines() if line.startswith('id: ')]
    expected = client.get(f'/v1/runs/{rid}/events', params={'after':cursor}).json()
    assert ids == [e['sequence'] for e in expected]
    assert all(i > cursor for i in ids)
    assert response.headers['X-Accel-Buffering'] == 'no'
    assert 'event: done' in response.text


def test_sse_uses_later_of_header_and_explicit_cursor(client):
    rid = client.post('/v1/runs', json=PAYLOAD).json()['run_id']
    wait_for(client, rid)
    response = client.get(f'/v1/runs/{rid}/stream?after=5', headers={'Last-Event-ID':'1'})
    assert 'id: 6\n' in response.text and 'id: 2\n' not in response.text


@pytest.mark.parametrize('cursor', ['-2', 'abc', str(2**63)])
def test_sse_invalid_header(client, cursor):
    rid = client.post('/v1/runs', json=PAYLOAD).json()['run_id']
    assert client.get(f'/v1/runs/{rid}/stream', headers={'Last-Event-ID':cursor}).status_code == 422


def test_cors_allows_browser_retry_and_resume_headers(tmp_path, monkeypatch):
    monkeypatch.setenv('ONCOFUSION_CORS_ORIGINS','http://localhost:5173')
    with TestClient(create_app(tmp_path/'cors.db', MockProvider())) as client:
        response = client.options('/v1/runs', headers={
            'Origin':'http://localhost:5173', 'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'Authorization,Content-Type,Idempotency-Key,Last-Event-ID'})
        assert response.status_code == 200
        assert 'idempotency-key' in response.headers['access-control-allow-headers'].lower()


def test_store_request_key_is_removed_with_run(tmp_path, case):
    store = Store(tmp_path/'store.db')
    cid = store.save_cases([case])[0]
    rid = store.create_run(cid, RunConfig())
    assert store.request_run('key', 'fingerprint') is None
    store.remember_request('key', 'fingerprint', rid)
    assert store.request_run('key', 'fingerprint') == rid
    with pytest.raises(ValueError, match='different request'):
        store.request_run('key', 'other')
    store.cancel(rid)
    store.delete_case(cid)
    assert store.request_run('key', 'fingerprint') is None
