# Classroom web v2

The isolated branch imports source code (no data/results history) from server21
commit e4711bada390b32a28795e5128f2ebb00e4a2a9e. The algorithm files
vote_runner.py, voting.py, evidence.py and agent_design.py are unchanged from
that snapshot. This is a newly committed runnable implementation, not a
byte-exact recovery of the dirty worktree used by the historical MTB43 run.

The new page is /classroom; the previous /app and /v1 contracts remain
available. The classroom routes project persisted runs and append-only events
from the existing Store. Fixed-run submission uses stable idempotency keys:
three selected cases times B0/OncoFusion, once per slot. OncoFusion uses V3:
four selected professional ballots at most, unweighted counts, fixed tie
breaking, conditional semantic arbitration, two structural repairs, and
initial-label retention after arbiter failure. Decision is assembly logic.

All six executions share the provider's process-wide 20-slot scheduler.
Provider retries remain zero, matching the validated environment. Full source
inputs, reference labels, SQLite state, raw logs and full traces stay outside
Git. Gold is joined by the presentation/evaluation route only after the run is
terminal; it never appears in the submitted CaseInput or provider payload.

## Start on server21

Use the dedicated checkout and the existing installed Python environment:

    source ~/.config/oncofusion/real-api.env
    export ONCOFUSION_SEND_TEMPERATURE=true ONCOFUSION_SEND_SEED=true
    export ONCOFUSION_API_CONCURRENCY=20
    export PYTHONPATH=.
    /home/zhangmingzhou/BioOncoFusion/.venv/bin/python scripts/prepare_classroom_v2.py \
      --project /home/zhangmingzhou/BioOncoFusion \
      --out /home/zhangmingzhou/BioOncoFusion/runtime/classroom_web_v2_20261110
    /home/zhangmingzhou/BioOncoFusion/.venv/bin/python scripts/serve_classroom_v2.py \
      --root /home/zhangmingzhou/BioOncoFusion/runtime/classroom_web_v2_20261110 --port 8181

Prepare only before the frozen batch; do not replace protocol identity after
runs exist. Normal restart only needs the serve command. The service refuses
mock providers. After the six runs, presentation/API projections may be
corrected while frozen inference files are checked against their committed
bytes. The execution commit and initial environment remain attached to the
original records; a later UI commit never replaces them.

From the user's Mac, create a private tunnel and open the page:

    ssh -N -L 18181:127.0.0.1:8181 server21-direct
    open http://127.0.0.1:18181/classroom

The default view is suitable for public projection. Original questions and
clinical source text are available only by explicitly enabling the server
original view through this private tunnel. Upload uses the existing JSON/JSONL
protocol for inspection; it does not add another execution to the fixed batch.

## Publication

The upstream code repository has an MIT software license, but that alone does
not establish redistribution permission for the patient source corpus.
Prepared data has empty source license fields. Public exports therefore omit
clinical source quotes, ages and patient identifiers and label every omitted
passage. Chinese case/source summaries are derived presentation annotations,
not verbatim evidence. Chinese ballot summaries must match the SHA256 of the
exact saved reason; unmatched translations are not displayed.

The MCQ input protocol inherits a constant verification_scheme=refutes default
(not a gold label). Some historical ballots misread that constant as evidence.
This classroom delivery preserves the algorithm and records that limitation.
Historical results and the six new runs are reported separately.

Upstream references:

- https://github.com/bunnelab/mtbbench/blob/main/LICENSE
- https://github.com/bunnelab/mtbbench#datasets
