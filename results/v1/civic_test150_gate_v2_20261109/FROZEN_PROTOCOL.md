# Frozen CIViC-Fact test protocol

## What was frozen

The method, prompts, model settings, evidence access, repair budget, case
selection and test partition were frozen before the 150-case run.

| Item | Frozen value |
|---|---|
| Dataset | CIViC-Fact 2026.06.09 |
| Inputs SHA256 | `165c8d3415eb8588dcbafcc10eae378e1a3d0be30c1b9698bfae78b2b2d7183d` |
| Labels SHA256 | `f3221fa1e39e75a002f8a08c83bf409ffdf02e78c91d0ed7654ad7fe4c522088` |
| Model | `hc-qwen38-27b-fp8` |
| Temperature / seed | `0 / 0` |
| Hidden thinking budget | `0` |
| Native labels | `SUPPORTS / REVISIONS / NEI` |
| Test cases | 150; 50 each label; 150 distinct source groups across 71 articles |
| Maximum cases per article | 3 |
| Case selection seed | `20261108` |
| Plan SHA256 | `f7b4ac2cb7da612d633d4d4b076b02a7601595f2e04d7463bb2e224dfe659673` |
| Study identity | `315bf22afdeafe5366f644596df0d16503395486da19b4a6a3da819605e7ecf1` |
| Evidence mode | numbered fragment citation |
| Fragment budget | 12,000 characters, 600 characters per span, up to 8 spans per document |
| Model calls / tool calls per execution | at most 12 / 12 |
| Total input+output token ceiling | 260,000 |
| Output token ceiling per call | 5,000 |
| Schema repair limit | 2 |
| Parallel cases | 4, case-interleaved across arms |
| Arms | revision-gate seven-role multi agent; strong single agent with shared evidence and the same revision contract |

## Code under test

The code commit is the commit containing this file. It changes only the
verification-revision contract in `oncofusion/schemas.py`,
`oncofusion/engine.py`, `oncofusion/providers.py` and
`tests/test_claim_scopes.py`.

The task includes server-generated claim IDs and author roles, role-scoped
claim fields, a Verifier that reviews existing claims, visible evidence IDs
for citations, a separate revision assessment and bounded repair. These
features were already present in the preceding commit; this experiment tests
the revision assessment's stricter state mapping.

## Pre-test development history

The predeclared development subset was frozen in
`experiments/civic_phase_a_dev12_20261109.json`: 12 cases, four per label and
one per article. It ran once through each of three arms, 36 executions total.
The plan SHA256 is
`2fbeba21bf8b7f1642413d1161e4506b2885d87ea3b57a917e6407be99940f56`.

Two structural calibration cases were frozen before any development model
calls in `experiments/civic_revision_gate_calibration_dev2_20261109.json`.
The plan SHA256 is
`6b2bf8b67463f328e2cb7093d3ba1350603520c34ebc88003f52150f4e2bc9a1`.
Both rounds of trajectories, including the wrong result and the failed
pid-monitoring file, are retained. A previously prepared calibration plan
that accidentally named test cases was rejected by the runner before any
model call and is retained under `experiments/rejected/`.

No case in the 150-case test set was used to change the method during this
round. Five cases from three source articles in the test set had already been
used in earlier debugging. They are listed in
`experiments/civic_test_source_manifest.json` and reported separately.

## Analysis choices

Accuracy, Macro-F1 and per-class recall include every failed case in the
denominator. Completion includes only executions with status `completed`.
Paired differences cluster by article. Bootstrap draws 2,000 times with seed
0. The comparison is exploratory and has one repetition per arm, so the
interval is not a multi-seed stability estimate.

The old reference run remains a separate code version. Pairwise changes
between old and new versions are descriptive, not a substitute for a
controlled ablation. The new multi-agent and single-agent arms share evidence,
the revision label contract, and repair settings; their comparison isolates
collaboration and its associated call structure.

Provider pricing was not configured. `known_cost_usd=0` means cost is not
computable, not that inference was free.

## Stop and failure policy

Individual truncation or exhausted schema repair failures are recorded and
the batch continues. The formal batch was not stopped because failures were
sparse and individually attributable, with no common code crash, secret
leak, universal provider outage or cross-case protocol failure. No failed run
was retried to obtain a selected successful result.
