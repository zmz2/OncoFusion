# Vote-v1 supplemental experiment protocol

## Scope

This run evaluates the frozen vote-v1 classroom method through the predeclared E01–E09 analyses. It does not change the production algorithm, model, role prompts, evidence planner, voting rule, arbitration rule, web page, or PPT. MTB is the main task; CIViC is supplementary.

## Model and settings

- Display name: 千问 3.6 35B-A3B
- API model identifier: hc-qwen38-27b-fp8
- B0 temperature 0; specialist/generalist vote-pool temperature 0.4; seed 0
- Output limit 5,000 tokens; schema repair maximum 2
- Per-case call limits: B0 3, vote pool 12, arbitration 3
- Per-case total-token limit 260,000
- Arbitration: trigger when top vote share is strictly below 0.75 or first-to-second vote margin is strictly below 0.25; equal weight; fixed tie seed 0; failed arbitration retains the initial valid vote.
- The actual API-request concurrency across simultaneously active processes never exceeds 20.

## Total generation budget

There is no aggregate call-count or aggregate token cap for this evaluation. The fixed sample lists and per-case method limits above define the work; the run stops when the declared experiment rows have terminal results and exports are checked. No result-based resampling or success-only reruns are permitted.

## Data isolation

Frozen dataset and label fingerprints, sample manifests, historical-use groups, and evaluation-only label handling are recorded in FROZEN_PROTOCOL.json and SOURCE_REGISTER.json. Raw inputs, patient identifiers, full prompts, model responses, and complete traces remain on server21.

## Run and cleanup

Raw run data are stored temporarily in the private server result tree. After aggregating and validating all experiment tables and selected examples, remove this task's high-volume raw traces and logs only. Preserve the frozen protocol, plans and identities, aggregate result tables, selected private examples, and public redacted deliverables.
