"""Execute the real medspaCy component in the optional-dependency CI job."""
import pytest
pytest.importorskip("medspacy")
from oncofusion.clinical_context import assertions
from oncofusion.schemas import Document, Entities


@pytest.mark.parametrize("text,target,attribute",[
    ("There is no evidence of progression.","progression","negated"),
    ("Possible recurrence.","recurrence","uncertain"),
    ("Family history of melanoma.","melanoma","family"),
    ("History of melanoma.","melanoma","historical"),
    ("If progression occurs, repeat imaging.","progression","hypothetical"),
])
def test_assertion_attributes_and_exact_offsets(text,target,attribute):
    d=Document(id="note",origin_id="note",kind="clinical",text=text)
    rows=assertions([d],Entities(disease="melanoma"))
    row=next(r for r in rows if r["text"]==target)
    assert row[attribute] is True
    assert text[row["start"]:row["end"]]==target


def test_positive_mention_and_no_cross_case_target_leakage():
    d=Document(id="p",origin_id="p",kind="pathology",text="Melanoma is present.")
    row=assertions([d],Entities(disease="melanoma"))[0]
    assert not any(row[k] for k in ["negated","family","historical","hypothetical","uncertain"])
    assert assertions([d],Entities())==[]


def test_literature_is_not_classified_as_patient_record():
    d=Document(id="paper",origin_id="paper",kind="literature",text="Family history of melanoma.")
    assert assertions([d],Entities(disease="melanoma"))==[]


def test_real_component_enters_engine_and_has_independent_switch():
    from oncofusion.engine import Engine
    from oncofusion.providers import MockProvider
    from oncofusion.schemas import CaseInput, RunConfig
    case=CaseInput(id='x',patient_id='p',task='mcq',question='Observed progression?',
                   options={'A':'yes','B':'no'},data_class='synthetic',
                   documents=[Document(id='note',origin_id='note',kind='clinical',text='No evidence of progression.')])
    active=Engine(MockProvider()).run(case,RunConfig(task_scoped=True,clinical_context=True))
    disabled=Engine(MockProvider()).run(case,RunConfig(task_scoped=True,clinical_context=False))
    assert any(e.details.get('signals',{}).get('clinical_assertions') for e in active.trace)
    assert not any('clinical_assertions' in e.details.get('signals',{}) for e in disabled.trace)
