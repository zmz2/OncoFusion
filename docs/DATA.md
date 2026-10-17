# 数据获取、版本与隔离

## CIViC-Fact 核验

固定来源：`creisle/civicfact` 的 commit `1a767d889b015a836f0f4331afcac5cef165ec7f`，build `civicfact-2026.06.09`。压缩数据文件 Git blob `af1b4ee457b2f96f661a27ecce72e1c938dc8c4c`。脚本下载时核对 Git blob SHA-1，并记录 SHA-256；版本变化会显式失败。

```bash
python scripts/prepare_data.py civicfact --raw data/raw/civicfact --out data/civicfact \
  --download --accept-source-terms
```

已下载文件可以直接使用：

```bash
python scripts/prepare_data.py civicfact --raw data/raw/civicfact --out data/civicfact \
  --source data/raw/civicfact/civicfact-2026.06.09.jsonl.gz
```

适配器仅导出 `claim.flat`、`evidence.flat`、原文标题/PMID/许可等白名单字段；`gold_label_name`、review、civic.description、augmentation 元数据保持在评测侧。主张实体从结构化 claim 表提取，来源证据实体保持原样，避免将待核验主张伪装为证据属性。

保留官方 train/dev/test，按 PMID 进行跨集合泄漏检查。未知标签立即失败；`--refutes-label` 只在核实特定版本语义后使用。仓库旧 README 出现过 REVISIONS 字样，程序不会擅自把所有未知标签映射成 REFUTES。

## MTBBench 纵向文本

```bash
python scripts/prepare_data.py mtbbench --raw data/raw/mtbbench --out data/mtbbench \
  --download --accept-source-terms
```

从 `EeshaanJain/MTBBench` 解析 revision SHA 后固定下载；获取 `questions_msk_bench.json`，只下载事件中明确列出的源文件。通过最长路径后缀生成唯一映射；模糊匹配显式失败并列出候选。

已有本地数据时：

```bash
python scripts/prepare_data.py mtbbench --raw data/raw/mtbbench --out data/mtbbench \
  --source data/raw/mtbbench/questions_msk_bench.json
```

必要时传入已审计的 `--path-map path_map.json`：键是原始事件路径，值是 `--raw` 内的相对路径。适配器拒绝目录穿越、符号链接逃逸、非文本扩展及超限文件。

原生事件顺序为 context/file_paths/question。每个问题创建当时可见的病例快照，答案单独保存。后续 context、未宣布文件和模型日志均排除。患者使用 seed=0 的哈希分组切分（约 20% dev，其余 test），所有同患者问题始终同组。此版本是明确的阶段可见文本协议，与原论文不同模型/工具环境的成绩分开比较。

## 独立段落检索

给定段落的核验任务只有一份候选文档，适合核验，不适合重排消融。使用同文章全部 chunks 作为检索候选：

```bash
python scripts/retrieval_study.py prepare --download --accept-source-terms \
  --raw data/raw/civic_retrieval --out data/civic_retrieval
# 有排除项时先检查 retrieval_audit.json，确认原因后再显式放行
python scripts/retrieval_study.py prepare --queries data/raw/civic_retrieval/retreival.jsonl.gz \
  --chunks data/raw/civic_retrieval/document_chunks.jsonl.gz \
  --out data/civic_retrieval --allow-exclusions
python scripts/retrieval_study.py evaluate --dataset data/civic_retrieval --split dev \
  --out results/retrieval/dev.json
```

文件名 `retreival.jsonl.gz` 保留上游拼写。固定 blob：queries `4783a5ad0b63b9387b191f814a1e562337b39cb9`；chunks `4a1b5acf727d9fb1b2ff000ccde9ea9b6702d60b`。相关性定义为 chunk 覆盖人工证据跨度至少 75%；同文章同主张的重复跨度取并集。NEI、缺少对齐、超限文章等产生审计排除项。此相关性协议明确版本化，不声称逐项复制原论文 IR 指标。

检索输入仅有主张和原文 chunks，人工跨度/相关性保持在 `_gold`；人工 selections、评论等元数据排除。官方文章划分从 chunk 文件继承。

## 输出与审计

每套准备数据产生：

```text
inputs.jsonl          只供模型读取的 CaseInput
_gold/labels.jsonl    独立答案/组/划分/可选检索相关性
manifest.json        版本、条数、SHA-256
 audit.json          实际模态/分组/划分/标签/许可/长度统计
```

正式报告使用本次 `audit.json` 的实际规模，而不是沿用其他版本论文中的样本数。来源许可继承原文；仓库只提供合成示例、导入代码与无正文验证摘要。数据准备成功后应检查许可、跨组隔离和输入字段，再接入付费 API。

## 实际文献片段工程测试

`scripts/upstream_smoke.py` 支持上游手工复核文件或已审核本地提取片段；这是补充的真实内容软件测试，独立于官方测试集。采样身份、来源 blob、模拟标志和运行数保存在验证报告。它的模拟标签准确率没有科学效能含义。

## 原始资料

- https://github.com/creisle/civicfact/tree/1a767d889b015a836f0f4331afcac5cef165ec7f/data_builder
- https://github.com/creisle/civicfact/blob/master/data_builder/README.md
- https://github.com/bunnelab/mtbbench
- https://huggingface.co/datasets/EeshaanJain/MTBBench
- https://www.cbioportal.org/study/summary?id=msk_chord_2024
