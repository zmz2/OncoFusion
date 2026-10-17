"""Conservative first-release scope, runnable configuration and input-coverage audit.

Coverage describes visible inputs, never proves an agent improves the answer.
No gold labels, model calls or external requests enter this module.
"""
from collections import Counter
from importlib.util import find_spec

from .evidence import deduplicate_documents, visible_case
from .schemas import Ablations, CaseInput, Document, Entities, ROLES, RunConfig


def v1_config(backend: str = 'langgraph') -> RunConfig:
    return RunConfig(workflow_backend=backend, evidence_first=True,
                     specialist_contracts=True, latest_role_board=True,
                     routing='fixed', ablations=Ablations(targeted_requery=False))


def inspect_case(case: CaseInput) -> dict:
    visible = visible_case(case)
    docs = visible.documents
    kinds = Counter(d.kind for d in docs)
    entities = [visible.entities] + [d.entities for d in docs]
    present = lambda field: any(getattr(e, field).strip() for e in entities)
    role_inputs = {
        'timeline': bool(kinds['clinical'] or any(d.event_day is not None for d in docs)),
        'genomics': bool(kinds['genomics'] or present('gene') or present('variant')),
        'pathology': bool(kinds['pathology'] or present('disease')),
        'drug': bool(kinds['therapy'] or present('drug')),
        'literature': bool(kinds['literature']),
        'verifier': bool(docs),
        'decision': bool(docs),
    }
    unique_literature = deduplicate_documents([d for d in docs if d.kind == 'literature'])
    warnings = []
    if len(kinds) < 2:
        warnings.append('Single document modality: use as component evaluation, not proof of multimodal integration.')
    if len(unique_literature) < 2:
        warnings.append('Fewer than two distinct literature candidates: reranking benefit is not measurable here.')
    if not docs:
        warnings.append('No visible source evidence; an evidence-based substantive answer may be unavailable.')
    if case.data_class == 'unreviewed':
        warnings.append('Review/deidentify the input before remote model processing.')
    missing = [r for r in ROLES if not role_inputs[r]]
    return {'case_id': case.id, 'task': case.task,
            'visible_document_count': len(docs), 'visible_document_kinds': dict(kinds),
            'distinct_literature_candidates': len(unique_literature),
            'explicit_role_inputs': role_inputs, 'roles_without_explicit_inputs': missing,
            'heterogeneous_document_input': len(kinds) >= 2,
            'source_bytes': sum(len(d.text.encode()) for d in docs),
            'warnings': warnings,
            'interpretation': 'Structural input coverage only. Narrative facts may still be relevant; no automatic role skipping or efficacy inference.'}


def coverage_report(cases: list[CaseInput]) -> dict:
    rows = [inspect_case(c) for c in cases]
    return {'cases': len(rows), 'patient_or_article_groups': len({c.patient_id for c in cases}),
            'heterogeneous_input_cases': sum(r['heterogeneous_document_input'] for r in rows),
            'multi_candidate_retrieval_cases': sum(r['distinct_literature_candidates'] >= 2 for r in rows),
            'explicit_role_input_cases': {role: sum(r['explicit_role_inputs'][role] for r in rows) for role in ROLES},
            'interpretation': 'Counts are structural eligibility signals, not agent-importance labels. Report task-appropriate subsets and independent retrieval results.'}


def profile_catalog() -> dict:
    return {'v1': {
        'title': 'OncoFusion: multi-agent integration and traceable reasoning over oncology evidence',
        'architecture': 'LangGraph fixed specialist workflow with shared evidence, verifier and coordinator',
        'config': v1_config().model_dump(), 'graph_installed': find_spec('langgraph') is not None,
        'llm_protocol': 'same provider/model for all roles; shared budget and exact source citations',
        'primary_task': 'MTBBench stage-visible text MCQ; integration of available clinical, molecular and specimen data',
        'component_tasks': ['CIViC-Fact native claim verification', 'CIViC-Fact article-local passage retrieval'],
        'scope': 'Evidence integration research. Drug relationships are evidence-qualified; these datasets do not label optimal patient therapy.',
        'runtime_reuse': ['LangGraph StateGraph', 'optional ToolUniverse read-only SDK'],
        'source_policy': 'Closed corpus for benchmarks. Reviewed public-source snapshots only for contemporary custom synthesis.',
        'first_release': {'parallel': False, 'automatic_live_tools': False, 'requery_rounds': 0,
                          'durable_graph_resume': False, 'multi_user_authorization': False},
        'start_plan': 'experiments/v1_mtb_smoke.json',
    }}


def integration_example() -> CaseInput:
    """A fictional heterogeneity fixture; it carries no biomedical benchmark gold."""
    entity = Entities(gene='GENE1', variant='V600E', disease='Tumor-A', drug='Compound-A')
    return CaseInput(id='synthetic-integration', patient_id='synthetic-research-p1',
        task='synthesis', data_class='synthetic', entities=entity,
        question='Integrate the observed variant, specimen context, pathway membership and drug evidence. State which links are supported and what remains unknown.',
        documents=[
            Document(id='clinical', origin_id='fictional-clinical', kind='clinical', event_day=0,
                     text='FICTIONAL CASE. At day 0, a specimen was collected before exposure to Compound-A.'),
            Document(id='specimen', origin_id='fictional-specimen', kind='pathology',
                     text='FICTIONAL CASE. Histology: Tumor-A. Sampled site: primary lesion.', entities=Entities(disease='Tumor-A')),
            Document(id='molecular', origin_id='fictional-sequencing', kind='genomics',
                     text='FICTIONAL ASSAY. Sequencing detected GENE1 p.Val600Glu. Pathway activity was not measured.', entities=entity),
            Document(id='pathway', origin_id='fictional-pathway-db', kind='genomics',
                     text='FICTIONAL DATABASE RECORD. GENE1 is a member of Pathway-X; membership alone does not establish variant function.'),
            Document(id='drug', origin_id='fictional-drug-db', kind='therapy',
                     text='FICTIONAL DATABASE RECORD. Compound-A targets the GENE1 protein. This record reports no patient outcome.'),
            Document(id='supporting-study', origin_id='fictional-study-1', kind='literature',
                     text='FICTIONAL STUDY. Tumor-A cells carrying GENE1 V600E were sensitive to Compound-A in a cell assay. Clinical effectiveness was not evaluated.'),
            Document(id='other-study', origin_id='fictional-study-2', kind='literature',
                     text='FICTIONAL STUDY. Tumor-B cells with GENE1 wild type showed no response to Compound-A. This is a different molecular and disease setting.'),
        ])
