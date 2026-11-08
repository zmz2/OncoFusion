| Arm / split | N | Complete | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all / current_multi | 12 | 100.0% | 0.750 | 0.696 | 1.000 | 0.250 | 1.000 | 68 | 250298 | 25673 |
| debug / current_multi | 0 | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 0 | 0 |
| unused / current_multi | 12 | 100.0% | 0.750 | 0.696 | 1.000 | 0.250 | 1.000 | 68 | 250298 | 25673 |
| all / revision_gate_multi | 12 | 100.0% | 0.833 | 0.822 | 1.000 | 0.500 | 1.000 | 72 | 275265 | 28832 |
| debug / revision_gate_multi | 0 | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 0 | 0 |
| unused / revision_gate_multi | 12 | 100.0% | 0.833 | 0.822 | 1.000 | 0.500 | 1.000 | 72 | 275265 | 28832 |
| all / single_tools_shared_evidence | 12 | 100.0% | 0.917 | 0.915 | 1.000 | 0.750 | 1.000 | 13 | 34082 | 4171 |
| debug / single_tools_shared_evidence | 0 | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 0 | 0 |
| unused / single_tools_shared_evidence | 12 | 100.0% | 0.917 | 0.915 | 1.000 | 0.750 | 1.000 | 13 | 34082 | 4171 |

```json
{
  "study_identity": "4cb76a2bb5193a58468c7a7d142209b6947ef27ba8dff434bf14f64b05089e65",
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
      "treatment": "current_multi",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.75,
      "macro_f1": 0.6962962962962963,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.25,
        "NEI": 1.0
      },
      "calls": 68,
      "input_tokens": 250298,
      "output_tokens": 25673
    },
    {
      "scope": "debug",
      "treatment": "current_multi",
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
      "treatment": "current_multi",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.75,
      "macro_f1": 0.6962962962962963,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.25,
        "NEI": 1.0
      },
      "calls": 68,
      "input_tokens": 250298,
      "output_tokens": 25673
    },
    {
      "scope": "all",
      "treatment": "revision_gate_multi",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.8333333333333334,
      "macro_f1": 0.8222222222222222,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.5,
        "NEI": 1.0
      },
      "calls": 72,
      "input_tokens": 275265,
      "output_tokens": 28832
    },
    {
      "scope": "debug",
      "treatment": "revision_gate_multi",
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
      "treatment": "revision_gate_multi",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.8333333333333334,
      "macro_f1": 0.8222222222222222,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.5,
        "NEI": 1.0
      },
      "calls": 72,
      "input_tokens": 275265,
      "output_tokens": 28832
    },
    {
      "scope": "all",
      "treatment": "single_tools_shared_evidence",
      "count": 12,
      "completed": 12,
      "completion_rate": 1.0,
      "failed_or_incomplete": 0,
      "accuracy": 0.9166666666666666,
      "macro_f1": 0.9153439153439153,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.75,
        "NEI": 1.0
      },
      "calls": 13,
      "input_tokens": 34082,
      "output_tokens": 4171
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
      "accuracy": 0.9166666666666666,
      "macro_f1": 0.9153439153439153,
      "per_class_recall": {
        "SUPPORTS": 1.0,
        "REVISIONS": 0.75,
        "NEI": 1.0
      },
      "calls": 13,
      "input_tokens": 34082,
      "output_tokens": 4171
    }
  ],
  "failures": [],
  "failure_status_counts": {
    "completed": 36
  }
}
```
