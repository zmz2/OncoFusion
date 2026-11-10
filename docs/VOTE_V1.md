# vote-v1 independent ballot protocol

## Scope

`vote-v1` is a separate execution path. It does not alter historical
`v1_class`, `v1_fast`, RouteEngine or earlier result files.

The five professional roles receive the same complete question and the same
common evidence packet. They independently return one task-level label,
confidence, short evidence-backed findings and cited `evidence_id` values.
Verifier and Decision never cast independent votes.

## Configuration

Use `oncofusion.profiles.vote_v1_config()` or
`GET /v1/configs/vote`.

- `execution_model=vote`
- `interaction_protocol=vote-v1`
- maximum two structural repairs per node
- 5,000-token node output ceiling
- temperature and seed are sent only when the provider accepts them
- all provider calls use the existing process-wide scheduler

The validated real-provider configuration sends both fields. Each independent
member uses its own seed (`base_seed + member_index`), and structural repairs
use subsequent seeds. B0 remains greedy. The provider identity in the run
records whether temperature and seed were actually sent; changing either flag
creates a different study identity.

The default plan uses:

- B0 common single: one generic answer on the same common evidence packet.
- G-K: K independent generic samples, with K equal to the applicable
  professional-role count for that case.
- P-K: K independent professional ballots.

The select plans are:

- `experiments/vote_v1_mtb_dev43_20261109.json`
- `experiments/vote_v1_civic_dev60_20261109.json`

The source-isolated development plans are:

- `experiments/vote_v1_civic_calibration_20261109.json`
- `experiments/vote_v1_civic_confirm_20261109.json`

`experiments/vote_v1_source_isolation_20261110.json` records the actual
article-group intersections among development, calibration, confirmation and
the historical 150-case/71-article diagnostic set. The current frozen plans
have zero pairwise source-group overlap.

## Commands

```bash
python scripts/make_vote_plans.py
python scripts/run_study.py \
  --plan experiments/vote_v1_civic_dev60_20261109.json \
  --dataset data/civicfact-pmidids \
  --out results/v1/vote_v1_civic_dev60_20261110_sampling_run3 \
  --execution-cap 180 --workers 4 --interleave-treatments
```

The plan output contains exactly one generation pass per ballot pool. V0,
V1, V2 and C-raw must be computed from the stored ballots, not regenerated:

```bash
python scripts/fit_vote_calibration.py \
  --run results/v1/vote_v1_civic_calibration_20261110_sampling_run2 \
  --dataset data/civicfact-pmidids \
  --out results/v1/vote_v1_civic_calibration_20261110_sampling_run2/calibration.json

python scripts/analyze_vote_pool.py \
  --run results/v1/vote_v1_civic_dev60_20261110_sampling_run3 \
  --dataset data/civicfact-pmidids \
  --weights results/v1/vote_v1_civic_calibration_20261110_sampling_run2/calibration.json \
  --calibration results/v1/vote_v1_civic_calibration_20261110_sampling_run2/calibration.json \
  --out results/v1/vote_v1_civic_dev60_20261110_sampling_run3/analysis

python scripts/audit_vote_study.py \
  --run results/v1/vote_v1_civic_dev60_20261110_sampling_run3 \
  --plan experiments/vote_v1_civic_dev60_20261109.json \
  --dataset data/civicfact-pmidids \
  --out results/v1/vote_v1_civic_dev60_20261110_sampling_run3/audit.json
```

The calibrator is a pooled Platt curve fitted in standardized logit space with
an L2 penalty of 1.0 by default. Role reliability and calibration losses assign
one unit of total weight to each source group, so multiple questions from one
article or patient do not become independent calibration observations.

MTB has only eight development patients. Its V1/V2 estimates therefore use
leave-one-patient-out fitting and are exploratory:

```bash
python scripts/analyze_vote_pool.py \
  --run results/v1/vote_v1_mtb_dev43_20261110_sampling_run1 \
  --dataset data/mtbbench \
  --arm p_k_specialists \
  --reference-arm b0_common_single \
  --crossfit-groups \
  --out results/v1/vote_v1_mtb_dev43_20261110_sampling_run1/analysis_crossfit
```

For V3, use only low-consensus cases after V0 has been measured:

```bash
python scripts/run_vote_arbitration.py \
  --run results/v1/vote_v1_civic_dev60_20261110_sampling_run3 \
  --dataset data/civicfact-pmidids \
  --allow-remote --execution-cap 1000 \
  --out results/v1/vote_v1_civic_dev60_20261110_sampling_run3/v3
```

The V3 output copies every unchanged high-consensus V0 case and calls the
arbiter only for the predeclared low-consensus cases. This keeps the V3
evaluation denominator equal to the full case set.

## Output contract

Each `Ballot` records:

- server-assigned `ballot_id` and `case_id`
- applicable role
- model, seed, input fingerprint and usage
- `vote`, `abstain` or `failed`
- label, uncalibrated confidence and concise reason
- local findings and exact resolved citations

`VoteResult` records:

- V0 counts and all requested aggregation scores
- raw-confidence diagnostic scores
- calibrated-confidence scores when a calibrator is supplied
- valid/abstain/failed counts and full/degraded/failed completion
- tie and deterministic tie-break status
- optional one-shot arbitration state

The final label is fixed before explanation. A non-NEI vote requires visible
evidence. A missing local modality does not become a global NEI vote.

## Development result

The final development runs are:

- CIViC: `results/v1/vote_v1_civic_dev60_20261110_sampling_run3/`
- MTB: `results/v1/vote_v1_mtb_dev43_20261110_sampling_run1/`
- CIViC calibration:
  `results/v1/vote_v1_civic_calibration_20261110_sampling_run2/`

CIViC dev60 Accuracy: B0 `0.8333`, G-K `0.8833`, P-K `0.8333`.
MTB dev43 Accuracy: B0 `0.4419`, G-K `0.5116`, P-K `0.5814`.
The GT/specialist signal is task-dependent; the complete tables, failure
denominators, calibration and V3 results are in
[VOTE_V1_RESULTS](VOTE_V1_RESULTS_20261110.md).

The CIViC confirmation set and the reserved final test were not run because
the professional route did not beat the controls. The historical 150-case/
71-article CIViC set remains a used diagnostic set, not an independent test.
