"""Retain public abstract IDs without inventing a source URL."""
import pytest
from oncofusion.datasets import civic_article_reference

@pytest.mark.parametrize('value',['ASCO:147167','ASCO:160289'])
def test_asco_abstract_identity_has_no_fabricated_pubmed_url(value):
    origin, group, url = civic_article_reference(value)
    assert origin == 'source-' + value
    assert group == 'article-' + value
    assert url == ''
