import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from oncofusion.api import create_app
from oncofusion.config import presets
from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate
from oncofusion.examples import examples
from oncofusion.experiments import (PERTURBATIONS, StudyPlan, Treatment, perturb, run_study,
                                   select_cases, standard_plan)
from oncofusion.preparation import (acquire_mtb, build_path_map, claim_entities, dataset_audit,
                                    download, prepare_civic, prepare_mtb)
from oncofusion.providers import (MockProvider, ModelReply, OpenAICompatibleProvider, ProviderError,
                                  env_bool, provider_identity)
from oncofusion.schemas import AnalysisOutput, RunConfig


def data():
    cases = list(examples().values())[:3]
    labels = [GoldRecord(case_id=c.id, label=l, group_id=c.patient_id, split="dev")
              for c, l in zip(cases, ["SUPPORTS", "REFUTES", "NEI"])]
    return cases, labels


@pytest.mark.parametrize("name", PERTURBATIONS)
@pytest.mark.parametrize("example", list(examples()))
def test_perturbation_isolated_and_runs(name, example):
    case = examples()[example]
    before = case.model_dump_json()
    changed = perturb(case, name, 12)
    result = Engine(MockProvider()).run(changed)
    assert result.status == "completed"
    assert "FUTURE_CANARY" not in result.model_dump_json()
    assert case.model_dump_json() == before
    assert perturb(case, name, 12) == changed


def test_fixed_five_real_roles(case):
    result = Engine(MockProvider()).run(case, presets()["fixed_five"])
    assert [r.role for r in result.reports] == ["genomics", "pathology", "drug", "literature"]
    assert all(r.executor == r.role for r in result.reports)
    assert result.usage.calls == 5


@pytest.mark.parametrize("seeds", [[-1], [1, 1], []])
def test_plan_invalid_seeds(seeds):
    with pytest.raises(ValueError):
        StudyPlan(name="test", task="verification", seeds=seeds, treatments=[Treatment(name="full")])


@pytest.mark.parametrize("kw", [{"preset": "invalid"}, {"perturbation": "invalid"},
                                 {"overrides": {"max_calls": 0}}, {"overrides": {"unknown": 1}}])
def test_treatment_validation(kw):
    with pytest.raises(ValueError):
        Treatment(name="test", **kw)


def test_treatment_nested_override():
    config = Treatment(name="off", overrides={"ablations": {"disease_matching": False}}).config(3)
    assert config.seed == 3 and not config.ablations.disease_matching
    assert config.ablations.drug_polarity
    assert presets()["full"].ablations.disease_matching


def test_selection_groups_and_empty():
    cases, gold = data()
    plan = standard_plan("verification", group_limit=1, smoke=True)
    selected, labels = select_cases(cases, gold, plan)
    assert len(selected) == len(labels) == 1
    with pytest.raises(ValueError, match="empty"):
        select_cases(cases, gold, standard_plan("mcq", smoke=True))
    with pytest.raises(ValueError):
        select_cases(cases, gold[:-1], plan)


def test_study_resume_and_identity(tmp_path, recorder):
    cases, gold = data()
    plan = standard_plan("verification", smoke=True)
    first = run_study(plan, cases, gold, Engine(recorder), tmp_path)
    calls = len(recorder.payloads)
    second = run_study(plan, cases, gold, Engine(recorder), tmp_path, resume=True)
    assert len(first["table"]) == 5 and first == second
    assert len(recorder.payloads) == calls
    with pytest.raises(ValueError, match="exists"):
        run_study(plan, cases, gold, Engine(recorder), tmp_path)
    cases[0].question += " changed"
    with pytest.raises(ValueError, match="changed"):
        run_study(plan, cases, gold, Engine(recorder), tmp_path, resume=True)


def test_resume_at_individual_case(tmp_path, recorder):
    cases, gold = data()
    report = evaluate(cases, gold, Engine(recorder), RunConfig(), tmp_path)
    count = len(recorder.payloads)
    assert evaluate(cases, gold, Engine(recorder), RunConfig(), tmp_path, resume=True)["metrics"] == report["metrics"]
    assert len(recorder.payloads) == count
    with pytest.raises(ValueError, match="identity"):
        evaluate(cases, gold, Engine(recorder), RunConfig(seed=6), tmp_path, resume=True)


