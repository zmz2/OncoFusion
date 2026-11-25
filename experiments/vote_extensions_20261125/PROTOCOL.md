# Vote-v1 supplementary experiments

This branch freezes the vote-v1 method at source commit `a6351d3d8e5748d7894ab071aadeaf1edee06229`. The current primary method, specialist prompts, evidence planner, equal vote, tie rule, and selective arbitration stay unchanged; experimental input and prompt variants are isolated to this branch.

## Current frozen batch

MTB holdout uses 85 fixed cases from 19 source groups in the nominal 140-case test frame. Thirteen groups with historical case-level result files (45 cases) are excluded wholesale, including known debug group P-0004727. The full private register and exact case list are server-only. The public register contains hashes and counts. Data SHA256s and configurations are in `artifacts/vote_extensions_20261125/FROZEN_PROTOCOL.json`.

B0 and P-K are interleaved; V3 is derived from the same P-K ballots. The arbitration threshold is `top_share < .75 OR margin < .25`; failures remain in the denominator. The original model and per-case call/token guards remain fixed. The user removed the aggregate API-call and token budget ceiling; execution follows the finite predeclared experiment matrices.

## Execution

The experiment provider scheduler is set to 20 concurrent requests. All calls, repairs, and arbitration use the same process-wide scheduler. The experiment process runs one stage at a time. Data and full traces remain private on server21.

## Cleanup after completion

After all tables, hashes, and representative examples are validated, remove only high-volume logs and full traces created under this run directory. Preserve result tables, frozen plans, manifests, progress, and selected example traces. Do not modify historical runs or source datasets.
