import csv
import json
import pytest
from oncofusion.engine import Engine
from oncofusion.examples import examples
from oncofusion.datasets import GoldRecord
from oncofusion.experiments import standard_plan, run_study
from oncofusion.providers import MockProvider
from oncofusion.review import export_review, read_review, score_reviews


def write(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['review_id', 'supports'])
        writer.writeheader()
        writer.writerows(rows)


def test_export_blinded_review(tmp_path):
    case = examples()['synthetic-support']
    gold = [GoldRecord(case_id=case.id, group_id=case.patient_id, label='SUPPORTS', split='dev')]
    run_study(standard_plan('verification', smoke=True), [case], gold, Engine(MockProvider()), tmp_path/'study')
    result = export_review(tmp_path/'study', [case], tmp_path/'review', limit=4)
    assert result['count'] == 4
    a, b = tmp_path/'review/reviewer_A.csv', tmp_path/'review/reviewer_B.csv'
    assert a.read_bytes() == b.read_bytes()
    with a.open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    assert 'treatment' not in rows[0]
    assert len(json.loads((tmp_path/'review/_private/blinding_key.json').read_text())) == 4
    export_review(tmp_path/'study', [case], tmp_path/'repeat', limit=4)
    assert a.read_bytes() == (tmp_path/'repeat/reviewer_A.csv').read_bytes()
    with pytest.raises(ValueError):
        read_review(a)
    with pytest.raises(ValueError, match='duplicate'):
        export_review(tmp_path/'study', [case, case], tmp_path/'review')
    for path in (a,b):
        write(path, [{'review_id':row['review_id'], 'supports':'yes'} for row in rows])
    assert score_reviews(a,b)['conservative_agreed_support_fraction'] == 1
    assert score_reviews(a,b)['cohen_kappa'] is None


@pytest.mark.parametrize('limit', [0,5001])
def test_export_limit(limit, tmp_path):
    with pytest.raises(ValueError):
        export_review(tmp_path, [], tmp_path/'out', limit)


def test_disagreement_and_uncertainty(tmp_path):
    a,b = tmp_path/'a.csv',tmp_path/'b.csv'
    write(a, [{'review_id':str(i),'supports':v} for i,v in enumerate(['yes','no','unclear'])])
    write(b, [{'review_id':str(i),'supports':v} for i,v in enumerate(['yes','yes','unclear'])])
    result = score_reviews(a,b)
    assert result['agreement'] == 2/3
    assert result['requires_adjudication'] == ['1','2']
    assert result['cohen_kappa'] == pytest.approx(.5)
    write(b,[{'review_id':'different','supports':'no'}])
    with pytest.raises(ValueError):
        score_reviews(a,b)


@pytest.mark.parametrize('rows', [[],[{'review_id':'x','supports':'maybe'}],[{'review_id':'','supports':'yes'}],
                                  [{'review_id':'x','supports':'yes'},{'review_id':'x','supports':'yes'}]])
def test_invalid_review(rows,tmp_path):
    p = tmp_path/'review.csv';write(p,rows)
    with pytest.raises(ValueError):
        read_review(p)
