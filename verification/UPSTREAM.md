# v0.2 upstream component verification

Starting revision: `bf8efe2b1aafa9a78f0837e1433bd61da220a053` (510 passing tests).

## Locally completed checks

- Full offline regression: 614 tests passed before the final independent workflow-order switch; the additional switch regression also passed.
- Combined coverage at that full run: 97.3342%; statement coverage 98.1982%; branch coverage 94.8780%.
- Actual LangGraph 1.0.10 execution matches the Python reference on source views, decisions, reports, budgets and events.
- Actual ToolUniverse 1.5.7 imported and executed through its own SDK: 10 contract tests passed with upstream HTTP replaced by deterministic fixtures. These are separate from wrapper unit tests.
- Actual loopback HTTP: 27 presets, 177 simulated model requests, 11 transport checks passed.
- Exhaustive offline matrix: 4,208 case executions passed (2,048 feature combinations + 2,160 perturbation/preset cases).
- Wheel build completed; both upstream licenses and THIRD_PARTY_NOTICES are included in distribution metadata.

Model inference in these tests is simulated; commercial model API calls = 0.
A native runtime or SDK test is not a clinical-quality result.

## CI acceptance

The feature PR reruns the full suite on Python 3.11/3.12/3.13, existing public-data adapters, Docker and the new actual-SDK contract suite. Live public biomedical-service checks are recorded separately by `Upstream SDK acceptance`. A public endpoint failure is retained in `upstream_live.json` and does not turn into mock evidence. That live availability step is non-blocking for deterministic source/SDK acceptance.

`docs/AGENT_DESIGN.md` gives the per-Agent adoption decisions. `third_party/upstream-lock.json` records audited source revisions. The pinned toolkit package and repository HEAD are distinct provenance entries; no entire upstream agent is claimed to have been transplanted.

## Remaining quality acceptance

Connect a real model, run the two new presets on the development set, examine claim verdict quality and RCS citation support, and compare the separate 26-treatment plans. Preserve legacy baselines and use actual costs. Frozen test data remains untouched during prompt/architecture selection. `TASK.md` contains commands.
