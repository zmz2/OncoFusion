"""Pick six traceable cases for human inspection: success, failure and repair/correction shapes."""
import argparse
import json
from pathlib import Path

from oncofusion.datasets import read_jsonl


def load(study_dir: Path) -> dict:
    rows = {}
    for path in sorted(study_dir.glob("*/*/*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        data = json.loads(path.read_text())
        rows[data["case_id"]] = data
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()

    gold = {g["case_id"]: g for g in (json.loads(l) for l in args.gold.read_text().splitlines())}
    visible = {row["id"]: row for row in read_jsonl(args.inputs)}
    ref, cand = load(args.reference), load(args.candidate)
    common = sorted(set(ref) & set(cand))

    def score(row):
        answer = row["decision"]["answer"] if row["decision"] else None
        return int(row["status"] == "completed" and answer == gold[row["case_id"]]["label"])

    categories = {"budget_or_failure": [], "disagreement": [], "both_correct": [], "both_wrong": []}
    for case_id in common:
        r, c = ref[case_id], cand[case_id]
        if r["status"] != "completed" or c["status"] != "completed":
            categories["budget_or_failure"].append(case_id)
        elif score(r) != score(c):
            categories["disagreement"].append(case_id)
        elif score(r):
            categories["both_correct"].append(case_id)
        else:
            categories["both_wrong"].append(case_id)

    picked, order = [], ["budget_or_failure", "disagreement", "both_correct", "both_wrong"]
    for kind in order:
        for case_id in categories[kind]:
            if len(picked) >= args.limit:
                break
            picked.append((kind, case_id))
        if len(picked) >= args.limit:
            break

    lines = ["# 可追溯人工检查案例（真实 API，脱敏：只含结构断言，不含病例正文或论文片段）", ""]
    lines.append("| # | 类别 | 病例 | 七Agent 判定/正确 | 单调用 判定/正确 | 引用数 | quote 逐字命中 | offset 与原文一致 | 跨来源检查 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for index, (kind, case_id) in enumerate(picked, 1):
        cells = []
        for arm in (ref, cand):
            row = arm[case_id]
            answer = row["decision"]["answer"] if row["decision"] else None
            citations = (row["decision"].citations if False else (row["decision"]["citations"] if row["decision"] else []))
            doc_texts = {d["id"]: d["text"] for d in visible[case_id]["documents"]}
            verbatim = all(c["quote"] in doc_texts.get(c["document_id"], "") for c in citations)
            offsets = all(doc_texts.get(c["document_id"], "")[c["start"]:c["end"]] == c["quote"]
                          for c in citations if c["start"] is not None)
            foreign = all(c["document_id"] in doc_texts for c in citations)
            cells.append((answer, score(row), len(citations), verbatim, offsets, foreign))
        seven, one = cells
        lines.append("| %d | %s | `%s` | %s/%d | %s/%d | %d / %d | %s / %s | %s / %s | %s / %s |" % (
            index, kind, case_id, seven[0], seven[1], one[0], one[1], seven[2], one[2],
            seven[3], one[3], seven[4], one[4], seven[5], one[5]))
    lines += ["", "判定/正确列：模型答案与 `_gold` 标签的是否一致（1 对 0 错）；",
              "quote 逐字命中与 offset 一致列：七Agent / 单调用 两臂分别对全部引用做机械校验的结果；",
              "跨来源检查确认每条引用的 `document_id` 都在该病例本阶段可见来源内。",
              "双人语义审查用 `scripts/review_citations.py export/score`，本表只证明定位正确，不替代语义支持判断。",
              ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print("picked", len(picked), "cases ->", args.out)
    print("categories:", {k: len(v) for k, v in categories.items()})


main()
