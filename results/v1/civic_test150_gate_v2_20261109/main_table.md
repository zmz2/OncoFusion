| Arm / split | N | Complete | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all / revision_gate_multi | 150 | 98.7% | 0.653 | 0.654 | 0.540 | 0.560 | 0.860 | 830 | 3088140 | 334286 |
| debug / revision_gate_multi | 5 | 100.0% | 0.600 | 0.667 | 0.500 | 0.500 | 1.000 | 26 | 86823 | 9780 |
| unused / revision_gate_multi | 145 | 98.6% | 0.655 | 0.655 | 0.542 | 0.562 | 0.857 | 804 | 3001317 | 324506 |
| all / single_tools_shared_evidence | 150 | 97.3% | 0.713 | 0.718 | 0.460 | 0.840 | 0.840 | 161 | 416772 | 86933 |
| debug / single_tools_shared_evidence | 5 | 80.0% | 0.800 | 0.889 | 0.500 | 1.000 | 1.000 | 6 | 14821 | 7986 |
| unused / single_tools_shared_evidence | 145 | 97.9% | 0.710 | 0.712 | 0.458 | 0.833 | 0.837 | 155 | 401951 | 78947 |

```json
{
  "study_identity": "315bf22afdeafe5366f644596df0d16503395486da19b4a6a3da819605e7ecf1",
  "simulated": false,
  "execution_order": "case_interleaved",
  "debug_group_ids": [
    "article-20147967",
    "article-20979473",
    "article-31160355"
  ],
  "debug_case_ids": [
    "civic-00693f9a-e755-4b1a-a158-c6ea8d40247b",
    "civic-31021ed2-d0a0-4772-8495-6290df86983f",
    "civic-400d7ece-0b3d-4e59-b363-e15373f94f42",
    "civic-af46590a-d6fd-48bc-b077-3d4aa78afdbe",
    "civic-d2956c41-9709-44ff-923d-9991d7f00a54"
  ],
  "table": [
    {
      "scope": "all",
      "treatment": "revision_gate_multi",
      "count": 150,
      "completed": 148,
      "completion_rate": 0.9866666666666667,
      "failed_or_incomplete": 2,
      "accuracy": 0.6533333333333333,
      "macro_f1": 0.6542997355017816,
      "per_class_recall": {
        "SUPPORTS": 0.54,
        "REVISIONS": 0.56,
        "NEI": 0.86
      },
      "calls": 830,
      "input_tokens": 3088140,
      "output_tokens": 334286
    },
    {
      "scope": "debug",
      "treatment": "revision_gate_multi",
      "count": 5,
      "completed": 5,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.6,
      "macro_f1": 0.6666666666666666,
      "per_class_recall": {
        "SUPPORTS": 0.5,
        "REVISIONS": 0.5,
        "NEI": 1.0
      },
      "calls": 26,
      "input_tokens": 86823,
      "output_tokens": 9780
    },
    {
      "scope": "unused",
      "treatment": "revision_gate_multi",
      "count": 145,
      "completed": 143,
      "completion_rate": 0.9862068965517241,
      "failed_or_incomplete": 2,
      "accuracy": 0.6551724137931034,
      "macro_f1": 0.6551529702790206,
      "per_class_recall": {
        "SUPPORTS": 0.5416666666666666,
        "REVISIONS": 0.5625,
        "NEI": 0.8571428571428571
      },
      "calls": 804,
      "input_tokens": 3001317,
      "output_tokens": 324506
    },
    {
      "scope": "all",
      "treatment": "single_tools_shared_evidence",
      "count": 150,
      "completed": 146,
      "completion_rate": 0.9733333333333334,
      "failed_or_incomplete": 4,
      "accuracy": 0.7133333333333334,
      "macro_f1": 0.7178084674496158,
      "per_class_recall": {
        "SUPPORTS": 0.46,
        "REVISIONS": 0.84,
        "NEI": 0.84
      },
      "calls": 161,
      "input_tokens": 416772,
      "output_tokens": 86933
    },
    {
      "scope": "debug",
      "treatment": "single_tools_shared_evidence",
      "count": 5,
      "completed": 4,
      "completion_rate": 0.8,
      "failed_or_incomplete": 1,
      "accuracy": 0.8,
      "macro_f1": 0.8888888888888888,
      "per_class_recall": {
        "SUPPORTS": 0.5,
        "REVISIONS": 1.0,
        "NEI": 1.0
      },
      "calls": 6,
      "input_tokens": 14821,
      "output_tokens": 7986
    },
    {
      "scope": "unused",
      "treatment": "single_tools_shared_evidence",
      "count": 145,
      "completed": 142,
      "completion_rate": 0.9793103448275862,
      "failed_or_incomplete": 3,
      "accuracy": 0.7103448275862069,
      "macro_f1": 0.7123032284322607,
      "per_class_recall": {
        "SUPPORTS": 0.4583333333333333,
        "REVISIONS": 0.8333333333333334,
        "NEI": 0.8367346938775511
      },
      "calls": 155,
      "input_tokens": 401951,
      "output_tokens": 78947
    }
  ],
  "failures": [
    {
      "path": "revision_gate_multi/0/civic-61766705-9e86-4ee2-8e88-ea67f6031d2d.failed.json",
      "error": "model output was truncated; raise max_output_tokens"
    },
    {
      "path": "revision_gate_multi/0/civic-8476f8d8-55ca-473c-a0ea-5c2076715469.failed.json",
      "error": "model output failed schema or source-integrity validation"
    },
    {
      "path": "single_tools_shared_evidence/0/civic-400d7ece-0b3d-4e59-b363-e15373f94f42.failed.json",
      "error": "model output was truncated; raise max_output_tokens"
    },
    {
      "path": "single_tools_shared_evidence/0/civic-b56c778d-1332-4ae6-b19b-5af9104657ef.failed.json",
      "error": "model output was truncated; raise max_output_tokens"
    },
    {
      "path": "single_tools_shared_evidence/0/civic-cbb7fee3-56fa-43de-872c-ee2593c44233.failed.json",
      "error": "model output was truncated; raise max_output_tokens"
    },
    {
      "path": "single_tools_shared_evidence/0/civic-e1e3959b-e131-493e-a7b9-f3d33d0352e5.failed.json",
      "error": "model output was truncated; raise max_output_tokens"
    }
  ],
  "failure_status_counts": {
    "completed": 294,
    "failed": 6
  }
}
```
