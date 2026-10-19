import gzip
import json
import pytest
from oncofusion.datasets import (GoldRecord, group_split, import_civicfact, import_mtbbench,
                                  parse_mcq, read_jsonl, safe_source, validate_splits, write_dataset)
from oncofusion.engine import Engine
from oncofusion.evaluation import (classification_metrics, evaluate, load_evaluation,
                                    paired_cluster_bootstrap, retrieval_metrics, risk_coverage)
from oncofusion.examples import examples
from oncofusion.experiments import run_study, standard_plan
from oncofusion.providers import MockProvider, ProviderError
from oncofusion.schemas import RunConfig


def civic_row(label="SUPPORTS"):
    return {"id": "example1", "claim.flat": "The claim", "evidence.flat": "Some evidence.",
            "document.pmid": "123", "document.title": "Study", "document.license": "CC-BY",
            "partition": "test", "gold_label_name": label,
            "civic.description": "GOLD_CANARY", "reviews": [{"explanation": "GOLD_CANARY"}],
            "generated": True}


@pytest.mark.parametrize("label", ["SUPPORTS", "REFUTES", "NEI"])
def test_civic_whitelist(label, recorder):
    cases, gold = import_civicfact([civic_row(label)])
    assert gold[0].label == label
    assert "GOLD_CANARY" not in cases[0].model_dump_json()
    assert "gold_label_name" not in cases[0].model_dump_json()
    Engine(recorder).run(cases[0])
    assert "GOLD_CANARY" not in json.dumps(recorder.payloads)
    assert cases[0].documents[0].license == "CC-BY"


def test_explicit_label_mapping():
    with pytest.raises(ValueError, match="unsupported"):
        import_civicfact([civic_row("REVISIONS")])
    with pytest.raises(ValueError, match="remapping"):
        import_civicfact([civic_row("REVISIONS")], "REVISIONS")
    cases, gold = import_civicfact([civic_row("REVISIONS")], verification_scheme="revisions")
    assert gold[0].label == "REVISIONS"
    assert cases[0].verification_scheme == "revisions"


def test_civic_empty_evidence():
    row = civic_row("NEI")
    row["evidence.flat"] = ""
    assert import_civicfact([row])[0][0].documents == []


def test_mtb_event_replay_and_future_isolation(tmp_path):
    (tmp_path / "specimen.txt").write_text("Visible Tumor-A specimen", encoding="utf-8")
    records = {"p1": [
        {"context": "Initial case context."},
        {"file_paths": ["upstream/specimen.txt"]},
        {"question": "Outcome?\nA) yes\nB) no", "answer": "A) yes", "explanation": "GOLD_CANARY"},
        {"context": "LATER_CANARY true outcome observed."},
        {"question": "Next outcome?\nA) yes\nB) no", "answer": "B) no"},
    ]}
    cases, gold = import_mtbbench(records, tmp_path, {"upstream/specimen.txt": "specimen.txt"})
    assert len(cases) == 2 and [g.label for g in gold] == ["A", "B"]
    assert "GOLD_CANARY" not in cases[0].model_dump_json()
    assert "LATER_CANARY" not in cases[0].model_dump_json()
    assert "LATER_CANARY" in cases[1].model_dump_json()
    assert cases[0].documents[-1].kind == "pathology"
    assert cases[0].stage < cases[1].stage
    with pytest.raises(ValueError, match="unmapped"):
        import_mtbbench(records, tmp_path, {})


@pytest.mark.parametrize("question", ["No options", "Question\nA) one", "Q\nA) one\nA) two"])
def test_malformed_mcq(question):
    with pytest.raises(ValueError):
        parse_mcq(question)


def test_mcq_multiple_styles():
    q, options = parse_mcq("Question\nA. first\n  more text\nB: second\nC) third")
    assert q == "Question" and options["A"] == "first\n  more text" and options["C"] == "third"


