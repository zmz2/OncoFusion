"""Task fit, information routing and synthesis contracts; deterministic model doubles."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oncofusion.api import create_app
from oncofusion.config import research_v1_config
from oncofusion.datasets import import_civicfact
from oncofusion.engine import Engine
from oncofusion.examples import examples
from oncofusion.experiments import StudyPlan
from oncofusion.providers import MockProvider, ProviderError
from oncofusion.schemas import (AnalysisOutput, CaseInput, ClaimFields, DecisionOutput,
                               Document, EvidenceSection, RunConfig)
from oncofusion.specialists import MODULES, coverage, scoped_signals


class Recorder(MockProvider):
    def __init__(self):
        super().__init__(); self.payloads=[]; self.systems=[]
    def complete(self, system, payload, *args):
        self.payloads.append(copy.deepcopy(payload)); self.systems.append(system)
        return super().complete(system,payload,*args)


def scoped(**kwargs):
    return RunConfig(task_scoped=True,evidence_first=True,specialist_contracts=True,latest_role_board=True,**kwargs)


def test_original_claim_fields_whitelist_and_gold_isolation():
    row={"id":"1","document.pmid":123,"partition":"dev","gold_label_name":"SUPPORTS",
         "claim.flat":"Original claim", "evidence.flat":"Public excerpt", "claim":[{"type":"table",
          "content":[["molecularProfile","GENE1 V1A"],["therapies","Compound-A"],["diseases","Cancer-X"],
                     ["gold_label_name","GOLD_SENTINEL"]], "meta":{"revised_claim":"GOLD_SENTINEL"}}],
          "revised_claim.flat":"GOLD_SENTINEL"}
    cases,_=import_civicfact([row]); case=cases[0]
    assert case.claim_fields.therapies=="Compound-A"
    assert "GOLD_SENTINEL" not in case.model_dump_json()
    row["gold_label_name"]="NEI"
    assert import_civicfact([row])[0]==cases


def test_claim_dimensions_control_applicability():
    case=CaseInput(id="x",patient_id="x",task="verification",question="Claim",
                   claim_fields=ClaimFields(molecular_profile="GENE1 V1A",disease="Cancer-X"),
                   documents=[Document(id="lit",origin_id="paper",kind="literature",text="Public evidence.")])
    provider=Recorder(); result=Engine(provider).run(case,scoped())
    active=[r["role"] for r in provider.payloads]
    assert active==["literature","genomics","pathology","verifier","decision"]
    assert coverage(case)["heterogeneous_input"] is False
    skipped={e.role for e in result.trace if e.kind=="agent_skipped"}
    assert skipped=={"timeline","drug"}


def test_drug_receives_clinical_treatment_history_even_in_adaptive_mode():
    case=CaseInput(id="x",patient_id="p",task="mcq",question="Outcome?",options={"A":"response","B":"progression"},
                   documents=[Document(id="note",origin_id="note",kind="clinical",text="After Compound-A treatment progression occurred.")])
    p=Recorder(); Engine(p).run(case,scoped(routing="adaptive"))
    drug=next(r for r in p.payloads if r["role"]=="drug")
    assert drug["sources"][0]["id"]=="note"


def test_no_extra_requery_without_unseen_literature():
    class Requests(Recorder):
        def complete(self,system,payload,*args):
            reply=super().complete(system,payload,*args)
            if payload["role"]=="verifier":
                reply.content=AnalysisOutput(requery="Search again",unresolved=["Missing evidence"]).model_dump_json()
            return reply
    p=Requests(); result=Engine(p).run(examples()["synthetic-support"],scoped())
    assert sum(e.kind=="requery_requested" for e in result.trace)==0


def test_role_delegation_preserves_source_access():
    c=examples()["synthetic-support"]
    a,b=Recorder(),Recorder()
    Engine(a).run(c,scoped())
    Engine(b).run(c,scoped(delegated_roles=["genomics"]))
    assert [(v["role"],v["sources"]) for v in a.payloads]==[(v["role"],v["sources"]) for v in b.payloads]


def test_unavailable_modality_does_not_become_false_negative():
    case=CaseInput(id="x",patient_id="p",task="mcq",question="Outcome?",options={"A":"response","B":"progression"})
    p=Recorder(); result=Engine(p).run(case,scoped())
    assert "genomics" not in [r["role"] for r in p.payloads]
    assert result.decision is not None
    assert coverage(case)["document_kinds"]=={}


def test_future_sources_cannot_change_scope_or_routing():
    c=examples()["synthetic-support"].model_copy(deep=True)
    before=coverage(c)
    c.documents.append(Document(id="future",origin_id="future",kind="genomics",text="FUTURE_SENTINEL",available_stage=c.stage+10))
    assert coverage(c)==before
    p=Recorder();Engine(p).run(c,scoped())
    assert "FUTURE_SENTINEL" not in json.dumps(p.payloads)


def test_scope_filters_signal_side_channels():
    docs=[Document(id="a",origin_id="a",kind="pathology",text="Public")]
    result=scoped_signals({"matches":{"a":{},"secret":{}},"timeline":[{"id":"secret","text":"hidden"}],
                           "clinical_assertions":[{"document_id":"secret","text":"hidden"}]},docs)
    assert "secret" not in json.dumps(result) and "hidden" not in json.dumps(result)


def test_pathology_has_separate_raw_source_view():
    docs=[Document(id=k,origin_id=k,kind=k,text=k) for k in ["clinical","pathology","genomics","therapy","literature"]]
    assert {d.id for d in MODULES["pathology"].sources(docs)}=={"clinical","pathology","literature"}


def test_revision_definitions_reach_all_roles():
    c=examples()["synthetic-support"].model_copy(update={"verification_scheme":"revisions"})
    p=Recorder();Engine(p).run(c,scoped())
    assert all("partial support with a necessary claim correction" in s for s in p.systems)


def test_supported_synthesis_section_requires_source():
    with pytest.raises(ValueError,match="citations"):
        EvidenceSection(status="supported",statement="Drug benefit")


def test_v1_synthesis_contains_all_evidence_links_and_marks_simulation():
    c=examples()["synthetic-support"].model_copy(update={"task":"synthesis"})
    result=Engine(MockProvider()).run(c,scoped())
    assert result.simulated is True
    assert set(result.decision.integration.model_dump())=={"molecular","pathology_context","pathway","drug","literature"}
    assert all(v["status"]=="insufficient_evidence" for v in result.decision.integration.model_dump().values())


def test_v1_synthesis_missing_links_rejected():
    class Missing(MockProvider):
        def complete(self,system,payload,*args):
            reply=super().complete(system,payload,*args)
            if payload["role"]=="decision":
                value=json.loads(reply.content);value["integration"]=None;reply.content=json.dumps(value)
            return reply
    c=examples()["synthetic-support"].model_copy(update={"task":"synthesis"})
    with pytest.raises(ProviderError,match="validation"):
        Engine(Missing()).run(c,scoped())


def test_unreviewed_remote_upload_requires_explicit_review(tmp_path):
    provider=MockProvider(simulated=False)
    c=examples()["synthetic-support"].model_copy(update={"data_class":"unreviewed"})
    with TestClient(create_app(tmp_path/"db",provider=provider)) as client:
        reply=client.post("/v1/runs",json={"case":c.model_dump(),"allow_remote_processing":True})
        assert reply.status_code==422
        assert client.get("/v1/runs").json()==[]


@pytest.mark.parametrize("path",sorted(Path("experiments").glob("v1_*_*.json")))
def test_v1_plans_load_and_share_input_policies(path):
    plan=StudyPlan.model_validate_json(path.read_text())
    configs=[t.config(0) for t in plan.treatments]
    assert all(c.task_scoped for c in configs)
    assert len({(c.max_total_tokens,c.max_calls,c.max_output_tokens,c.schema_retries) for c in configs})==1
    if "pilot" in path.name:
        assert len(plan.treatments)==4 and plan.seeds==[0] and plan.group_limit==2


def test_v1_profile_requires_real_graph_and_optional_clinical_module():
    c=research_v1_config()
    assert c.workflow_backend=="langgraph" and c.task_scoped and c.clinical_context

@pytest.mark.parametrize('case',list(examples().values()), ids=lambda c:c.id)
@pytest.mark.parametrize('mode',['multi','single_iterative'])
def test_v1_real_graph_parity(case,mode):
    pytest.importorskip('langgraph.graph')
    native=Engine(MockProvider()).run(case,scoped(mode=mode))
    graph=Engine(MockProvider()).run(case,scoped(mode=mode,workflow_backend='langgraph'))
    assert native.decision==graph.decision
    assert native.reports==graph.reports
    assert native.usage==graph.usage


def test_api_missing_selected_dependency_fails_before_queuing(tmp_path,monkeypatch):
    def missing(config):
        raise RuntimeError('dependency missing')
    monkeypatch.setattr('oncofusion.api.dependency_identity',missing)
    with TestClient(create_app(tmp_path/'db',provider=MockProvider())) as client:
        reply=client.post('/v1/runs',json={'example_id':'synthetic-support'})
        assert reply.status_code==503
        assert client.get('/v1/runs').json()==[]


@pytest.mark.parametrize("therapies", [["Compound-A", "Compound-B"], []])
def test_native_civic_table_dictionary_and_therapy_list(therapies):
    row = {"id": "native", "document.pmid": 123, "partition": "dev", "gold_label_name": "SUPPORTS",
           "claim.flat": "Original combination claim", "evidence.flat": "Public evidence",
           "claim": {"type": "table", "content": {
               "molecularProfile": "GENE1 V1A", "disease": "Cancer-X", "therapies": therapies,
               "evidenceType": "PREDICTIVE", "significance": "response", "reviews": "GOLD_SENTINEL"},
               "meta": {"gold_label_name": "GOLD_SENTINEL"}},
           "revised_claim": {"content": {"therapies": ["GOLD_SENTINEL"]}}}
    case = import_civicfact([row])[0][0]
    assert case.claim_fields.disease == "Cancer-X"
    assert case.claim_fields.therapies == (json.dumps(therapies) if therapies else "")
    assert "GOLD_SENTINEL" not in case.model_dump_json()
    assert MODULES["drug"].applicability(case)[0] == bool(therapies)


@pytest.mark.parametrize("claim", ["unsupported", [{"type": "unstructured", "content": []}]])
def test_unknown_original_claim_shape_is_explicit_failure(claim):
    from oncofusion.datasets import original_claim_fields
    with pytest.raises(ValueError, match="original claim"):
        original_claim_fields({"claim": claim})


def test_clinical_numeric_abi_is_explicitly_pinned():
    import tomllib
    extras = tomllib.loads(Path("pyproject.toml").read_text())["project"]["optional-dependencies"]
    assert "numpy==1.26.4" in extras["clinical"]
    assert "thinc==8.2.5" in extras["clinical"]
    assert not any("tooluniverse" in item for item in extras["clinical"])
