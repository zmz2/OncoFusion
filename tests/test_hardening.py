"""Independent regression cases for evidence handoff and exact ablation scope."""
import copy
import json

from oncofusion.engine import Engine, run_fingerprint
from oncofusion.providers import MockProvider, OpenAICompatibleProvider
from oncofusion.schemas import AnalysisOutput, CaseInput, Document, Entities, RunConfig


class Recorder(MockProvider):
    def __init__(self):
        super().__init__()
        self.payloads = []

    def complete(self, system, payload, max_tokens, temperature, seed):
        self.payloads.append(copy.deepcopy(payload))
        return super().complete(system, payload, max_tokens, temperature, seed)


def test_verifier_unresolved_reaches_decision():
    class Concern(Recorder):
        def complete(self, system, payload, max_tokens, temperature, seed):
            reply = super().complete(system, payload, max_tokens, temperature, seed)
            if payload['role'] == 'verifier':
                reply.content = AnalysisOutput(unresolved=['Cancer subtype applicability remains unresolved.']).model_dump_json()
            return reply

    provider = Concern()
    case = CaseInput(id='handoff', patient_id='p1', task='verification', question='Drug sensitivity?', documents=[])
    Engine(provider).run(case)
    assert provider.payloads[-1]['unresolved'] == [
        {'role': 'timeline', 'items': ['No matching evidence in the provided source view.']},
        {'role': 'genomics', 'items': ['No matching evidence in the provided source view.']},
        {'role': 'pathology', 'items': ['No matching evidence in the provided source view.']},
        {'role': 'drug', 'items': ['No matching evidence in the provided source view.']},
        {'role': 'literature', 'items': ['No matching evidence in the provided source view.']},
        {'role': 'verifier', 'items': ['Cancer subtype applicability remains unresolved.']},
    ]


def ranked_for(config, entity_field, query_value, first_value, second_value):
    query = Entities(**{entity_field: query_value})
    docs = [Document(id=key, origin_id=key, kind='literature', text='Evidence about treatment response.',
                     entities=Entities(**{entity_field: value}))
            for key, value in [('a', first_value), ('z', second_value)]]
    case = CaseInput(id='ranking', patient_id='p1', task='verification', question='Treatment response',
                     entities=query, documents=docs)
    result = Engine(MockProvider()).run(case, config)
    return next(e.details['ranked_ids'] for e in result.trace if e.kind == 'retrieval_completed')


def test_variant_ablation_reaches_retrieval():
    config = RunConfig(top_k=1)
    assert ranked_for(config, 'variant', 'V600E', 'p.Val600Glu', 'V600E') == ['a']
    config.ablations.variant_normalization = False
    assert ranked_for(config, 'variant', 'V600E', 'p.Val600Glu', 'V600E') == ['z']


def test_disease_ablation_reaches_retrieval():
    config = RunConfig(top_k=1)
    assert ranked_for(config, 'disease', 'melanoma', 'leukemia', 'melanoma') == ['z']
    config.ablations.disease_matching = False
    assert ranked_for(config, 'disease', 'melanoma', 'leukemia', 'melanoma') == ['a']


def test_retry_policy_changes_run_identity():
    case = CaseInput(id='identity', patient_id='p', task='verification', question='Evidence?')
    first = OpenAICompatibleProvider('https://example.org/v1', 'test', 'not-a-real-key', retries=0)
    second = OpenAICompatibleProvider('https://example.org/v1', 'test', 'not-a-real-key', retries=2)
    assert run_fingerprint(case, RunConfig(), first) != run_fingerprint(case, RunConfig(), second)

import pytest
from oncofusion.datasets import GoldRecord, import_civicfact, import_mtbbench
from oncofusion.evaluation import evaluate
from oncofusion.preparation import prepare_mtb, prepare_civic
from oncofusion.providers import ProviderError
from oncofusion.retrieval_benchmark import import_retrieval, prepare_retrieval
from oncofusion.schemas import Finding