def test_resume_failures_explicit(tmp_path):
    class Fails(MockProvider):
        calls = 0
        def complete(self, *args):
            self.calls += 1
            raise ProviderError("fixture failure")
    cases, gold = data()
    provider = Fails()
    evaluate(cases, gold, Engine(provider), RunConfig(), tmp_path)
    assert provider.calls == 3
    evaluate(cases, gold, Engine(provider), RunConfig(), tmp_path, resume=True)
    assert provider.calls == 3
    evaluate(cases, gold, Engine(provider), RunConfig(), tmp_path, resume=True, retry_failed=True)
    assert provider.calls == 6


def test_schema_repair_charged_and_bounded(case):
    class OnceInvalid(MockProvider):
        calls = 0
        def complete(self, *args):
            self.calls += 1
            if self.calls == 1:
                return ModelReply("not-json", 5, 2)
            return super().complete(*args)
    provider = OnceInvalid()
    result = Engine(provider).run(case, RunConfig(schema_retries=1))
    assert result.status == "completed" and result.usage.calls == 8
    assert sum(e.kind == "schema_repair_requested" for e in result.trace) == 1
    result = Engine(OnceInvalid()).run(case, RunConfig(schema_retries=1, max_calls=1))
    assert result.status == "budget_exhausted"


def test_event_stage_timeline_without_dates(recorder):
    case = examples()["synthetic-timeline"]
    for d in case.documents:
        d.event_day = None
    result = Engine(recorder).run(case)
    timeline = recorder.payloads[-1]["signals"]["timeline"]
    assert [x["stage"] for x in timeline] == [0, 1]
    assert result.status == "completed"


@pytest.mark.parametrize("temperature,seed", [(False, False), (True, False), (False, True)])
def test_provider_optional_parameters(temperature, seed):
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
    provider = OpenAICompatibleProvider("https://test.example/v1", "m", "private-key", send_temperature=temperature,
                                        send_seed=seed, transport=httpx.MockTransport(handle))
    provider.complete("s", {}, 100, .5, 123)
    assert ("temperature" in bodies[0]) == temperature
    assert ("seed" in bodies[0]) == seed
    assert "private-key" not in json.dumps(provider_identity(provider))


@pytest.mark.parametrize("value", ["1", "yes", "invalid", ""])
def test_strict_env_boolean(monkeypatch, value):
    monkeypatch.setenv("FLAG", value)
    with pytest.raises(ValueError):
        env_bool("FLAG", True)


def test_download_atomic_and_pinned(tmp_path):
    raw = b"known dataset bytes"
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as client:
        path = tmp_path / "file.gz"
        report = download(client, "https://example.test/data", path, git_blob=blob)
        assert path.read_bytes() == raw and report["git_blob_sha1"] == blob
        with pytest.raises(ValueError, match="checksum"):
            download(client, "https://example.test/data", path, git_blob="0" * 40)
        assert path.read_bytes() == raw
        with pytest.raises(ValueError, match="size"):
            download(client, "https://example.test/data", path, max_bytes=3)
        assert not path.with_suffix(".gz.part").exists()


