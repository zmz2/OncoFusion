| Arm / split | N | Complete | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all / v1_class | 12 | 100.0% | 0.833 | 0.838 | 0.750 | 0.750 | 1.000 | 65 | 214491 | 23975 |
| debug / v1_class | 0 | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 0 | 0 |
| unused / v1_class | 12 | 100.0% | 0.833 | 0.838 | 0.750 | 0.750 | 1.000 | 65 | 214491 | 23975 |
| all / single_tools_shared_evidence | 12 | 100.0% | 0.667 | 0.628 | 0.750 | 0.250 | 1.000 | 12 | 22478 | 4330 |
| debug / single_tools_shared_evidence | 0 | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 0 | 0 |
| unused / single_tools_shared_evidence | 12 | 100.0% | 0.667 | 0.628 | 0.750 | 0.250 | 1.000 | 12 | 22478 | 4330 |

```json
{
  "study_identity": "a6c47715fedf7f80d1097cef1973b997364027da4b56ac5d1f7bcddaa3f1bad3",
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
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.8333333333333334,
      "macro_f1": 0.8380952380952381,
      "per_class_recall": {
        "SUPPORTS": 0.75,
        "REVISIONS": 0.75,
        "NEI": 1.0
      },
      "calls": 65,
      "input_tokens": 214491,
      "output_tokens": 23975
    },
    {
      "scope": "debug",
      "treatment": "v1_class",
      "count": 0,
      "completed": 0,
      "completion_rate": null,
      "failed_or_incomplete": 0,
      "accuracy": null,
      "macro_f1": null,
      "per_class_recall": {
        "SUPPORTS": null,
        "REVISIONS": null,
        "NEI": null
      },
      "calls": 0,
      "input_tokens": 0,
      "output_tokens": 0
    },
    {
      "scope": "unused",
      "treatment": "v1_class",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.8333333333333334,
      "macro_f1": 0.8380952380952381,
      "per_class_recall": {
        "SUPPORTS": 0.75,
        "REVISIONS": 0.75,
        "NEI": 1.0
      },
      "calls": 65,
      "input_tokens": 214491,
      "output_tokens": 23975
    },
    {
      "scope": "all",
      "treatment": "single_tools_shared_evidence",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.6666666666666666,
      "macro_f1": 0.6277777777777778,
      "per_class_recall": {
        "SUPPORTS": 0.75,
        "REVISIONS": 0.25,
        "NEI": 1.0
      },
      "calls": 12,
      "input_tokens": 22478,
      "output_tokens": 4330
    },
    {
      "scope": "debug",
      "treatment": "single_tools_shared_evidence",
      "count": 0,
      "completed": 0,
      "completion_rate": null,
      "failed_or_incomplete": 0,
      "accuracy": null,
      "macro_f1": null,
      "per_class_recall": {
        "SUPPORTS": null,
        "REVISIONS": null,
        "NEI": null
      },
      "calls": 0,
      "input_tokens": 0,
      "output_tokens": 0
    },
    {
      "scope": "unused",
      "treatment": "single_tools_shared_evidence",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.6666666666666666,
      "macro_f1": 0.6277777777777778,
      "per_class_recall": {
        "SUPPORTS": 0.75,
        "REVISIONS": 0.25,
        "NEI": 1.0
      },
      "calls": 12,
      "input_tokens": 22478,
      "output_tokens": 4330
    }
  ],
  "failures": [],
  "failure_status_counts": {
    "completed": 24
  }
}
```
