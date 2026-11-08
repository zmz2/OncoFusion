# CIViC-Fact 150-case independent experiment

This is the primary CIViC-Fact component evaluation. MTBBench was not started.

## Freeze and provenance

- Code: `5d5a671d9fb3429be6445a89357052cee9a0cb54` at test launch.
- Model: `hc-qwen38-27b-fp8`, temperature 0, seed 0, hidden thinking budget 0.
- Dataset: CIViC-Fact 2026.06.09. Input SHA256
  `165c8d3415eb8588dcbafcc10eae378e1a3d0be30c1b9698bfae78b2b2d7183d`; label SHA256
  `f3221fa1e39e75a002f8a08c83bf409ffdf02e78c91d0ed7654ad7fe4c522088`.
- Test subset: 150 cases, exactly 50 each of SUPPORTS, REVISIONS and NEI; 71 articles;
  maximum three cases per article. One frozen execution per arm.
- Arms: seven-role `v1_class` and `single_tools_shared_evidence`. Both use the same model,
  retrieval, fragment representation, 12,000-character evidence budget, 260,000-token sum
  budget, 5,000-token output cap and two bounded schema repairs.
- Execution: case-interleaved, four cases in flight, 300 total executions.
- Study identity: `392077d8c061273235f4d52d99dcb6f3f1f11719892089f597fb19e3cc7a8e4b`.

All prior runs, failed runs and calibration directories remain in Git. The first 12-case
development run was command-construction error analysis and is not part of the final test
estimate. The final 12-case development calibration completed 24/24 and preceded the frozen
test run.

## Debug-source disclosure

Five selected test cases from three article groups had already been used for error analysis:

- `civic-00693f9a-e755-4b1a-a158-c6ea8d40247b` (`article-31160355`)
- `civic-31021ed2-d0a0-4772-8495-6290df86983f` (`article-20147967`)
- `civic-400d7ece-0b3d-4e59-b363-e15373f94f42` (`article-20147967`)
- `civic-af46590a-d6fd-48bc-b077-3d4aa78afdbe` (`article-20147967`)
- `civic-d2956c41-9709-44ff-923d-9991d7f00a54` (`article-20979473`)

The remaining 145 cases from 68 articles are unused test groups. The table reports both
partitions and does not describe all 150 cases as completely unseen.

## Main result

| Arm / split | N | Complete | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all / v1_class | 150 | 100.0% | 0.607 | 0.580 | 0.600 | 0.280 | 0.940 | 817 | 2,907,727 | 310,231 |
| debug / v1_class | 5 | 100.0% | 0.800 | 0.778 | 1.000 | 0.500 | 1.000 | 26 | 81,246 | 8,349 |
| unused / v1_class | 145 | 100.0% | 0.600 | 0.571 | 0.583 | 0.271 | 0.939 | 791 | 2,826,481 | 301,882 |
| all / single_tools_shared_evidence | 150 | 99.3% | 0.660 | 0.644 | 0.700 | 0.380 | 0.900 | 150 | 311,938 | 49,130 |
| debug / single_tools_shared_evidence | 5 | 100.0% | 0.400 | 0.356 | 0.500 | 0.000 | 1.000 | 5 | 9,114 | 1,515 |
| unused / single_tools_shared_evidence | 145 | 99.3% | 0.669 | 0.654 | 0.708 | 0.396 | 0.898 | 145 | 302,824 | 47,615 |

The single-agent arm's one failure is
`civic-cbb7fee3-56fa-43de-872c-ee2593c44233`: output reached the provider's 5,000-token limit.
It remains in the denominator as failed/incomplete. No successful rerun was substituted.

## Paired difference and interpretation

The paired case accuracy difference (single-agent minus seven-agent) was +0.0533, with a
patient/article-clustered bootstrap 95% interval of [-0.0216, 0.1267] over 71 groups. This
does not establish a positive seven-agent advantage; the point estimate is higher for the
single-agent baseline, and the interval includes zero.

REVISIONS recall is the main weakness of both systems: 0.280 for seven-agent and 0.380 for
single-agent. Both instead make many NEI predictions. The result supports keeping the
single-agent baseline as a serious comparator and investigating revision detection before
treating specialist role count as a benefit.

Cost differs sharply: the seven-agent arm used 817 calls and 3,217,958 tokens, versus
150 calls and 361,068 tokens for the single-agent arm. The provider did not supply prices, so
`known_cost_usd=0` is an unset computable field, not a zero-cost claim.

## Protocol audit

- Every one of the 150 seven-agent cases has one final Decision call and a verifier ledger.
- Missing specialist modalities were registered as a valid `not_applicable` claim: Timeline
  150 cases; Drug 53; Genomics 30; Pathology 13. Their skipped-role events do not hide cases
  from the denominator.
- The single-agent schema had no upstream claim roster or verifier ledger in any case.
- Bounded schema recovery produced 13 invalid attempts: Pathology 8, Drug 3, Verifier 2.
  All owning cases completed within the fixed repair limit; no manual retry occurred.
- There were no extra agent roles and no changes to the 2026.06.09 native vocabulary.

## Case 1: revisions rather than a copy of the source claim

`civic-71a34c3c-862b-40b7-b76e-f577a6a4ed7b` (debug group; gold REVISIONS): Literature
identifies VHL disease and the p.R161X protein change. Genomics raises the same claim to
REVISIONS because the supplied text does not explicitly establish the nucleotide change
c.481C>T. Pathology and Drug find no applicable patient-specific material and emit explicit
not-applicable claims. The final Verifier corrects both source claims and marks the
non-applicable claims insufficient. Decision adopts the source and molecular claims, excludes
the non-applicable ones, and answers REVISIONS while recording the missing nucleotide evidence
as unresolved. This demonstrates the intended distinction between a supported fact, a claim
needing revision, and material that was never supplied.

## Case 2: a compatible therapy does not support the stated histology

`civic-d4924b6b-fe96-40ef-b328-18b73109470d` (unused test group; gold NEI): Literature and
Genomics report BRAF V600E NSCLC activity for dabrafenib plus trametinib. Drug records that
relationship, but separates it from the absent exposure history. The final evidence does not
establish that the study population is basaloid lung carcinoma. The Decision therefore keeps
the therapy activity claims but rejects the applicability claim and answers NEI, with the
histology gap in unresolved. This demonstrates that specialist agreement on a neighboring
fact does not override an entity/context mismatch in the benchmark claim.

## Artifacts

- Raw study: `results/v1/civic_test150_frozen_20261108/run/`
- Per-case failed trace: `results/v1/civic_test150_frozen_20261108/run/single_tools_shared_evidence/0/civic-cbb7fee3-56fa-43de-872c-ee2593c44233.failed.json`
- Command-level call audit: `results/v1/civic_test150_frozen_20261108/provider_calls.jsonl`
- Machine-readable table/report: `results/v1/civic_test150_frozen_20261108/main_table.md`

The present result is a single-seed component evaluation. It does not support significance
claims, full ablation conclusions or MTBBench integration conclusions.