def test_mtb_invalid_answer(tmp_path):
    with pytest.raises(ValueError, match="answer format"):
        import_mtbbench({"p": [{"question": "Q\nA) one\nB) two", "answer": "Z"}]}, tmp_path, {})


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "bad.png"])
def test_source_path_boundary(tmp_path, path):
    with pytest.raises(ValueError):
        safe_source(tmp_path, path)


def test_symlink_and_large_source(tmp_path):
    target = tmp_path.parent / "outside-source.txt"
    target.write_text("secret")
    (tmp_path / "link.txt").symlink_to(target)
    with pytest.raises(ValueError):
        safe_source(tmp_path, "link.txt")
    (tmp_path / "large.txt").write_text("x" * 100_001)
    with pytest.raises(ValueError, match="100 KB"):
        safe_source(tmp_path, "large.txt")


def test_jsonl_gzip_roundtrip(tmp_path, case):
    gold = [GoldRecord(case_id=case.id, label="SUPPORTS", group_id="p1")]
    manifest = write_dataset([case], gold, tmp_path / "dataset", "synthetic")
    assert manifest["count"] == 1 and len(manifest["inputs_sha256"]) == 64
    cases, labels = load_evaluation(tmp_path / "dataset/inputs.jsonl", tmp_path / "dataset/_gold/labels.jsonl")
    assert cases == [case] and labels == gold
    path = tmp_path / "rows.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write('\n{"x": 1}\n')
    assert read_jsonl(path) == [{"x": 1}]
    (tmp_path / "bad.jsonl").write_text('{"x":1}\ninvalid')
    with pytest.raises(ValueError, match="line 2"):
        read_jsonl(tmp_path / "bad.jsonl")
    with pytest.raises(ValueError):
        write_dataset([case, case], gold, tmp_path / "bad", "synthetic")


def test_group_splits():
    groups = ["p1", "p1", "p2", "p3", "p4", "p5"]
    splits = group_split(groups)
    assert splits == group_split(groups)
    assert set(splits.values()) == {"dev", "test"} and len(splits) == 5
    gold = [GoldRecord(case_id="a", label="A", group_id="p", split="dev"),
            GoldRecord(case_id="b", label="B", group_id="p", split="test")]
    with pytest.raises(ValueError, match="crosses"):
        validate_splits(gold)
    for g in gold:
        g.split = "dev"
    validate_splits(gold)
    for args in [(["p"], .2), (["p", "q"], 0), (["p", "q"], 1)]:
        with pytest.raises(ValueError):
            group_split(args[0], dev_fraction=args[1])


def test_classification_metrics_exact():
    m = classification_metrics(["S", "R", "N", "S"], ["S", "S", "N", "__FAILED__"], ["S", "R", "N"])
    assert m["accuracy"] == .5
    assert m["per_class"]["S"]["precision"] == .5
    assert m["per_class"]["S"]["recall"] == .5
    assert m["macro_f1"] == .5


@pytest.mark.parametrize("g,p,labels", [([], [], ["S"]), (["S"], [], ["S"]), (["X"], ["X"], ["S"]),
                                       (["S"], ["S"], ["S", "S"])])
def test_metric_boundary(g, p, labels):
    with pytest.raises(ValueError):
        classification_metrics(g, p, labels)


def test_retrieval_metrics_exact():
    m = retrieval_metrics({"a", "b"}, ["x", "a", "a", "b"], 3)
    assert m["recall_at_k"] == 1
    assert m["average_precision_at_k"] == pytest.approx((.5 + 2/3) / 2)
    with pytest.raises(ValueError):
        retrieval_metrics(set(), [], 3)


def test_paired_cluster_bootstrap():
    out = paired_cluster_bootstrap(["p1", "p1", "p2"], [1, 1, 1], [0, 0, 0], repeats=100)
    assert out["mean_delta"] == 1 and out["ci95"] == [1, 1]
    assert out == paired_cluster_bootstrap(["p1", "p1", "p2"], [1, 1, 1], [0, 0, 0], repeats=100)
    with pytest.raises(ValueError):
        paired_cluster_bootstrap([], [], [])


