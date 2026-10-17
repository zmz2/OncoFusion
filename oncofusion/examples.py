"""Small explicitly fictional fixtures. Gold labels are created separately by the evaluator."""
from .schemas import CaseInput, Document, Entities


def examples() -> dict[str, CaseInput]:
    entity = Entities(gene="GENE1", variant="p.Val600Glu", disease="Tumor-A", drug="Compound-A")
    base = CaseInput(id="synthetic-support", patient_id="synthetic-p1", task="verification",
                     question="GENE1 V600E in Tumor-A is sensitive to Compound-A.",
                     entities=entity, data_class="synthetic", stage=1,
                     documents=[
                         Document(id="path", origin_id="synthetic-path", kind="pathology",
                                  text="Fictional specimen: Tumor-A. This record is synthetic.",
                                  entities=Entities(disease="Tumor-A")),
                         Document(id="gene", origin_id="synthetic-gene", kind="genomics",
                                  text="Fictional sequencing detected GENE1 p.Val600Glu.",
                                  entities=Entities(gene="GENE1", variant="p.Val600Glu")),
                         Document(id="paper1", origin_id="synthetic-paper1", kind="literature",
                                  text="Synthetic experiment: GENE1 V600E in Tumor-A was sensitive to Compound-A.",
                                  entities=entity.model_copy(update={"variant": "V600E"}), license="Synthetic fixture"),
                         Document(id="future", origin_id="synthetic-future", kind="clinical",
                                  text="FUTURE_CANARY: later progression was observed.", available_stage=2, event_day=90),
                     ])
    refute = base.model_copy(deep=True)
    refute.id, refute.patient_id = "synthetic-refute", "synthetic-p2"
    refute.documents[2].text = "Synthetic experiment: GENE1 V600E in Tumor-A was resistant to Compound-A."
    nei = base.model_copy(deep=True)
    nei.id, nei.patient_id = "synthetic-nei", "synthetic-p3"
    nei.documents = [Document(id="unrelated", origin_id="synthetic-unrelated", kind="literature",
                              text="Unrelated synthetic experiment describes cell morphology in Tumor-B.",
                              entities=Entities(disease="Tumor-B"))]
    timeline = CaseInput(id="synthetic-timeline", patient_id="synthetic-p4", task="mcq", stage=1,
                         as_of_day=30, question="Which response is the most recent visible assessment?",
                         options={"A": "partial response", "B": "stable disease", "C": "progressive disease"},
                         data_class="synthetic", documents=[
                             Document(id="old", origin_id="synthetic-visit0", kind="clinical",
                                      text="At day 0 the assessment was stable disease.", event_day=0),
                             Document(id="current", origin_id="synthetic-visit1", kind="clinical",
                                      text="At day 30 the assessment was partial response.", event_day=30, available_stage=1),
                             Document(id="later", origin_id="synthetic-visit2", kind="clinical",
                                      text="FUTURE_CANARY: progressive disease at day 60.", event_day=60, available_stage=2),
                         ])
    return {x.id: x for x in (base, refute, nei, timeline)}
