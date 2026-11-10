import json

from scripts.report_multi_route import _protocol_record, dataset_labels, percentile, read_rows


def test_report_percentiles_use_median_and_nearest_rank():
    assert percentile([1, 2, 3, 4], .50) == 2.5
    assert percentile([1, 2, 3, 4], .95) == 4


def test_report_derives_native_verification_labels_from_scheme(tmp_path):
    (tmp_path / "inputs.jsonl").write_text(json.dumps({
        "task": "verification",
        "verification_scheme": "revisions",
    }) + "\n")
    assert dataset_labels(tmp_path) == ["SUPPORTS", "REVISIONS", "NEI"]


def test_protocol_audit_uses_only_final_engine_verifier_entries():
    raw = {
        "reports": [{
            "role": "literature",
            "output": {"findings": [{
                "claim_id": "literature-01",
                "author_role": "literature",
                "scope": "source",
            }]},
        }],
        "decision": {
            "answer": "NEI",
            "adopted_claim_ids": [],
            "rejected_claim_ids": ["literature-01"],
        },
        "trace": [{
            "kind": "verification_ledger",
            "details": {"entries": [
                {
                    "target_claim_id": "literature-01",
                    "reviewer": "genomics",
                    "verdict": "corrected",
                    "final": False,
                },
                {
                    "target_claim_id": "literature-01",
                    "reviewer": "verifier",
                    "verdict": "confirmed",
                    "final": True,
                },
            ]},
        }],
    }
    audit = _protocol_record(raw)
    assert audit["assigned_claims"] == 1
    assert audit["verdicts"] == 1
    assert audit["duplicate_verdict_targets"] == 0
    assert audit["rejected_confirmed"] == 1


def test_report_counts_route_starts_from_result_and_failure_files(tmp_path):
    arm = tmp_path / "a1_route" / "0"
    arm.mkdir(parents=True)
    rows = [
        {
            "case_id": "ok",
            "status": "completed",
            "usage": {"calls": 0},
            "duration_seconds": 1,
        },
        {
            "case_id": "bad",
            "status": "failed",
            "usage_incomplete": True,
            "observed_usage": {"calls": 0},
        },
    ]
    (arm / "summary.json").write_text(json.dumps({"rows": rows}))
    (arm / "ok.json").write_text(json.dumps({"trace": [
        {"kind": "route_node_started", "role": "genomics"},
        {"kind": "model_usage", "role": "genomics"},
    ]}))
    (arm / "bad.failed.json").write_text(json.dumps({"trace": [
        {"kind": "route_node_started", "role": "literature"},
        {"kind": "route_node_started", "role": "verifier"},
    ]}))
    plan = {
        "seeds": [0],
        "case_ids": ["bad", "ok"],
        "treatments": [{"name": "a1_route"}],
    }

    loaded, diagnostics = read_rows(tmp_path, plan)

    assert sum(row["trace_calls"] for row in loaded) == 3
    assert diagnostics["a1_route"]["trace_calls"] == 3
    assert diagnostics["a1_route"]["calls_without_usage_event"] == 2
