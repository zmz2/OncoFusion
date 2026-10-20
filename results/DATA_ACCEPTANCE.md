# 数据验收（真实数据准备与审计）

准备机器：server21 `/home/zhangmingzhou/BioOncoFusion`，Python 3.12.15（uv 受管），
`ONCOFUSION_HF_ENDPOINT=https://hf-mirror.com`（官方 `huggingface.co` 从该机不可达，000 超时）。
原始资料留在 `data/raw/`，标签只进 `_gold/`，模型侧仅读 `inputs.jsonl`。

## CIViC-Fact 证据核验

固定 commit `1a767d889b015a836f0f4331afcac5cef165ec7f`、build `civicfact-2026.06.09`，
下载时核对 Git blob `af1b4ee457b2f96f661a27ecce72e1c938dc8c4c`（不符会显式失败）。

- 首次导入 `data/civicfact`：12,476 例 / 1,409 文章组；`inputs_sha256=093e61dc6cda8d74f8f300c616981cb95f385399650f1d8c7e54a0c52591ba0c`。
- 真实联调发现来源 id 被硬编码为 `evidence`，与模型按语义写出的真实 PMID 标识不一致，
  导致引用回填系统性失败（详见 `REAL_API_ACCEPTANCE.md` 第三节）。id 修复后按 TASK 要求
  从**同一原始文件**重导到新目录 `data/civicfact-pmidids`：
  `inputs_sha256=165c8d3415eb8588dcbafcc10eae378e1a3d0be30c1b9698bfae78b2b2d7183d`，
  `labels_sha256=f3221fa1e39e75a002f8a08c83bf409ffdf02e78c91d0ed7654ad7fe4c522088`。
  标签哈希与修订前**完全相同**，仅输入身份变化；两套输入属不同协议，统计不混算。
- 划分沿用官方：train 9,693 / dev 1,044 / test 1,026 / 未分配 713（研究前需声明划分）。
- 原生标签保持三分类 SUPPORTS 4,208 / REVISIONS 4,300 / NEI 3,968，`--verification-scheme revisions`，
  不做 REVISIONS→REFUTES 映射；`revised_claim.flat`、原标签与人工解释留在评测侧。
- 角色输入覆盖（结构信号，非重要性标签）：文献 12,476、癌种 11,555、药物 8,446、单基因变异 9,365，
  时间线 0；`heterogeneous_input_cases=0`、`multi_candidate_retrieval_cases=0`
  （每条病例只有一份文献，故重排收益不在此集判定）。
- 许可与缺失如实计数：CC BY 2,643、CC BY-NC 481、CC BY-NC-SA 149、CC BY-NC-ND 531、CC0 16、
  `none` 635、UNSPECIFIED 8,021；空标题 4,945、空许可 8,021 记为未知，不推断授权。

## MTBBench 纵向文本

从 `EeshaanJain/MTBBench` 解析 revision SHA 后固定下载，仅取事件里明确列出的源文件，
最长后缀唯一映射（歧义会显式失败并列出候选）。

- 183 题 / 40 患者；`inputs_sha256=e093bd91da2add4103971a6ee71c9fbf722bde67f68503ee866c1a90e753ffe5`、
  `labels_sha256=3dcce219f360be0b7d1193496270957ebf3834947bb59b3e8fc7886fc34f628f`。
- 患者哈希分组 seed=0、dev 20% → dev 43 题 / test 140 题；同患者所有问题同组。
- 模态计数：clinical 747、pathology 152、genomics 152；`heterogeneous_input_cases=152`。
  角色覆盖：时间线 183、基因 152、病理 152、药物 0、文献 0
  （该版本无独立 therapy/literature 文档，故 Literature 在此不等于已完成公开文献检索）。
- `empty_source_files=["data/msk_bench/cases/P-0007637/timeline2.txt"]`：跳过空文档，
  不把它解释成“未检出变异”。答案、后续 context、未宣布文件与模型日志均隔离。

## 独立段落检索

同固定 CIViC commit 的 queries/chunks（保留上游文件名 `retreival.jsonl.gz`），
相关性定义为 chunk 覆盖人工证据跨度 ≥75%，同文章同主张且标签一致的重复跨度取并集，
同查询组标签冲突整组排除。

- 纳入 1,140 条 / 602 文章组；chunk 文档 41,025；`multi_candidate_retrieval_cases=1,139`。
- 排除 169 条，原因逐条可查：NEI 无检索相关性目标 106、同文章同主张证据标签冲突 40、
  缺文章/跨度对齐或相关 chunk 23。按 DATA.md 先审 `retrieval_audit.json` 再用
  `--allow-exclusions` 放行，分母如实保留。
- 划分 train 931 / dev 125 / test 84；人工跨度与相关性只进 `_gold`。

## 隔离与复现检查

- `import-civic/import-mtb` 与 `prepare_data.py` 共用同一适配与审计，避免双入口产生不同输入。
- 加载、选择与评测三处联合校验 Case `patient_id` 与 Gold `group_id`；同患者改组名不能绕过划分。
- 工程回归：`python scripts/run_checks.py` 718 通过、分支覆盖 97%；
  LangGraph 与 native 两后端 `check_v1.py` 均 passed；模拟结果一律带 `simulated` 标记，
  不当作医学成绩（`accuracy` 0.6047 等仅证明链路可用）。
