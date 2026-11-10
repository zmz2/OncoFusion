import time
from pathlib import Path

from fastapi.testclient import TestClient

from oncofusion.api import create_app
from oncofusion.mock_routes import MockRouteProvider
from oncofusion.profiles import profile_catalog


def test_vote_profile_is_exposed_and_executes_through_api(tmp_path):
    with TestClient(create_app(tmp_path / "vote.db", provider=MockRouteProvider())) as client:
        configs = client.get("/v1/configs/demo").json()
        vote_config = configs["configs"]["vote_v1"]
        assert vote_config["execution_model"] == "vote"
        assert configs["config"]["execution_model"] == "engine"

        submitted = client.post("/v1/runs", json={
            "example_id": "synthetic-support",
            "config": vote_config,
            "allow_remote_processing": True,
        })
        assert submitted.status_code == 202
        run_id = submitted.json()["run_id"]
        for _ in range(100):
            run = client.get("/v1/runs/" + run_id).json()
            if run["status"] != "running" and run["status"] != "queued":
                break
            time.sleep(.02)
        assert run["status"] == "succeeded"
        result = run["result"]
        assert result["vote_result"]["rule"] == "v0"
        assert result["vote_result"]["valid_votes"] == 4
        assert len(result["ballots"]) == 4


def test_vote_profile_points_to_the_frozen_start_plan():
    vote = profile_catalog()["vote_v1"]
    assert Path(vote["start_plan"]).is_file()
    assert vote["first_release"]["parallel"] is True
    assert vote["first_release"]["global_api_concurrency"] == 20


def test_web_exposes_vote_switch_and_panel(client):
    page = client.get("/app").text
    assert 'id="run-profile"' in page
    assert 'id="vote-panel"' in page
    assert 'vote_v1' in page
