# v0.2 upstream component verification — 2026-10-17

Starting revision: `bf8efe2b1aafa9a78f0837e1433bd61da220a053` (510 passing tests).
Verified source revision: `aafe22649ba599c299597f4948d95836f99c414a`. Later documentation-only commits record this acceptance.

## Completed checks

| Check | Actual result |
|---|---|
| Core regression | 615 passed, zero failures or skips; one upstream pytest deprecation warning |
| Python compatibility | GitHub Actions 3.11 / 3.12 / 3.13 jobs all passed |
| Coverage, Python 3.12 | Combined 97.3350%; statements 98.1990%; branches 94.8780% |
| Actual LangGraph 1.0.10 | Node execution and bounded conditional requery; event/result/budget parity with Python reference |
| Actual ToolUniverse 1.5.7 | 10 SDK contract tests with deterministic HTTP fixtures passed locally and in the dedicated full-dependency CI job |
| Actual loopback HTTP | 27 presets, 177 simulated model requests, 11 transport checks passed |
| Exhaustive offline scenarios | 4,208 case executions passed: 2,048 feature combinations + 2,160 perturbation/preset cases |
| Distribution | Wheel build passed; both upstream licenses and THIRD_PARTY_NOTICES are included |
| Docker | Non-root image and authenticated frontend contract passed |
| Public benchmark adapters | Existing authentic MTBBench, CIViC-Fact and retrieval integration jobs passed |
| Live public knowledge tools | All six ToolUniverse endpoints and the adapted GeneAgent Enrichr flow returned valid results |

The core suite increased by 105 regression cases. The dedicated actual-SDK tests are a separate suite.

## Live services versus model inference

The live check used reviewed public queries and called MyGene, OncoTree, Reactome, ChEMBL, OpenTargets, PubMed and Enrichr. PubMed returned one attachable abstract; Enrichr returned ten hits. Response hashes and durations are preserved in `upstream_live.json`. This demonstrates observed endpoint compatibility, not future availability or biomedical answer accuracy.

All model inference in this pass is simulated. Commercial model API calls = 0. Source/SDK correctness and biomedical quality are separate acceptance criteria.

## Reproducible CI records

- Core Python matrix, HTTP, stress and wheel: https://github.com/zmz2/OncoFusion/actions/runs/39016559385
- Actual SDK and live knowledge services: https://github.com/zmz2/OncoFusion/actions/runs/39016559351
- Public benchmark integration: https://github.com/zmz2/OncoFusion/actions/runs/39016559469
- Docker acceptance: https://github.com/zmz2/OncoFusion/actions/runs/39016559311

Live availability is deliberately reported separately from deterministic SDK contracts. Its CI step is non-blocking, retains failures, and never substitutes mock evidence. In the recorded run all seven live checks passed.

`docs/AGENT_DESIGN.md` gives the per-Agent adoption decisions. `third_party/upstream-lock.json` records reviewed source revisions. Pinned toolkit package versions and audited repository HEADs are distinct provenance entries. Reuse is stated at the actual granularity: runtime dependency, adapted function, copied prompts or architectural reference.

## Remaining quality acceptance

Connect a real model, run `grounded_v2` and `grounded_v2_contexts` on development data, inspect per-claim semantic judgments and RCS citation support, and compare the separate 26-treatment plans. Preserve legacy baselines and report actual costs. Test data stays frozen during prompt/architecture selection. Root `TASK.md` contains the exact commands and preserves the existing backend handover.
