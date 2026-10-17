"""Upstream manual-review samples for integration smoke only, not official test scores."""
from html.parser import HTMLParser
from .datasets import GoldRecord
from .schemas import CaseInput, Document

UPSTREAM_REVIEW_PATH = "manual_reviews/data/doccano/15c038a5-6df4-469a-b0d9-4e7116ea1d79/admin.jsonl"
UPSTREAM_REVIEW_BLOB = "f9bd84ad42c27bd44bb6bea4506da017f3f7c3a1"


class Sections(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active, self.depth, self.heading = "", 0, False
        self.parts = {"claim": [], "evidence": []}

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if self.active:
                self.depth += 1
            else:
                name = dict(attrs).get("class", "")
                if name in self.parts:
                    self.active, self.depth = name, 1
        if self.active:
            if tag == "h2":
                self.heading = True
            elif tag in ("tr", "p", "br"):
                self.parts[self.active].append("\n")
            elif tag in ("td", "th"):
                self.parts[self.active].append(" ")

    def handle_endtag(self, tag):
        if self.active:
            if tag == "h2":
                self.heading = False
            elif tag == "div":
                self.depth -= 1
                if self.depth == 0:
                    self.active = ""

    def handle_data(self, data):
        if self.active and not self.heading:
            self.parts[self.active].append(data)


def import_reviews(rows: list[dict], limit: int = 20):
    cases, gold = [], []
    mapping = {"Supports": "SUPPORTS", "Refutes": "REFUTES", "Not Enough Information": "NEI"}
    for row in rows:
        if len(row["label"]) != 1 or row["label"][0] not in mapping:
            continue
        parsed = Sections()
        parsed.feed(row["text"])
        claim, evidence = ("".join(parsed.parts[k]).strip() for k in ("claim", "evidence"))
        if not claim or not evidence:
            raise ValueError("review sample is missing claim/evidence HTML sections")
        cid = "review-" + row["meta"]["example_id"]
        cases.append(CaseInput(id=cid, patient_id=cid, task="verification", question=claim,
                               documents=[Document(id="review-evidence", origin_id=cid, kind="literature", text=evidence,
                                                    license="Upstream source terms; no redistribution in this repository")],
                               data_class="deidentified"))
        gold.append(GoldRecord(case_id=cid, label=mapping[row["label"][0]], group_id=cid))
        if len(cases) == limit:
            break
    if not cases:
        raise ValueError("no supported labeled review samples found")
    return cases, gold
