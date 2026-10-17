# Engineering instructions

Read TASK.md, docs/EVALUATION.md and verification/README.md before changing behavior.

- Implement the stated research tasks, preserving the existing API and schema versions.
- Start by running supplied commands. Use actual failing cases to guide minimal complete fixes.
- Preserve answer/source/time isolation in every ablation and baseline.
- Keep mock results, loopback HTTP results and genuine model/benchmark results explicitly separate.
- Never turn provider failure into a mock success. Count failures and budget exhaustion in evaluation denominators.
- Validate real boundaries (uploads, provider responses, downloaded data, database state). Let broken internal invariants fail visibly.
- Retain source provenance, exact quotes, raw traces and cost-completeness flags.
- Never commit credentials, uploads, database files, raw benchmark texts or private annotation sheets.
- Freeze data, prompts, model parameters and study plans before evaluating test splits.
- Prefer local tests, explicit configuration and small changes. Add a regression test for each discovered bug.
- Scope is backend and algorithms. Frontend uses /v1 interfaces; keep new UI work separate.
