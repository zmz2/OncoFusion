"""Export experiment tables without external services. Citation review has a separate script."""
import argparse
import csv
import json
from pathlib import Path


def build(source: Path, output: Path) -> dict:
    study = json.loads(source.read_text())
    output.mkdir(parents=True, exist_ok=True)
    columns = ["treatment", "preset", "perturbation", "accuracy_mean", "accuracy_std", "macro_f1_mean",
               "failed_or_incomplete", "observed_calls", "observed_input_tokens", "observed_output_tokens", "known_cost_usd", "cost_complete", "usage_incomplete_runs"]
    with (output / "results.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in study["table"]:
            writer.writerow({key: row[key] for key in columns})
    heading = "模拟运行：仅验证软件流程" if study["simulated"] else "真实模型运行：依据冻结协议解释结果"
    text = ["# OncoFusion 实验报告", "", heading, "",
            f"病例/样本数：{study['case_count']}；患者/文章组数：{study['group_count']}。", "",
            "| 配置 | Accuracy | Macro-F1 | 未完成 | 相对主配置差值及95%区间 |", "|---|---:|---:|---:|---|"]
    for row in study["table"]:
        ci = row["delta_vs_reference"]
        text.append(f"| {row['treatment']} | {row['accuracy_mean']:.4f} | {row['macro_f1_mean']:.4f} | {row['failed_or_incomplete']} | {ci['mean_delta']:.4f} [{ci['ci95'][0]:.4f}, {ci['ci95'][1]:.4f}] |")
    text += ["", "统计说明：重复种子先在样本内平均，随后按患者/文章聚类 bootstrap。消融收益依据实测结果判断。", "",
             "引用检查：自动校验只说明原文片段与偏移一致；语义支持率使用双人盲审结果。", "",
             "## 需要填写的结果分析", "", "主要对照：Full 与 single_tools、single_iterative。",
             "记录各 Agent 的收益、成本、失败案例和适用子集。所有科学结论以真实模型结果为准。"]
    (output / "REPORT.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return {"table": str(output / "results.csv"), "report": str(output / "REPORT.md")}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--study", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(build(args.study, args.out)))
