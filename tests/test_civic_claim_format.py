"""Regression for the pinned upstream Text(type='claim') export; fixtures are fictional."""
import json

import pytest

from oncofusion.datasets import read_jsonl
from oncofusion.preparation import claim_entities, prepare_civic


def modern_claim(**changes):
    content = {'molecularProfile': 'GENE1 V600E', 'disease': 'Tumor-A',
               'therapies': ['Compound-A'], 'evidenceDirection': 'DOES_NOT_SUPPORT'}
    content.update(changes)
    return {'claim': [{'type': 'claim', 'content': content, 'meta': {}}],
            'revised_claim': [{'type': 'claim', 'content': {'molecularProfile': 'GOLD_CANARY X'}}]}


def test_native_2026_claim_fields_are_not_silently_ignored():
    assert claim_entities(modern_claim()).model_dump() == {
        'gene': 'GENE1', 'variant': 'V600E', 'disease': 'Tumor-A', 'drug': 'Compound-A'}


def test_native_claim_can_be_single_text_object():
    row = modern_claim()
    row['claim'] = row['claim'][0]
    assert claim_entities(row).gene == 'GENE1'


def test_therapy_list_preserves_all_names_without_inventing_a_regimen():
    assert claim_entities(modern_claim(therapies=['Compound-A', 'Compound-B'])).drug == 'Compound-A; Compound-B'


@pytest.mark.parametrize('profile', ['GENE1 V600E AND GENE2 G12C',
                                    'GENE1 V600E OR GENE2 G12C', 'GENE1 V600E; GENE2 G12C'])
def test_composite_profile_is_not_mislabeled_as_one_variant(profile):
    entities = claim_entities(modern_claim(molecularProfile=profile))
    assert entities.gene == entities.variant == ''
    assert entities.disease == 'Tumor-A'


def test_revised_gold_and_metadata_are_not_used_as_claim_entities():
    row = modern_claim()
    row['claim'][0]['meta'] = {'molecularProfile': 'GOLD_CANARY V1'}
    assert 'GOLD_CANARY' not in claim_entities(row).model_dump_json()
    assert claim_entities({'revised_claim': row['revised_claim']}).gene == ''


def test_legacy_table_and_modern_object_give_same_entities():
    legacy = {'claim': [{'type': 'table', 'content': [
        ['molecularProfile', 'GENE1 V600E'], ['diseases', 'Tumor-A'], ['therapies', 'Compound-A']]}]}
    assert claim_entities(legacy) == claim_entities(modern_claim())


def test_import_retains_question_but_keeps_claim_entities_out_of_source(tmp_path):
    row = modern_claim()
    row.update({'id': 'record-1', 'document.pmid': '10001', 'claim.flat': 'FICTIONAL original claim',
                'evidence.flat': 'FICTIONAL source evidence.', 'gold_label_name': 'SUPPORTS', 'partition': 'dev'})
    source = tmp_path/'raw.jsonl'
    source.write_text(json.dumps(row)+'\n')
    audit = prepare_civic(source, tmp_path/'prepared')
    imported = read_jsonl(tmp_path/'prepared/inputs.jsonl')[0]
    assert imported['question'] == row['claim.flat']
    assert imported['entities']['gene'] == 'GENE1'
    assert not any(imported['documents'][0]['entities'].values())
    assert 'GOLD_CANARY' not in json.dumps(imported)
    coverage = audit['role_coverage']
    assert all(coverage['explicit_role_input_cases'][r] == 1 for r in ('genomics','pathology','drug'))
    assert coverage['heterogeneous_input_cases'] == 0
