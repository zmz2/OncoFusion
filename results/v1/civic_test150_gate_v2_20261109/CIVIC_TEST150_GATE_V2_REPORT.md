# CIViC-Fact 150-case revision-gate experiment

## Result

This is a frozen test run. The revision-gate seven-role system does not beat
the strong single-agent control on CIViC-Fact.

| System / partition | N | Completion | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| revision-gate multi / all test | 150 | 98.7% | 0.653 | 0.654 | 0.540 | 0.560 | 0.860 | 830 | 3,088,140 | 334,286 |
| revision-gate multi / previously debugged | 5 | 100.0% | 0.600 | 0.667 | 0.500 | 0.500 | 1.000 | 26 | 86,823 | 9,780 |
| revision-gate multi / unused test groups | 145 | 98.6% | 0.655 | 0.655 | 0.542 | 0.562 | 0.857 | 804 | 3,001,317 | 324,506 |
| single tools / all test | 150 | 97.3% | 0.713 | 0.718 | 0.460 | 0.840 | 0.840 | 161 | 416,772 | 86,933 |
| single tools / previously debugged | 5 | 80.0% | 0.800 | 0.889 | 0.500 | 1.000 | 1.000 | 6 | 14,821 | 7,986 |
| single tools / unused test groups | 145 | 97.9% | 0.710 | 0.712 | 0.458 | 0.833 | 0.837 | 155 | 401,951 | 78,947 |

The paired single-agent minus multi-agent Accuracy difference is `+0.060` with
an article-clustered bootstrap 95% interval `[-0.040, 0.153]` over 71 groups.
The interval crosses zero, but the point estimate favors the single agent.
McNemar discordance is 27 single-agent wins versus 18 multi-agent wins.

The revised seven-role system uses 1,164,507 observed tokens versus 503,705
for the single agent, about 2.31 times as many. Its mean execution time is
36.61 seconds versus 7.64 seconds. The provider supplied no prices, so
`known_cost_usd=0` is an unset computable field, not a zero-cost claim.

## Development comparison

The predeclared 12-case development calibration had 4 cases in each native
label and one case per article.

| Development system | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls |
|---|---:|---:|---:|---:|---:|---:|
| current multi | 0.750 | 0.696 | 1.000 | 0.250 | 1.000 | 68 |
| revision-gate multi | 0.833 | 0.822 | 1.000 | 0.500 | 1.000 | 72 |
| shared-evidence single agent | 0.917 | 0.915 | 1.000 | 0.750 | 1.000 | 13 |

The gate changed one development case from wrong to right and another from
right to wrong. Net development correction was one case, with a clustered
bootstrap interval crossing zero.

On the same 150 test cases, the gate changed the old multi-agent result from
17 wrong to right and 10 right to wrong: a net gain of seven cases. The old
multi-agent REVISIONS recall was 0.280; the gate raised it to 0.560. The cost
was a fall in SUPPORTS recall from 0.600 to 0.540 and in NEI recall from
0.940 to 0.860. The gate therefore addressed the target failure mode but
over-applied repair to some claims that were already supported or irrelevant.

The new single agent also received the same correction contract. Its
REVISIONS recall rose from 0.380 to 0.840 while SUPPORTS recall fell from
0.700 to 0.460. It also gained eight net cases over the old single-agent run.
The contract's effect is therefore not specific to multi-agent collaboration.

## Freeze and provenance

- Code: `oncofusion/schemas.py`, `oncofusion/engine.py`,
  `oncofusion/providers.py` and `tests/test_claim_scopes.py` at the
  `civic-test150-gate-v2` commit containing this report.
- Model: `hc-qwen38-27b-fp8`; temperature 0, seed 0, hidden thinking budget 0.
- Dataset: CIViC-Fact 2026.06.09. Inputs SHA256
  `165c8d3415eb8588dcbafcc10eae378e1a3d0be30c1b9698bfae78b2b2d7183d`;
  labels SHA256 `f3221fa1e39e75a002f8a08c83bf409ffdf02e78c91d0ed7654ad7fe4c522088`.
- Test subset: 150 cases, 50 per native label, 71 articles, at most three
  cases per article. The plan SHA256 is
  `f7b4ac2cb7da612d633d4d4b076b02a7601595f2e04d7463bb2e224dfe659673`.
- Study identity: `315bf22afdeafe5366f644596df0d16503395486da19b4a6a3da819605e7ecf1`.
- Plan and execution history: `experiments/civic_test150_gate_v2_20261109.json`;
  the output directory is `results/v1/civic_test150_gate_v2_20261109`.
- Execution order: case-interleaved, total concurrency 4, one execution per arm.
- Common protocol: fragment citation mode, 12,000-character evidence budget,
  260,000-token total ceiling, 5,000-token output ceiling, and two bounded
  schema repairs.

