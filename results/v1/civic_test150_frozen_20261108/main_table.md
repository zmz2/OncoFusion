| Arm / split | N | Complete | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all / v1_class | 150 | 100.0% | 0.607 | 0.580 | 0.600 | 0.280 | 0.940 | 817 | 2907727 | 310231 |
| debug / v1_class | 5 | 100.0% | 0.800 | 0.778 | 1.000 | 0.500 | 1.000 | 26 | 81246 | 8349 |
| unused / v1_class | 145 | 100.0% | 0.600 | 0.571 | 0.583 | 0.271 | 0.939 | 791 | 2826481 | 301882 |
| all / single_tools_shared_evidence | 150 | 99.3% | 0.660 | 0.644 | 0.700 | 0.380 | 0.900 | 150 | 311938 | 49130 |
| debug / single_tools_shared_evidence | 5 | 100.0% | 0.400 | 0.356 | 0.500 | 0.000 | 1.000 | 5 | 9114 | 1515 |
| unused / single_tools_shared_evidence | 145 | 99.3% | 0.669 | 0.654 | 0.708 | 0.396 | 0.898 | 145 | 302824 | 47615 |

```json
{
  "study_identity": "392077d8c061273235f4d52d99dcb6f3f1f11719892089f597fb19e3cc7a8e4b",
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
      "treatment": "v1_class",
      "count": 150,
      "completed": 150,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.6066666666666667,
      "macro_f1": 0.5802362984129447,
      "per_class_recall": {
        "SUPPORTS": 0.6,
        "REVISIONS": 0.28,
        "NEI": 0.94
      },
      "calls": 817,
      "input_tokens": 2907727,
      "output_tokens": 310231
    },
    {
      "scope": "debug",
      "treatment": "v1_class",
      "count": 5,
      "completed": 5,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.8,
      "macro_f1": 0.7777777777777778,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.5,
        "NEI": 1.0
      },
      "calls": 26,
      "input_tokens": 81246,
      "output_tokens": 8349
    },
    {
      "scope": "unused",
      "treatment": "v1_class",
      "count": 145,
      "completed": 145,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.6,
      "macro_f1": 0.5713690290477677,
      "per_class_recall": {
        "SUPPORTS": 0.5833333333333334,
        "REVISIONS": 0.2708333333333333,
        "NEI": 0.9387755102040817
      },
      "calls": 791,
      "input_tokens": 2826481,
      "output_tokens": 301882
    },
    {
      "scope": "all",
      "treatment": "single_tools_shared_evidence",
      "count": 150,
      "completed": 149,
      "completion_rate": 0.9933333333333333,
      "failed_or_incomplete": 1,
      "accuracy": 0.66,
      "macro_f1": 0.644023569023569,
      "per_class_recall": {
        "SUPPORTS": 0.7,
        "REVISIONS": 0.38,
        "NEI": 0.9
      },
      "calls": 150,
      "input_tokens": 311938,
      "output_tokens": 49130
    },
    {
      "scope": "debug",
      "treatment": "single_tools_shared_evidence",
      "count": 5,
      "completed": 5,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.4,
      "macro_f1": 0.35555555555555557,
      "per_class_recall": {
        "SUPPORTS": 0.5,
        "REVISIONS": 0.0,
        "NEI": 1.0
      },
      "calls": 5,
      "input_tokens": 9114,
      "output_tokens": 1515
    },
    {
      "scope": "unused",
      "treatment": "single_tools_shared_evidence",
      "count": 145,
      "completed": 144,
      "completion_rate": 0.993103448275862,
      "failed_or_incomplete": 1,
      "accuracy": 0.6689655172413793,
      "macro_f1": 0.6535767372723895,
      "per_class_recall": {
        "SUPPORTS": 0.7083333333333334,
        "REVISIONS": 0.3958333333333333,
        "NEI": 0.8979591836734694
      },
      "calls": 145,
      "input_tokens": 302824,
      "output_tokens": 47615
    }
  ],
  "failures": [
    {
      "path": "single_tools_shared_evidence/0/civic-cbb7fee3-56fa-43de-872c-ee2593c44233.failed.json",
      "error": "model output was truncated; raise max_output_tokens"
    }
  ],
  "failure_status_counts": {
    "completed": 299,
    "failed": 1
  }
}
```
