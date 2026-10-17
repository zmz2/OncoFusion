"""Native structural form confirmed in civicfact data_builder/src/nli/util.py."""
import json
import pytest

from oncofusion.datasets import import_civicfact, original_claim_fields


def test_native_claim_discriminator_preserves_original_combination():
    row = {"id": "native", "document.pmid": 123, "partition": "dev",
           "gold_label_name": "REVISIONS", "claim.flat": "Original claim",
           "evidence.flat": "Visible evidence", "claim": {
               "type": "claim", "content": {"molecularProfile": "GENE1 V1A",
                   "disease": "Cancer-X", "evidenceType": "PREDICTIVE",
                   "therapies": ["Compound-A", "Compound-B"], "significance": "response"}},
           "revised_claim": {"type": "claim", "content": {"therapies": ["HIDDEN_REVISION"]}},
           "reviews": ["HIDDEN_REVIEW"]}
    cases, gold = import_civicfact([row], verification_scheme="revisions")
    assert cases[0].claim_fields.disease == "Cancer-X"
    assert json.loads(cases[0].claim_fields.therapies) == ["Compound-A", "Compound-B"]
    assert gold[0].label == "REVISIONS"
    assert "HIDDEN" not in cases[0].model_dump_json()
    row["gold_label_name"] = "NEI"
    assert import_civicfact([row], verification_scheme="revisions")[0] == cases


def test_native_therapy_member_schema_is_checked():
    with pytest.raises(ValueError, match="therapies"):
        original_claim_fields({"claim": {"type": "claim", "content": {"therapies": [12]}}})