def civic_record(label='REVISIONS'):
    return {'id': '1', 'document.pmid': '123', 'gold_label_name': label, 'partition': 'dev',
            'claim.flat': 'GENE1 response to Compound-A', 'evidence.flat': 'Evidence concerns a different molecular profile.',
            'revised_claim.flat': 'PRIVATE_GOLD_REVISION', 'reviews': ['PRIVATE_REVIEW'],
            'civic.description': 'PRIVATE_CURATION'}


@pytest.mark.parametrize('label', ['SUPPORTS', 'REVISIONS', 'NEI'])
def test_native_revision_vocabulary_preserved(label):
    cases, gold = import_civicfact([civic_record(label)], verification_scheme='revisions')
    assert gold[0].label == label
    assert cases[0].verification_labels == ('SUPPORTS', 'REVISIONS', 'NEI')
    assert 'PRIVATE_' not in cases[0].model_dump_json()
    p = Recorder()
    result = Engine(p).run(cases[0])
    assert result.decision.answer in cases[0].verification_labels
    assert all('PRIVATE_' not in json.dumps(payload) for payload in p.payloads)
    assert all(payload['verification_labels'] == list(cases[0].verification_labels) for payload in p.payloads)


def test_labels_do_not_change_inference_payload():
    first, _ = import_civicfact([civic_record('SUPPORTS')], verification_scheme='revisions')
    second, _ = import_civicfact([civic_record('NEI')], verification_scheme='revisions')
    assert first == second


def test_revision_label_rejected_by_legacy_scheme():
    with pytest.raises(ValueError, match='unsupported'):
        import_civicfact([civic_record()])
    with pytest.raises(ValueError, match='remapping'):
        import_civicfact([civic_record()], 'REVISIONS')


@pytest.mark.parametrize('mode', ['multi', 'fixed_five', 'single_tools', 'single_direct', 'single_iterative'])
def test_revision_mode_evaluation(mode):
    cases, gold = import_civicfact([civic_record()], verification_scheme='revisions')
    report = evaluate(cases, gold, Engine(MockProvider()), RunConfig(mode=mode))
    assert set(report['metrics']['per_class']) == {'SUPPORTS', 'REVISIONS', 'NEI'}
    assert report['verification_scheme'] == 'revisions'
    assert report['failed_or_incomplete'] == 0


def test_mixed_label_ontologies_fail_before_model():
    c = CaseInput(id='a', patient_id='p', task='verification', question='Evidence?')
    d = c.model_copy(update={'id': 'b', 'verification_scheme': 'revisions'})
    p = Recorder()
    with pytest.raises(ValueError, match='vocabulary'):
        evaluate([c, d], [GoldRecord(case_id=x.id, group_id='p', label='NEI') for x in [c, d]], Engine(p), RunConfig())
    assert p.payloads == []


def test_wrong_gold_label_fails_before_model():
    c = CaseInput(id='a', patient_id='p', task='verification', question='Evidence?')
    p = Recorder()
    with pytest.raises(ValueError, match='vocabulary'):
        evaluate([c], [GoldRecord(case_id='a', group_id='p', label='REVISIONS')], Engine(p), RunConfig())
    assert p.payloads == []


@pytest.mark.parametrize('empty', ['', ' ', '\n\t'])
def test_mtb_empty_sources_are_omitted_without_false_biological_claim(tmp_path, empty):
    (tmp_path / 'mutation.txt').write_text(empty)
    records = {'P1': [{'context': ''}, {'file_paths': ['/original/P1/mutation.txt']},
                      {'question': 'Event?\nA) present\nB) absent', 'answer': 'A'}]}
    cases, gold = import_mtbbench(records, tmp_path, {'/original/P1/mutation.txt': 'mutation.txt'})
    assert cases[0].documents == []
    assert gold[0].label == 'A'
    assert 'no mutations' not in cases[0].model_dump_json()


