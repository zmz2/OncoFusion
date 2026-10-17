import copy
import socket

import pytest
from fastapi.testclient import TestClient
from oncofusion.api import create_app
from oncofusion.examples import examples
from oncofusion.providers import MockProvider


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ONCOFUSION_PROVIDER", "mock")
    monkeypatch.delenv("ONCOFUSION_API_TOKEN", raising=False)
    monkeypatch.delenv("ONCOFUSION_CORS_ORIGINS", raising=False)
    def deny(*args, **kwargs):
        raise AssertionError("network access is forbidden in offline tests")
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def case():
    return examples()["synthetic-support"]


class RecordingProvider(MockProvider):
    def __init__(self):
        super().__init__()
        self.payloads, self.systems = [], []

    def complete(self, system, payload, max_tokens, temperature, seed):
        self.payloads.append(copy.deepcopy(payload))
        self.systems.append(system)
        return super().complete(system, payload, max_tokens, temperature, seed)


@pytest.fixture
def recorder():
    return RecordingProvider()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite", provider=MockProvider())) as instance:
        yield instance
