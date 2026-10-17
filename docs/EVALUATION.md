# 实验协议与完整消融

## 两个主任务，独立报告

MTBBench 使用逐阶段选择题 Accuracy、患者平均 Accuracy、成本与失败率。CIViC-Fact 当前固定版保留 SUPPORTS/REVISIONS/NEI，使用给定证据的三分类 Accuracy、Macro-F1、分标签 Precision/Recall/F1。独立段落检索报告 Recall@1/3/6/10、AP@1/3/6/10。模拟结果仅用于工程验证。

研究主问题：同模型、可访问工具和预算上限下，专业分工、证据表示与核验是否改善最终表现。预先指定 Full vs single_tools / single_iterative 为主要比较，其余为探索性消融。真实结果决定模块保留、合并与适用任务。

## 25 个运行预设

| 组 | 预设 | 实际变化 |
|---|---|---|
| 主系统 | full | 七角色、结构化证据、核验和一次定向回查 |
| 单调用 | single_direct | 给定全部可见资料直接回答，0 工具调用 |
| 强工具单 Agent | single_tools | 同套确定性预处理/检索工具，1 次通用决策 |
| 计算量对照 | single_iterative | 同工具、6 次通用分析 + 1 次决策 |
| 简单多 Agent | fixed_five | 五个基础角色，文本板，无独立核验/回查 |
| 表示对照 | fixed_text | 七角色，文本板、反思核验、无回查 |
| 协作 | all_generalist / adaptive | 全角色通用提示 / 依据输入模态跳过空职责 |
| 结构修复 | schema_repair | 模型 JSON/引用校验失败后最多修复一次 |
| 九机制 | without_* | 单独关闭下面九个特征 |
| 七角色 | delegate_* | 把该角色交给通用提示，保留相同输入和工具 |

九特征：variant_normalization、disease_matching、drug_polarity、retrieval_reranking、timeline_structure、external_verification、source_deduplication、structured_board、targeted_requery。

Full 基础模型调用数为 7；一次补证增加 Literature 与 Verifier 两次调用。所有 preset 默认同一模型、12 次模型/工具上限及 120,000 token 总上限。统一上限与基础调用数对照不能替代真实 token 配对，所以报告实际 usage，同时提供预算曲线。真实供应商不支持 seed 时重复运行仍可衡量输出波动，但不把 seed 解释成供应商确定性保证。

## 41 个完整 treatment

每个完整计划包含 25 个预设，再加：

- 9 种数据扰动：随机顺序、重复来源、无关资料、未来 canary、分别去掉 genomics/pathology/therapy/literature/clinical 输入。
- 检索 top-k：1、3、10，候选池保持一致。
- 40k / 80k token 上限，分别运行 Full 与 single_iterative，共 4 项。

每项 seeds=0,1,2。文件位于 `experiments/`，包括 civic/mtb 的 dev_smoke（5 组、5 个基本系统）、dev_complete、test_complete。完整计划先在开发集执行；测试计划在提示与参数冻结后一次性评测。

## 角色、机制与信息贡献分别解释

`delegate_genomics` 保留分子资料与工具、只移交专业提示；`without_variant_normalization` 保留角色与资料、关闭对应预处理；`robust_without_genomics` 移除该类文档。三者分别检验专业分工、机制与信息价值。

部分任务没有某类输入，相关消融可能等价。CIViC 给定证据任务常只有一个文献文档，`without_genomics` 文档删除或重排的效果可能为零。对每个 Agent 应同时报告适用子集；段落检索重排使用独立检索任务。统计上观察到零收益也是结果，保持诚实解释。

原始基因文本的变异提取、病理命名字段、药物方向都带具体可执行信号，测试确认开关改变 payload。信号变化证明实验实现有效；效果提升仍须真实模型与真实标签支持。

## 运行与复用

```bash
python scripts/run_study.py --plan experiments/civic_dev_smoke.json \
  --dataset data/civicfact --out results/civic_dev_smoke --dry-run
python scripts/run_study.py --plan experiments/civic_dev_smoke.json \
  --dataset data/civicfact --out results/civic_dev_smoke --allow-remote
python scripts/run_study.py --plan experiments/civic_dev_smoke.json \
  --dataset data/civicfact --out results/civic_dev_smoke --allow-remote --resume
```

真实任务默认执行数量上限 1000；smoke 测出平均费用后，完整计划显式提高 `--execution-cap`。这个参数是任务数上限，token/调用预算仍由每个 RunConfig 控制。失败样本在 resume 时保留，只有显式 `--retry-failed` 才重试，防止自动重复计费。

代码、模型配置、任务计划、输入与标签指纹共同决定 study identity。任一改变使用新的输出目录，旧结果保留。结果目录包含逐样本完整轨迹、各配置 summary、最终 study.json、identity.json。

## 统计与缺失

重复运行先在样本内平均，再按患者/文章聚类进行配对 bootstrap，默认 2000 次。所有运行使用相同分组与样本 ID。探索性多重比较暂不校正，报告需按此解释。

失败、超预算样本的预测按错误计入分母。真实网络错误可能发生在供应商已处理但未返回 usage 时，此时费用只报告可观察下界；`cost_complete=false` 或 `usage_incomplete_runs>0` 应保留在表格中。失败轨迹中已有供应商 usage 的调用继续计入 token、逻辑调用数和已知费用。`known_cost_usd` 仅汇总已报告 usage 按配置价格估算的金额；字符估算 usage 的金额另列 `estimated_cost_usd`。真实模式出现估算 usage、HTTP 重试或未返回 usage 的失败时标记不完整。价格缺失时已知费用为零只是可计算项为空。模拟器的零费用只代表模拟运行。

最终决策接收各角色最新 `unresolved` 列表；定向补证后的同角色报告替换旧的未解决列表。角色输出仍是待核查的推论，最终答案依据原始来源。变异归一化/癌种匹配开关同时控制预处理和检索重排，避免消融发生旁路。

## 报告与人工语义核验

```bash
python scripts/build_report.py --study results/civic_dev_smoke/study.json --out results/civic_report
python scripts/review_citations.py export --study results/civic_dev_smoke \
  --inputs data/civicfact/inputs.jsonl --out results/review --limit 200
# 两人独立填写 reviewer_A.csv / reviewer_B.csv 的 supports=yes/no/unclear
python scripts/review_citations.py score --first results/review/reviewer_A.csv \
  --second results/review/reviewer_B.csv --out results/review/agreement.json
```

抽样为按固定哈希顺序抽取的引用主张；原文全文和精确 quote 提供给评审，配置和模型身份保存在私有映射中。分别输出支持比例、一致率、Cohen kappa 与待仲裁记录。该审查范围是已引用主张，遗漏引用和结论完整性可另设任务，保持指标名称准确。

## 最终需要的结果

主结果表、七角色委派表、九机制表、数据扰动/成本表、独立检索表、人工引用语义表，以及至少 6 个完整成功/失败/纠错案例。基线与消融均已实现；真实实验的“哪个模块有效”根据结果填写。

## 上游复用版开发集计划

新增两个 `upstream_*_dev.json` 计划，各24配置×3重复、五个开发集来源组。新机制为证据先行、专业工作清单和同角色最新报告板；LangGraph/native等价比较单独报告。每个旧角色与机制消融也套用新版配置。外部ToolUniverse快照不加入标准基准；未来扩展必须所有对照共用固定快照并单独定义协议。全文见 AGENT_REUSE_AUDIT。