def test_mtb_empty_sources_audited(tmp_path):
    (tmp_path / 'mutation.txt').write_text('')
    entry = [{'file_paths': ['/original/P/mutation.txt']}, {'question': 'Event?\nA) yes\nB) no', 'answer': 'A'}]
    source = tmp_path / 'questions.json'
    source.write_text(json.dumps({'P1': entry, 'P2': entry}))
    audit = prepare_mtb(source, tmp_path, tmp_path / 'out', {'/original/P/mutation.txt': 'mutation.txt'})
    assert audit['empty_source_files'] == ['mutation.txt']
    assert audit['cases'] == 2


def retrieval_fixture():
    chunks = [{'chunk.start': 0, 'chunk.end': 15, 'chunk.text': 'Source content.', 'chunk.id': '1',
               'document.pmid': '123', 'partition': 'dev'}]
    row = {'document.pmid': '123', 'claim.flat': 'Original query', 'gold_label_name': 'SUPPORTS',
           'evidence': [{'meta': {'start': 0, 'end': 6}}]}
    return row, chunks


@pytest.mark.parametrize('labels', [('SUPPORTS', 'NEI'), ('NEI', 'SUPPORTS'), ('SUPPORTS', 'REVISIONS')])
def test_retrieval_conflicts_excluded_as_whole_groups(labels):
    row, chunks = retrieval_fixture()
    queries = [{**row, 'gold_label_name': label} for label in labels]
    queries.append({**row, 'claim.flat': 'Separate valid query'})
    cases, gold, audit = import_retrieval(queries, chunks, exclude_conflicts=True)
    assert len(cases) == len(gold) == 1
    assert cases[0].question == 'Separate valid query'
    assert audit['conflicting_query_groups'] == 1
    assert len(audit['excluded']) == 1


def test_conflict_exclusions_require_review(tmp_path):
    row, chunks = retrieval_fixture()
    queries = [row, {**row, 'gold_label_name': 'NEI'}, {**row, 'claim.flat': 'Valid query'}]
    with pytest.raises(ValueError, match='excluded'):
        prepare_retrieval(queries, chunks, tmp_path)
    assert (tmp_path / 'retrieval_audit.json').exists()
    report = prepare_retrieval(queries, chunks, tmp_path, allow_exclusions=True)
    assert report['manifest']['count'] == 1


def test_resolved_concerns_not_reintroduced_after_requery():
    class Resolves(Recorder):
        def __init__(self):
            super().__init__()
            self.verifications = 0
        def complete(self, system, payload, max_tokens, temperature, seed):
            reply = super().complete(system, payload, max_tokens, temperature, seed)
            if payload['role'] == 'verifier':
                self.verifications += 1
                output = AnalysisOutput(unresolved=['Needs additional context.'], requery='context') if self.verifications == 1 else AnalysisOutput()
                reply.content = output.model_dump_json()
            return reply
    p = Resolves()
    Engine(p).run(CaseInput(id='q', patient_id='p', task='verification', question='Evidence?'))
    assert p.verifications == 2
    assert not any(row['role'] == 'verifier' for row in p.payloads[-1]['unresolved'])


@pytest.mark.parametrize('structured', [True, False])
def test_unresolved_evidence_same_information_in_both_board_formats(structured):
    p = Recorder()
    config = RunConfig()
    config.ablations.structured_board = structured
    Engine(p).run(CaseInput(id='q', patient_id='p', task='verification', question='Evidence?'), config)
    issues = p.payloads[-1]['unresolved']
    if not structured:
        issues = json.loads(issues)
    assert {row['role'] for row in issues} == {'timeline', 'genomics', 'pathology', 'drug', 'literature', 'verifier'}


def test_civic_real_null_metadata_stays_unknown(tmp_path):
    row = civic_record('SUPPORTS')
    row.update({'document.title': None, 'document.license': None})
    cases, gold = import_civicfact([row], verification_scheme='revisions')
    assert cases[0].documents[0].title == ''
    assert cases[0].documents[0].license == ''
    source = tmp_path/'source.jsonl'
    source.write_text(json.dumps(row)+'\n')
    audit = prepare_civic(source, tmp_path/'out')
    assert audit['missing_title_records'] == 1 and audit['missing_license_records'] == 1
