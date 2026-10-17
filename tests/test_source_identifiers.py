"""Regression: public CIViC uses ASH DOI identifiers in its document.pmid field."""
import pytest
from oncofusion.datasets import import_civicfact, civic_article_reference

@pytest.mark.parametrize('value',[12345,'12345'])
def test_numeric_pubmed_identity_is_compatible(value):
    assert civic_article_reference(value) == (
        'pmid-12345','article-12345','https://pubmed.ncbi.nlm.nih.gov/12345/')

def test_real_ash_identifier_is_stable_and_doi_linked():
    value = 'ASH:10.1182/blood-2021-148205'
    row = {'id':'example','document.pmid':value,'gold_label_name':'SUPPORTS',
           'evidence.flat':'Synthetic evidence for an identifier-format regression.',
           'claim.flat':'Synthetic claim.', 'partition':'dev'}
    cases, gold = import_civicfact([row],verification_scheme='revisions')
    doc = cases[0].documents[0]
    assert doc.url == 'https://doi.org/10.1182/blood-2021-148205'
    assert doc.origin_id.startswith('source-')
    assert '/' not in doc.origin_id
    assert cases[0].patient_id == gold[0].group_id
    same, _ = import_civicfact([dict(row,id='other')],verification_scheme='revisions')
    assert same[0].patient_id == cases[0].patient_id
    assert same[0].documents[0].origin_id == doc.origin_id
    other = civic_article_reference('ASH:10.1182/blood-2021-148206')
    assert other[0] != doc.origin_id

@pytest.mark.parametrize('value',[None,'','unknown','ASH:invalid','https://example.org/file'])
def test_unknown_namespace_requires_explicit_source_review(value):
    with pytest.raises(ValueError,match='unsupported article identifier'):
        civic_article_reference(value)
