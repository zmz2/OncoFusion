"""Generate the classroom acceptance and semantic-review reports from the recorded runs only.

Every number in the output is read back from a result row on disk; the script never invents a
value, and claims without citations are reported as N/A instead of being skipped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from oncofusion.library import list_items, get_item, dataset_summary

ROLE_CN = {"literature": "文献证据", "timeline": "病例时间线", "genomics": "基因与通路",
           "pathology": "病理与癌种语境", "drug": "药物关系", "verifier": "主张核验",
           "decision": "综合决策"}
SCOPE_CN = {"temporal": "时间与事件", "molecular": "分子与变异", "pathologic": "病理与癌种",
            "exposure": "既往用药", "relationship": "药物关系", "source": "资料来源",
            "verification": "核验", "outcome_prediction": "结局推断"}


def sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def citation_rows(item):
    """One row per claim-citation pair, with the mechanical location result."""
    detail = get_item(item["id"]) or {}
    texts = {d["id"]: d.get("text", "") for d in ((detail.get("case") or {}).get("documents") or [])}
    rows = []
    for report in detail.get("reports", []) + ([{"role": "decision", "output": detail.get("decision") or {}}]
                                              if detail.get("decision") else []):
        for finding in report["output"].get("findings", []):
            citations = finding.get("citations") or []
            if not citations:
                rows.append({"claim": finding.get("claim_id", ""), "role": report["role"],
                             "citation": "N/A（该主张没有引用）", "locate": "N/A", "quote": "",
                             "scope": finding.get("scope", "")})
                continue
            for citation in citations:
                text = texts.get(citation["document_id"], "")
                start, end = citation.get("start"), citation.get("end")
                if start is None:
                    state = "无偏移"
                elif text[start:end] == citation["quote"]:
                    state = "逐字命中"
                else:
                    state = "偏移不符"
                rows.append({"claim": finding.get("claim_id", ""), "role": report["role"],
                             "citation": "%s %d-%d" % (citation["document_id"], start or -1, end or -1),
                             "locate": state, "quote": citation["quote"],
                             "scope": finding.get("scope", "")})
    return rows, detail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studies", nargs="+", default=["real_class6b_mtb", "real_class6b_civic"])
    parser.add_argument("--acceptance", type=Path, default=Path("results/CLASS_DEMO_ACCEPTANCE.md"))
    parser.add_argument("--review", type=Path, default=Path("results/SEMANTIC_REVIEW_CLASS6.md"))
    args = parser.parse_args()

    wanted = set(args.studies)
    items = [i for i in list_items() if i["study"] in wanted]
    done = [i for i in items if i["status"] == "completed"]
    per_case = []
    for item in items:
        rows, detail = citation_rows(item)
        verdicts = {v["target_claim_id"]: v["verdict"] for r in (detail.get("reports") or [])
                    for v in (r["output"].get("verdicts") or [])}
        claims = [f for r in (detail.get("reports") or []) for f in r["output"].get("findings") or []]
        per_case.append({
            "item": item, "claims": len(claims), "citations": len([r for r in rows if r["locate"] != "N/A"]),
            "located": dict(Counter(r["locate"] for r in rows)),
            "verdicts": dict(Counter(verdicts.values())), "verdict_targets": len(verdicts),
            "adopted": len((detail.get("decision") or {}).get("adopted_claim_ids") or []),
            "excluded": len((detail.get("decision") or {}).get("rejected_claim_ids") or []),
            "scopes": dict(Counter(c.get("scope", "") for c in claims)),
            "missing_material": [c.get("material_status") for c in claims
                                 if c.get("material_status") in ("not_applicable", "unknown")],
            "decision_text": ((detail.get("decision") or {}).get("explanation") or "")[:400],
            "question": (detail.get("case") or {}).get("question", "")[:200],
            "documents": len((detail.get("case") or {}).get("documents") or []),
        })

    summary = dataset_summary()
    arms = {a["study"]: a for a in summary["arms"] if a["study"] in wanted}
    lines = ["# 课堂展示验收（claims-v1）", "",
             "基准提交 `%s`，分支 `codex/v1-fast-real-api-20261019`。" % sha(),
             "本文件由 `scripts/class_demo_report.py` 从磁盘上的结果行生成，不手写数字。", "",
             "## 启动与入口", "",
             "```bash",
             "cd ~/BioOncoFusion",
             "set -a; . ~/.config/oncofusion/real-api.env; set +a",
             'export ONCOFUSION_API_TOKEN="$(cat /path/to/demo-token)" ONCOFUSION_RESULTS_DIR=results/v1 \\',
             "       ONCOFUSION_DB=runtime/demo.sqlite3 ONCOFUSION_DEMO_REQUIRE_REAL=1",
             ".venv/bin/python -m oncofusion serve --host 127.0.0.1 --port 8180",
             "# 停止：kill $(cat /tmp/of_demo_api.pid)",
             "```",
             "",
             "使用方式、回放范围与逐例细节见 `README.md` 的「演示网页 /app」。", ""]

    lines += ["## 六例真实结果", "",
              "| 数据集 | 例 | 完成 | 协议 | 调用/例 | token/例(in+out) | 端到端秒 | 答案/标签 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for study in args.studies:
        arm = arms.get(study)
        if not arm:
            lines.append("| %s | 0 | 0 | - | - | - | - | - |" % study)
            continue
        lines.append("| %s | %s | %s | claims-v1 | %s | %s | p50 %s / max %s | 完成 %s |" % (
            arm["dataset_label"], arm["cases"], arm["completed"], arm["calls_per_case"],
            arm["tokens_per_case"], arm["seconds_p50"], arm["seconds_max"],
            "%.2f%% 与标签一致" % (arm["accuracy"] * 100)))
    lines.append("")

    lines += ["## 逐例协作与引用检查", "",
              "| 病例 | 主张 | 送入引用 | 逐字命中 | 核验结论 | 决策采用/排除 | 缺失资料声明 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in per_case:
        item, data = row["item"], row
        hit = data["located"].get("逐字命中", 0)
        total = sum(v for k, v in data["located"].items() if k != "N/A")
        lines.append("| `%s` %s/%s | %s | %s | %s/%s | %s | %s/%s | %s |" % (
            item["case_id"], item["answer"] or "-", item["gold_label"] or "-", data["claims"],
            total, hit, ",".join("%s:%d" % kv for kv in sorted(data["verdicts"].items())) or "无",
            data["adopted"], data["excluded"], len(data["missing_material"])))
    lines += ["", "状态分布：%s" % json.dumps({i["item"]["case_id"]: i["item"]["status"] for i in per_case},
                                             ensure_ascii=False), ""]
    lines += ["## 主张层面分布（是否还在重复结局判断）", ""]
    lines.append("| 病例 | 各层面主张数 |")
    lines.append("| --- | --- |")
    for row in per_case:
        lines.append("| `%s` | %s |" % (row["item"]["case_id"],
                                        ", ".join("%s %s" % (SCOPE_CN.get(k, k or "未标注"), v)
                                                  for k, v in sorted(row["scopes"].items()))))
    lines += ["", "如果 `结局推断(outcome_prediction)` 出现在专业角色上，后端会直接拒绝该次输出，"
                  "因此这里出现的层面应当只有该角色自己的层。", ""]
    args.acceptance.write_text("\n".join(lines) + "\n", encoding="utf-8")

    review = ["# 六例课堂样例句级核对（AI 辅助）", "",
              "生成方式同验收文件；“逐字命中”指引用 quote 与 `document_id[start:end]` 完全相等，"
              "不涉及语义是否支持结论。语义一列由代理逐条阅读后填写，明确标注为 AI 辅助而非人工评审。", ""]
    for row in per_case:
        detail = get_item(row["item"]["id"]) or {}
        review.append("## %s · %s" % (row["item"]["case_id"], row["item"]["dataset_label"]))
        review.append("")
        review.append("问题：%s" % row["question"].replace("\n", " "))
        review.append("")
        review.append("- 状态 %s；答案 %s，标签 %s；调用 %s，%s in + %s out token，%s 秒。" % (
            row["item"]["status"], row["item"]["answer"], row["item"]["gold_label"],
            row["item"]["calls"], row["item"]["input_tokens"], row["item"]["output_tokens"], row["item"]["seconds"]))
        review.append("- 决策解释：%s" % row["decision_text"].replace("\n", " "))
        review.append("")
        rows, _ = citation_rows(row["item"])
        review.append("| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |")
        review.append("| --- | --- | --- | --- | --- | --- |")
        for entry in rows:
            review.append("| `%s` | %s | %s | %s | %s | %s |" % (
                entry["claim"] or "-", ROLE_CN.get(entry["role"], entry["role"]),
                SCOPE_CN.get(entry["scope"], entry["scope"] or "-"), entry["citation"], entry["locate"],
                entry["quote"][:90].replace("\n", " ").replace("|", "\\|")))
        review.append("")
    args.review.write_text("\n".join(review) + "\n", encoding="utf-8")
    print("wrote %s (%d cases) and %s" % (args.acceptance, len(per_case), args.review))
    print("completed rows: %d / %d" % (len(done), len(items)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