def test_risk_coverage():
    result = risk_coverage([False, True, True], [.1, .9, .8])
    assert result[0] == {"coverage": 1/3, "risk": 0}
    assert result[-1]["risk"] == 1/3
    with pytest.raises(ValueError):
        risk_coverage([True], [1.2])


def test_evaluation_persists_failures_and_mock_flag(tmp_path):
    cases = list(examples().values())[:3]
    gold = [GoldRecord(case_id=c.id, group_id=c.patient_id, label=l) for c, l in zip(cases, ["SUPPORTS", "REFUTES", "NEI"])]
    report = evaluate(cases, gold, Engine(MockProvider()), RunConfig(), tmp_path)
    assert report["simulated"] and report["count"] == 3
    assert report["metrics"]["accuracy"] == 1.0
    assert (tmp_path / "summary.json").is_file()
    class Broken(MockProvider):
        def complete(self, *args):
            raise ProviderError("upstream unavailable")
    failed = evaluate(cases, gold, Engine(Broken()), RunConfig())
    assert failed["failed_or_incomplete"] == 3 and failed["metrics"]["accuracy"] == 0
    incomplete = evaluate(cases, gold, Engine(MockProvider()), RunConfig(max_calls=1))
    assert incomplete["failed_or_incomplete"] == 3
    with pytest.raises(ValueError):
        evaluate(cases, gold[:1], Engine(MockProvider()), RunConfig())


def _verification_set():
    cases = [c for c in examples().values() if c.task == "verification"]
    labels = ["SUPPORTS", "REFUTES", "NEI"]
    gold = [GoldRecord(case_id=c.id, group_id=c.patient_id, label=labels[i % 3], split="dev")
            for i, c in enumerate(cases)]
    return cases, gold


def test_parallel_evaluation_matches_sequential(tmp_path):
    cases, gold = _verification_set()
    assert len(cases) >= 3
    serial = evaluate(cases, gold, Engine(MockProvider()), RunConfig(), tmp_path / "serial")
    parallel = evaluate(cases, gold, Engine(MockProvider()), RunConfig(), tmp_path / "parallel", workers=4)
    projection = [(r["case_id"], r["status"], r["prediction"], r["fingerprint"]) for r in parallel["rows"]]
    assert projection == [(r["case_id"], r["status"], r["prediction"], r["fingerprint"]) for r in serial["rows"]]
    assert parallel["metrics"] == serial["metrics"]
    assert parallel["count"] == serial["count"]
    assert parallel["failed_or_incomplete"] == serial["failed_or_incomplete"]
    assert (tmp_path / "parallel" / (cases[0].id + ".json")).is_file()
    assert (tmp_path / "serial" / (cases[0].id + ".json")).is_file()


def test_parallel_evaluation_records_failures_per_case(tmp_path):
    cases, gold = _verification_set()
    class Broken(MockProvider):
        def complete(self, *args):
            raise ProviderError("upstream unavailable")
    report = evaluate(cases, gold, Engine(Broken()), RunConfig(), tmp_path, workers=3)
    assert report["failed_or_incomplete"] == len(cases)
    assert all(r["status"] == "failed" for r in report["rows"])
    assert [r["case_id"] for r in report["rows"]] == [c.id for c in cases]


@pytest.mark.parametrize("workers", [0, -1, 65])
def test_parallel_worker_bounds(workers):
    cases, gold = _verification_set()
    with pytest.raises(ValueError):
        evaluate(cases, gold, Engine(MockProvider()), RunConfig(), workers=workers)


def test_parallel_studies_match_sequential(tmp_path):
    cases, gold = _verification_set()
    plan = standard_plan("verification", smoke=True)
    plan.group_limit = None
    serial = run_study(plan, cases, gold, Engine(MockProvider()), tmp_path / "serial")
    parallel = run_study(plan, cases, gold, Engine(MockProvider()), tmp_path / "parallel", workers=4)
    assert serial["identity"] == parallel["identity"]
    assert serial["table"] == parallel["table"]
    assert serial["case_count"] == parallel["case_count"]
