"""Optional real medspaCy ConText component; no model download, GPU or remote calls.

English rule-based mention attributes, not a clinical diagnosis. Original text and
character offsets are preserved. Construct one isolated pipeline per case.
"""
from __future__ import annotations

from importlib.metadata import version

from .schemas import Document, Entities

MEDSPACY_VERSION = "1.3.1"
# Targets are mention locations, never assertions of disease presence or drug benefit.
EVENT_TERMS = ("progression", "recurrence", "metastasis", "response", "resistance")


def assertions(documents: list[Document], entities: Entities) -> list[dict]:
    if version("medspacy") != MEDSPACY_VERSION:
        raise RuntimeError("clinical context requires the reviewed medspacy==1.3.1")
    import medspacy
    from medspacy.ner import TargetRule

    nlp = medspacy.load(medspacy_enable={"medspacy_pyrush", "medspacy_target_matcher", "medspacy_context"})
    terms = {term: "EVENT" for term in EVENT_TERMS}
    terms.update({value: name.upper() for name, value in entities.model_dump().items() if value})
    nlp.get_pipe("medspacy_target_matcher").add([TargetRule(term, label) for term, label in sorted(terms.items())])
    rows = []
    for source in documents:
        if source.kind not in {"clinical", "pathology", "therapy"}:
            continue
        doc = nlp(source.text)
        for span in doc.ents:
            rows.append({"document_id": source.id, "start": span.start_char, "end": span.end_char,
                         "text": source.text[span.start_char:span.end_char], "label": span.label_,
                         "negated": span._.is_negated, "uncertain": span._.is_uncertain,
                         "historical": span._.is_historical, "hypothetical": span._.is_hypothetical,
                         "family": span._.is_family, "method": "medspacy-context-en"})
            if len(rows) >= 200:
                return rows
    return rows
