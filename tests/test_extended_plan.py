from collections import Counter

import pytest

from oncofusion.datasets import GoldRecord
from oncofusion.experiments import stratified_case_ids
from oncofusion.schemas import CaseInput


def _cases(labels: list[str], groups: list[str]) -> tuple[list[CaseInput], list[GoldRecord]]:
    cases, gold = [], []
    for number, (label, group) in enumerate(zip(labels, groups)):
        case_id = f"case-{number}"
        cases.append(CaseInput(
            id=case_id,
            patient_id=group,
            task="verification",
            question="Does the evidence support the claim?",
            data_class="deidentified",
        ))
        gold.append(GoldRecord(
            case_id=case_id,
            label=label,
            group_id=group,
            split="test",
        ))
    return cases, gold


def test_stratified_case_ids_balances_labels_and_caps_articles():
    labels = ["NEI", "SUPPORTS", "REVISIONS"] * 4
    groups = [f"article-{number}" for number in range(12)]
    cases, gold = _cases(labels, groups)

    selected = stratified_case_ids(
        cases, gold, task="verification", split="test", per_label=2,
        max_per_group=1, sampling_seed=7,
    )

    by_id = {record.case_id: record for record in gold}
    assert selected == stratified_case_ids(
        cases, gold, task="verification", split="test", per_label=2,
        max_per_group=1, sampling_seed=7,
    )
    assert Counter(by_id[case_id].label for case_id in selected) == {
        "NEI": 2, "REVISIONS": 2, "SUPPORTS": 2,
    }
    assert max(Counter(by_id[case_id].group_id for case_id in selected).values()) <= 1


def test_stratified_case_ids_fails_instead_of_returning_a_partial_sample():
    labels = ["NEI", "SUPPORTS", "REVISIONS"] * 2
    groups = ["article-1"] * 6
    cases, gold = _cases(labels, groups)

    with pytest.raises(ValueError, match="group cap"):
        stratified_case_ids(
            cases, gold, task="verification", split="test", per_label=2,
            max_per_group=1, sampling_seed=0,
        )