def test_download_http_failure(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            download(client, "https://example.test/data", tmp_path / "x")
    assert not list(tmp_path.iterdir())


def test_path_mapping_deterministic_and_ambiguous():
    assert build_path_map(["/original/data/P1/specimen.txt"], ["data/P1/specimen.txt", "data/P2/specimen.txt"]) == {
        "/original/data/P1/specimen.txt": "data/P1/specimen.txt"}
    assert build_path_map(["C:\\data\\P1\\specimen.txt"], ["data/P1/specimen.txt"])
    for candidates in [["specimen.txt"], ["a/P1/specimen.txt", "b/P1/specimen.txt"], []]:
        with pytest.raises(ValueError):
            build_path_map(["/original/P1/specimen.txt"], candidates)


def test_claim_entities_whitelist():
    row = {"claim": [{"type": "table", "content": [["molecularProfile", "BRAF V600E"], ["diseases", "Melanoma"], ["therapies", "Drug-A"]]}],
           "gold_label_name": "REFUTES", "reviews": "secret"}
    entities = claim_entities(row)
    assert entities.gene == "BRAF" and entities.variant == "V600E" and entities.disease == "Melanoma"
    assert claim_entities({}).gene == ""
    assert "secret" not in entities.model_dump_json()


def test_audit_and_civic_preparation(tmp_path):
    rows = [{"id": "case1", "document.pmid": "123", "claim.flat": "GENE1 sensitive to Drug-A", "evidence.flat": "Source response data.",
             "gold_label_name": "SUPPORTS", "partition": "dev"}]
    path = tmp_path / "raw.jsonl"
    path.write_text(json.dumps(rows[0]) + "\n")
    report = prepare_civic(path, tmp_path / "out")
    assert report["cases"] == 1 and report["groups"] == 1
    assert "gold_label_name" not in (tmp_path / "out/inputs.jsonl").read_text()
    assert report["warnings"]
    cases, gold = data()
    with pytest.raises(ValueError):
        dataset_audit(cases, gold[:-1])


def test_mtb_preparation_no_future_leak(tmp_path):
    records = {}
    for pid in ["P1", "P2"]:
        folder = tmp_path / "raw" / pid
        folder.mkdir(parents=True)
        (folder / "specimen.txt").write_text("Fictional specimen: tumor.")
        records[pid] = [{"context": "Initial information."}, {"file_paths": [f"/upstream/{pid}/specimen.txt"]},
                        {"question": "Which state?\nA) stable\nB) progressive", "answer": "A) stable"},
                        {"context": "FUTURE_CANARY"}, {"question": "Later?\nA) yes\nB) no", "answer": "B) no"}]
    source = tmp_path / "raw/questions_msk_bench.json"
    source.write_text(json.dumps(records))
    report = prepare_mtb(source, tmp_path / "raw", tmp_path / "ready")
    assert report["groups"] == 2 and report["cases"] == 4
    inputs = read_jsonl(tmp_path / "ready/inputs.jsonl")
    assert "FUTURE_CANARY" not in json.dumps(inputs[0])
    assert "FUTURE_CANARY" in json.dumps(inputs[1])


def test_acquire_hf_manifest_pinned(tmp_path):
    revision = "a" * 40
    questions = {"P1": [{"file_paths": ["/data/P1/specimen.txt"]}]}
    visited = []
    def handler(request):
        visited.append(str(request.url))
        if "/api/" in request.url.path:
            return httpx.Response(200, json={"sha": revision, "siblings": [{"rfilename": "questions_msk_bench.json"},
                                                                                        {"rfilename": "data/P1/specimen.txt"}]})
        return httpx.Response(200, json=questions) if request.url.path.endswith(".json") else httpx.Response(200, text="specimen")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        inventory = acquire_mtb(client, tmp_path)
    assert inventory["revision"] == revision and len(inventory["downloads"]) == 2
    assert all(revision in url for url in visited[1:])


@pytest.mark.parametrize("metadata", [{"sha": "bad", "siblings": []}, {"sha": "a" * 40, "siblings": []}])
def test_hf_invalid_metadata(tmp_path, metadata):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=metadata))) as client:
        with pytest.raises(ValueError):
            acquire_mtb(client, tmp_path)


def test_validation_response_does_not_echo_payload(client):
    response = client.post("/v1/cases", json={"patient_secret": "PRIVATE_CANARY"})
    assert response.status_code == 422 and "PRIVATE_CANARY" not in response.text


def test_cases_listing(client, case):
    cid = client.post("/v1/cases", json=case.model_dump()).json()["case_id"]
    assert client.get("/v1/cases").json()[0]["case_id"] == cid
    assert client.get("/v1/cases?offset=1").json() == []