Five cases from three articles had been used earlier for error analysis. They
are labelled debug in the table and source manifest. No other selected test
group was used for the revision-gate method adjustment. The old 150-case
results remain in `results/v1/civic_test150_frozen_20261108`; versions are
compared separately and never merged into one estimate.

## Failures and protocol audit

The revision-gate arm has 148 completed and two failed executions:

- `civic-61766705-9e86-4ee2-8e88-ea67f6031d2d`: Literature output reached
  the 5,000-token limit and was truncated.
- `civic-8476f8d8-55ca-473c-a0ea-5c2076715469`: three Decision responses in
  this one execution used an illegal revision field; the two allowed repairs
  were exhausted.

The single-agent arm has 146 completed and four failed executions. All four
are final Decision outputs truncated at 5,000 tokens:
`civic-400d7ece-0b3d-4e59-b363-e15373f94f42`,
`civic-b56c778d-1332-4ae6-b19b-5af9104657ef`,
`civic-cbb7fee3-56fa-43de-872c-ee2593c44233` and
`civic-e1e3959b-e131-493e-a7b9-f3d33d0352e5`.

All failures stay in the denominator. No failed case was rerun for a selected
successful answer. Failures were individually bounded and did not warrant
abandoning the batch.

For the 148 completed multi-agent executions:

- 817 professional claims carry server-assigned claim IDs and author roles.
- 997 verdicts target only claims that were already registered by prior roles.
- 0 verdicts come from the first role.
- Verifier emits 0 findings and only emits verdicts.
- 0 claim scopes violate the role contract.
- 0 not-applicable/unknown claims cite evidence or assert a relation.
- 0 final citations point outside the visible document set.
- Every successful final decision contains exactly one revision assessment.
- 27 multi-agent executions needed bounded repair; 31 invalid model responses
  were recorded. The single agent needed repair in 11 executions with 11
  invalid responses. Repair calls count in usage.

## Case 1: minimum correction after a local drug-direction conflict

`civic-e67920d6-4f2b-4044-a092-72c23a27c45d`, gold `REVISIONS`.

The claim says alectinib produces sensitivity/response for head-and-neck
cancer with EML4-ALK and ALK G1202R. The visible paper states that G1202R was
highly refractory to alectinib (`RR=27.9`) in NPM-ALK and EML4-ALK cellular
models.

Literature reports resistance. Drug turns that local fact into a
`REVISIONS` claim. Verifier confirms the resistance claim and rejects the
head-and-neck extrapolation. Decision's assessment records
`evidence_relevance=relevant`, `claim_conformance=requires_revision`, legal
revision fields `disease`, `evidenceDirection` and `significance`, and a
minimal corrected claim. It answers `REVISIONS` with the exact source span.
This makes the local relation, verification record and global label
inspectable as separate objects.

## Case 2: gate aid and gate overgeneralization

`civic-567e22df-d40e-4314-b42a-053aa8243168`, gold `REVISIONS`.

The evidence studies EGFR L858R and EGFR-TKI responses in NSCLC models. The
claim instead says L858R means resistance to a broad antineoplastic enzyme
inhibitor class in large-cell neuroendocrine carcinoma.

The seven-role system marks evidence as relevant and represents the exact
corrections as disease, therapy and significance. It answers `REVISIONS`.
This shows why the revision state was useful.

The single-agent run also sees the same disease, therapy and direction
mismatches, but sets `evidence_relevance=irrelevant` and answers `NEI`. This
one failure disappears if disease relevance is assessed at the molecular
relation and study-population level rather than requiring exact label
identity.

`civic-399ce656-039e-44dd-984f-8f0c8c5ae1c8` shows the opposite error. Its
supplied document is about NPM1-mutated AML, while the claim concerns
PIK3CA E545K and afatinib in nasal-cavity adenocarcinoma. Every specialist
correctly says the source is unrelated, yet Decision interprets the claim's
`DOES_NOT_SUPPORT` direction as satisfied by absence of evidence and answers
`SUPPORTS`. The single agent answers `NEI`, as it should.

Together, these cases identify the next mechanism to test: a strict
distinction between evidence relevance and relation direction, plus a
repository of legal claim fields. An entirely unrelated source must remain
NEI even when the original claim has a negative stance.

## Artifacts

- Raw study: `results/v1/civic_test150_gate_v2_20261109/run/`
- Main table: `results/v1/civic_test150_gate_v2_20261109/main_table.md`
- Machine-readable statistics: `results/v1/civic_test150_gate_v2_20261109/summary.json`
- Provider call log: `results/v1/civic_test150_gate_v2_20261109/provider_calls.jsonl`
- Development calibration: `results/v1/civic_phase_a_dev12_20261109/`
- Old reference run: `results/v1/civic_test150_frozen_20261108/`

This is a single-seed component study. It does not establish MTBBench
integration performance, complete per-agent ablations or repeated-seed
stability.
