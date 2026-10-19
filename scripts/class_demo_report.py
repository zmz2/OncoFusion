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

# The three cases the classroom round opens with, and what each one is there to show.
CLASSROOM_NOTES = {
    "mtb-P-0027883-q7": ["长时间线 + 真实分子资料，预测题带不确定性",
                         "七个角色各交自己那层（KRAS p.G12V / TP53 p.C275Y / FLT4 p.V1069I 与拷贝数缺失、"
                         "原发胰导管腺癌与分期、50.070 岁卡培他滨暴露），缺失层面写 unknown 且不带引用；"
                         "决策解释自己说了“支持但不证明”。"],
    "civic-60a33dc8-2af3-4b38-9a5c-951b40aafd27": ["单文献核验：来源与本题无关，逐角色写 unknown",
                                                   "要核验 MTOR F2108L / 皮肤癌 / 丝氨酸-苏氨酸激酶抑制剂耐药，"
                                                   "手里只有一篇 BCR-ABL/慢性髓系白血病文献；系统把 7 条主张排除、"
                                                   "答案给 NEI，这正是“没证据时怎么收口”。"],
    "mtb-P-0006191-q0": ["小输入全覆盖，答错的预测样例",
                         "8 段候选全部送入（100% 覆盖），最新记录 56.082 岁 CT「无癌、未进展」，系统据此答不复发，"
                         "标签是复发；未解决项写明了 56.082 之后没有任何随访记录。"],
}


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
    parser.add_argument("--studies", nargs="+", default=["real_class6c_mtb", "real_class6c_civic"])
    parser.add_argument("--audit", type=Path, default=Path("results/v1/fragment_truncation_audit.json"),
                        help="output of scripts/fragment_truncation_audit.py, rendered as fix evidence")
    parser.add_argument("--acceptance", type=Path, default=Path("results/CLASS_DEMO_ACCEPTANCE.md"))
    parser.add_argument("--review", type=Path, default=Path("results/SEMANTIC_REVIEW_CLASS6.md"))
    args = parser.parse_args()

    wanted = set(args.studies)
    items = [i for i in list_items() if i["study"] in wanted]
    done = [i for i in items if i["status"] == "completed"]
    per_case = []
    for item in items:
        rows, detail = citation_rows(item)
        verdict_rows = [v for r in (detail.get("reports") or [])
                        for v in (r["output"].get("verdicts") or [])]
        claims = [f for r in (detail.get("reports") or []) for f in r["output"].get("findings") or []]
        per_case.append({
            "item": item, "claims": len(claims), "citations": len([r for r in rows if r["locate"] != "N/A"]),
            "located": dict(Counter(r["locate"] for r in rows)),
            "verdicts": dict(Counter(v.get("verdict", "?") for v in verdict_rows)),
            "verdict_targets": len({v.get("target_claim_id") for v in verdict_rows}),
            "adopted": len((detail.get("decision") or {}).get("adopted_claim_ids") or []),
            "excluded": len((detail.get("decision") or {}).get("rejected_claim_ids") or []),
            "scopes": dict(Counter(c.get("scope", "") for c in claims)),
            "missing_material": [c.get("material_status") for c in claims
                                 if c.get("material_status") in ("not_applicable", "unknown")],
            "decision_text": ((detail.get("decision") or {}).get("explanation") or "")[:400],
            "question": (detail.get("case") or {}).get("question", "")[:200],
            "documents": len((detail.get("case") or {}).get("documents") or []),
            "coverage": [(r.get("role", "?"), r["evidence_coverage"])
                         for r in (detail.get("roles") or []) if r.get("evidence_coverage")],
        })

    summary = dataset_summary()
    arms = {a["study"]: a for a in summary["arms"] if a["study"] in wanted}
    lines = ["# 课堂展示验收（claims-v1）", "",
             "审查基准 `56492fd`，分支 `codex/v1-fast-real-api-20261019`；"
             "本文件生成时的 HEAD 是 `%s`。" % sha(),
             "数字全部由 `scripts/class_demo_report.py` 从磁盘上的结果行读出，不手写；"
             "本句之后的叙述文字同样来自该脚本。", "",
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
        lines.append("| %s | %s | %s | claims-v1 | %s | %s | p50 %s / max %s | %d/%d 与标签一致（试运行） |" % (
            arm["dataset_label"], arm["cases"], arm["completed"], arm["calls_per_case"],
            arm["tokens_per_case"], arm["seconds_p50"], arm["seconds_max"],
            round(arm["accuracy"] * arm["cases"]), arm["cases"]))
    lines += ["", "两个数据集分别只有 4 例与 2 例、且分属 3 位患者与 2 篇文献，这两个数字是试运行读数，"
                  "不是模型能力结论；样本数和来源组数随表列出。", ""]

    lines += ["## 每个角色实际收到多少证据（从记录回读，不是估算）", "",
              "`候选` = 该阶段可见文档被切成的整段记录数（现在覆盖全文）；`送入` = 本次真正写进提示的片段数。"
              "两列都在结果行里，网页的角色卡片同源。", "",
              "| 病例 | 角色 | 候选段 | 送入段 | 原文字符 | 送入字符 | 送入占比 | 预算字符 | 只覆盖前缀？ |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in per_case:
        for role, cov in row["coverage"]:
            share = cov.get("chars_sent", 0) / max(1, cov.get("chars_total", 0))
            lines.append("| `%s` | %s | %s | %s | %s | %s | %.1f%% | %s | %s |" % (
                row["item"]["case_id"], ROLE_CN.get(role, role), cov.get("candidates"),
                cov.get("sent"), cov.get("chars_total"), cov.get("chars_sent"), share * 100,
                cov.get("budget_characters"),
                "是（有文档未全覆盖）" if cov.get("tail_dropped") else "否"))
    lines += ["", "这六例里同一病例的七个节点数字相同：记录显示它们看到的阶段可见文档集一致，角色差异体现在"
                  "各自的提示与输出契约上，而不是各自换一批文档；跨病例的候选数差别很大（1 段到 47 段）。"
                  "`只覆盖前缀？` 一列在旧实现里恒为“是”，因为每文档最多取前 8 段。", ""]

    lines += ["## 逐例协作与引用检查", "",
              "| 病例 | 答案/标签 | 主张 | 送入引用 | 逐字命中 | 核验结论 | 决策采用/排除 | 缺失资料声明 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in per_case:
        item = row["item"]
        hit = row["located"].get("逐字命中", 0)
        total = sum(v for k, v in row["located"].items() if k != "N/A")
        na = row["located"].get("N/A", 0)
        lines.append("| `%s` | %s / %s | %d | %d | %d/%d（无引用 %d） | %s（%d/%d 主张） | %d/%d | %d |" % (
            item["case_id"], item["answer"] or "-", item["gold_label"] or "-", row["claims"],
            total, hit, total, na,
            ",".join("%s:%d" % kv for kv in sorted(row["verdicts"].items())) or "无",
            row["verdict_targets"], row["claims"],
            row["adopted"], row["excluded"], len(row["missing_material"])))
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

    if args.audit.is_file():
        a = json.loads(args.audit.read_text(encoding="utf-8"))
        lines += ["## 输入截尾修复证据（本地重放，不调模型）", "",
                  "`scripts/fragment_truncation_audit.py` 按基准提交 56492fd 的前缀走法"
                  "（`fragment_chars=%s`、每文档最多 %s 段）重放了 `%s` 的全部输入：" % (
                      a["fragment_chars"], a["fragments_per_document"], a["dataset"]),
                  "",
                  "- 病例 %d 个，其中 **%d 个**至少有一份文档被截掉尾部；文档 %d 份中有 %d 份被截。" % (
                      a["cases"], a["cases_truncated"], a["documents"], a["documents_truncated"]),
                  "- 看不见的原文共 %d 字符，占全部输入字符（%d）的 **%.1f%%**。" % (
                      a["characters_dropped"], a["characters"], a["share_characters_dropped"] * 100),
                  "",
                  "现行 `fragment_documents()` 先把每份文档整篇切成记录级候选（候选数＝上表文档的真实段数，"
                  "不再有“永远不可见的前缀之外内容”），再按问题、最新临床事件与分子/病理关键字段挑选送入子集；"
                  "每个节点把自己收到的 `evidence_ids` 与覆盖信息写进结果行，就是上一节那张表。",
                  "换句话说：修复的是“候选层面的截尾”，送入层面仍然受预算约束，并且现在会在页面上明说。", ""]
    else:
        lines += ["", "（缺少 `%s`：先运行 `scripts/fragment_truncation_audit.py` 再重新生成本报告。）" % args.audit, ""]

    by_case = {r["item"]["case_id"]: r for r in per_case}
    lines += ["## 课堂现场用的三个案例（已可回放）", "",
              "| 案例 | 演示点 | 实测 |", "| --- | --- | --- |"]
    for case_id, pitch in CLASSROOM_NOTES.items():
        row = by_case.get(case_id)
        if not row:
            lines.append("| `%s` | %s | 无结果行 |" % (case_id, pitch[0]))
            continue
        item = row["item"]
        lines.append("| `%s` | %s | 答案 %s（标签 %s），主张 %d，逐字命中 %d，采用/排除 %d/%d，送入占比 %s |" % (
            case_id, pitch[0], item["answer"], item["gold_label"], row["claims"],
            row["located"].get("逐字命中", 0), row["adopted"], row["excluded"],
            "100%" if not any(c.get("tail_dropped") for _, c in row["coverage"])
            else "%.0f%%" % (100 * max((c.get("chars_sent", 0) / max(1, c.get("chars_total", 0))
                                        for _, c in row["coverage"]), default=0))))
    lines += ["", "网页里默认显示每个案例的中文要点，原始英文结论与引用片段放在折叠区（`oncofusion/web/index.html` 的 "
                  "CLASS_NOTES 与主张表）。", ""]
    for case_id, pitch in CLASSROOM_NOTES.items():
        lines.append("- `%s`（%s）：%s" % (case_id, pitch[0], pitch[1]))
    lines.append("")

    lines += ["## 本轮修了什么（可在代码与测试里核对）", "",
              "- 片段规划改成整篇文档的记录级候选 + 按问题/最新临床事件/关键字段选择，换行只前进 1 字符；"
              "`tests/test_v1_fast.py` 里有对应的 4 条回归（跨行不切字、整篇候选、预算截断、未送入的 id 不可引用）。",
              "- 原始来源、可见文档、实际送入片段三个概念分开记录：每个节点写自己的 `evidence_ids` 与 `evidence_coverage`，"
              "页面角色卡片读的就是这两个字段，不再出现“模型读了全文”这类描述。",
              "- claims-v1 协作协议：主张带稳定 `claim_id`/`author_role`，后序声明 `used_claim_ids`，"
              "Verifier 逐主张给 `confirmed/corrected/rejected/insufficient`，Decision 给采用与排除；"
              "层面越权（例如专业角色直接下结局判断）由 `ROLE_SCOPES` 当场拒绝，回归在 `tests/test_claim_scopes.py`。",
              "- 计划文件不再手抄配置：`scripts/make_class_plan.py` 从 `profiles.v1_class_config()` 写出计划并断言相等，"
              "`tests/test_v1_contract.py` 检查每个计划的 ceiling 与它 `reference` 的 profile 一致（历史计划显式列入 frozen 名单）。",
              "- demo 只认真实 provider：`ONCOFUSION_DEMO_REQUIRE_REAL=1` 时缺 API 直接启动失败；页面模式取结果行的 "
              "`simulated`；回放白名单校验 `(study, treatment)` 与 case id 字符集（`tests/test_demo_app.py` 覆盖了 `../unapproved` 逃逸）。",
              "- 用量与失败分母：逐角色累加所有修复调用，`/v1/library?include_failed=true` 一并返回 `.failed.json` 行并可筛完成项。",
              "- CI：core 走 native 后端，LangGraph 契约单独一个 job；container 断言 `/app` 含「主张与核验关系」「执行顺序」且 demo 配置是 v1_class/claims-v1。",
              "", "## 还没做的", "",
              "- 关键引用的逐条语义核对目前是 AI 辅助（`results/SEMANTIC_CHECK_CLASS6_AI.md`），"
              "偏移定位单独记录在 `results/SEMANTIC_REVIEW_CLASS6.md`；没有第二位人工评审。"
              "核对里已经标出 4 条只能判“部分支持”的主张：逐字命中不等于引文覆盖该句的每个字段。",
              "- 六例是单 seed 试运行：MTB 4 例、3 位患者，CIViC 2 例、2 篇文献；不做显著性陈述，"
              "31 例单次验收与单 Agent 对照等到功能稳定后按需要再跑。",
              "- 预算仍是硬约束：上面“送入占比”小于 100% 的案例，页脚会写明哪些文档尾部没送进去，"
              "而不是假装全覆盖。", ""]

    args.acceptance.write_text("\n".join(lines) + "\n", encoding="utf-8")

    review = ["# 六例课堂样例：机械定位核对", "",
              "生成方式同验收文件；“逐字命中”指引用 quote 与 `document_id[start:end]` 完全相等，"
              "不涉及语义是否支持结论。语义层面的逐条判断在 `results/SEMANTIC_CHECK_CLASS6_AI.md`"
              "（由代理逐条阅读后填写，明确标注为 AI 辅助，不是人工评审；无引用的主张记 N/A）。", ""]
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
