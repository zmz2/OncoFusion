# Independent backend verification — 2026-10-17

The starting repository already contained the seven-agent backend and 446 tests. This pass first reproduced those tests on Python 3.11, 3.12 and 3.13 in GitHub Actions, then added independent failing regression cases.

## Corrected defects

- The latest verifier's unresolved concerns were omitted from the decision payload. They are now passed as sourced role context; a newer role report replaces its older unresolved list.
- Variant normalization and disease matching ablations did not reach the retrieval reranker. Both switches now govern every affected preprocessing path.
- Provider retry and timeout settings were absent from the inference/cache identity.
- The pinned CIViC-Fact 2026.06.09 release uses SUPPORTS / REVISIONS / NEI. REVISIONS is preserved as a native label, with a release-level verification_scheme. It is not mapped to REFUTES. Gold revised claims, curator descriptions and reviews remain evaluator-only.
- Real MTBBench includes empty source files. These are audited and skipped without creating biological absence claims.
- Independent retrieval includes repeated query groups with conflicting source labels. Preparation excludes the entire ambiguous query group and requires explicit audit acceptance.

## Evidence obtained

Initial CI: https://github.com/zmz2/OncoFusion/actions/runs/39007477337 — all three Python versions, loopback HTTP, offline stress and wheel build passed.

Initial authentic-source integration: https://github.com/zmz2/OncoFusion/actions/runs/39007655854 — exposed the three real-data adapter failures above. These failures are retained as discovery evidence, not passed acceptance.

Local tests after source corrections: 473 passed. Native-label tests preserve SUPPORTS, REVISIONS and NEI without passing gold revisions to inference.

Official label definitions: https://github.com/creisle/civicfact/blob/1a767d889b015a836f0f4331afcac5cef165ec7f/experiments/src/api/create_explanation_prompts.py

This file will be finalized after the corrected authentic-source integration and additional backend regressions. All model outputs in this pass are simulated; no real model quality claim is made.