@pytest.mark.parametrize("workers,pending", [(0, 2), (33, 40), (3, 2), (2, 1025)])
def test_worker_configuration_boundary(tmp_path, workers, pending):
    with pytest.raises(ValueError):
        create_app(tmp_path / "x.sqlite", max_workers=workers, max_pending=pending)


def test_review_html_parser_and_empty():
    from oncofusion.review_samples import import_reviews
    row = {"meta": {"example_id": "synthetic-review"}, "label": ["Supports"],
           "text": '<div class="claim"><h2>Claim</h2><p>GENE1 sensitive to Drug-A.</p></div><div class="evidence"><h2>Evidence</h2><div><p>GENE1 showed response.</p></div></div><div class="ad_info">PRIVATE_ANNOTATION</div>'}
    cases, gold = import_reviews([row], 1)
    assert cases[0].question == "GENE1 sensitive to Drug-A."
    assert cases[0].documents[0].text == "GENE1 showed response."
    assert gold[0].label == "SUPPORTS"
    assert "PRIVATE_ANNOTATION" not in cases[0].model_dump_json()
    row["label"] = []
    with pytest.raises(ValueError):
        import_reviews([row])
    row["label"] = ["Refutes"]
    row["text"] = '<div class="claim">claim</div>'
    with pytest.raises(ValueError):
        import_reviews([row])


def test_standard_plan_complete_frozen():
    plan = standard_plan("verification")
    assert len(plan.treatments) == 41
    assert len({t.name for t in plan.treatments}) == 41
    for t in plan.treatments:
        t.config(0)
    assert plan.seeds == [0, 1, 2]


def test_report_writer(tmp_path):
    from scripts.build_report import build
    cases, gold = data()
    run_study(standard_plan("verification", smoke=True), cases, gold, Engine(MockProvider()), tmp_path / "study")
    report = build(tmp_path / "study/study.json", tmp_path / "report")
    assert "模拟运行" in (tmp_path / "report/REPORT.md").read_text()
    assert len((tmp_path / "report/results.csv").read_text().splitlines()) == 6


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1])
def test_provider_timeout_finite(timeout):
    with pytest.raises(ValueError):
        OpenAICompatibleProvider("https://example.test", "m", "key", timeout=timeout)


def test_blank_question_rejected(client, case):
    body = case.model_dump()
    body["question"] = "   "
    assert client.post("/v1/cases", json=body).status_code == 422


def test_recursive_upload_rejected(client):
    body = b"[" * 2000 + b"0" + b"]" * 2000
    assert client.post("/v1/cases/upload", files={"file": ("deep.json", body)}).status_code == 422


def test_acquire_mtb_honours_endpoint_override(tmp_path, monkeypatch):
    revision = "b" * 40
    questions = {"P1": [{"file_paths": ["/data/P1/specimen.txt"]}]}
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if "/api/" in request.url.path:
            return httpx.Response(200, json={"sha": revision, "siblings": [
                {"rfilename": "questions_msk_bench.json"},
                {"rfilename": "data/P1/specimen.txt"}]})
        return (httpx.Response(200, json=questions) if request.url.path.endswith(".json")
                else httpx.Response(200, text="specimen"))

    monkeypatch.delenv("ONCOFUSION_HF_ENDPOINT", raising=False)
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acquire_mtb(client, tmp_path / "canonical")
    assert visited and all(url.startswith("https://huggingface.co/") for url in visited)

    visited.clear()
    monkeypatch.setenv("ONCOFUSION_HF_ENDPOINT", "https://mirror.example")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        inventory = acquire_mtb(client, tmp_path / "mirror")
    assert inventory["endpoint"] == "https://mirror.example"
    assert all(url.startswith("https://mirror.example/") for url in visited)

    visited.clear()
    monkeypatch.delenv("ONCOFUSION_HF_ENDPOINT")
    monkeypatch.setenv("HF_ENDPOINT", "https://mirror.example/")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acquire_mtb(client, tmp_path / "generic")
    assert all(url.startswith("https://mirror.example/") for url in visited)
