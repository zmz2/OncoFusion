> 首版整体审查与最新执行范围见 `docs/V1_PROJECT_REVIEW.md`（仓库根目录相对路径）及根目录 TASK.md；下文保留既有协议/历史背景。新增medspaCy为实际运行组件，相关验证以当前CI为准。

# Agent 与上游复用审计（2026-10-17）

## 结论

采用 **LangGraph 执行图 + ToolUniverse 受限工具层 + OncoFusion 评测与来源契约**。
GeneAgent、TxAgent、PaperQA2 的合适方法进入角色工作清单；保留已有病例阶段隔离、引用校验、预算、数据适配和网页接口。保留旧实现进行同条件比较，真实模型开发集决定最终默认版本。

复用有明确层级：LangGraph 与 ToolUniverse 是实际运行依赖；GeneAgent/PaperQA2 的方法是自主适配；MDAgents/medspaCy 是设计参考。当前代码没有加载 GeneAgent、TxAgent 的模型权重，也没有运行 PaperQA2 的完整 Agent 或 medspaCy 的 NLP 模型。

## 审查起点

审查基准提交为 `bf8efe2b1aafa9a78f0837e1433bd61da220a053`。原七角色使用共同 `AnalysisOutput`、简短专业提示和本地确定性工具。工程回归通过，支持的医学能力仍需真实评测。

发现两项适合直接实验的具体问题：

1. 原流程先运行 Timeline/Genomics/Pathology/Drug，随后才检索 Literature。CIViC 给定证据常只有文献，早期专家没有拿到可引用证据。`evidence_first=true` 将同一次 Literature 节点提前，不额外增加首轮模型调用。
2. 定向回查之后，旧 Literature/Verifier findings 仍与新 findings 一起进入后续证据板。`latest_role_board=true` 仅将同角色最新报告用于工作板，完整历史报告继续保存在轨迹中。

此外，基因变异归一化原来只是字符串归一化；药物方向原来只是词面信号。它们继续作为检索/解析工具，专业工作清单明确要求用证据判断功能和方向。

## 逐角色决策

| 角色 | 原实现 | 审查参考 | 本轮采用 | 复用程度 |
|---|---|---|---|---|
| Genomics | 变异拼写、正则提取、分子匹配 | GeneAgent；ToolUniverse | 分开记录基因通路成员关系、具体变异功能、样本实测活动；先证据后解释。可读取 MyGene/UniProt 固定记录 | ToolUniverse SDK 实际复用；GeneAgent 方法适配 |
| Pathology & Context | 标本/病理字段、癌种字面匹配 | medspaCy；PathChat | 显式区分原发/取样部位、患者/家族/假设描述、检验定义；保持文本任务 | 自有解析保留；上下文规则设计参考 |
| Drug | 药物实体、敏感/耐药关键词 | TxAgent；ToolUniverse precision-oncology | 药物—靶点—癌种—变异的适用性、原发/获得性耐药、既往暴露、证据终点；OpenTargets/DGIdb 记录可进入固定输入 | 实际复用 TxAgent 所用 ToolUniverse 工具层，未加载 TxAgent 权重 |
| Literature | 本地 BM25 与实体重排 | PaperQA2 | 提前汇集可引用证据，强调支持与反证、原始来源、检索命中与原始实验区分；补证在许可语料内完成 | 方法适配；当前检索仍为本地 BM25/规则重排 |
| Timeline | 阶段/日期过滤与事件排序 | MTBBench；medspaCy | 保留代码强制可见性；角色区分事件时间、记录顺序、计划/否定/不确定事件 | 自有隔离与排序保留；断言语境设计参考 |
| Verifier | 来源阅读或反思、一次补证 | GeneAgent；PaperQA2 | 专门逐项检查变异/癌种/药物/时间/终点；引用字面匹配与语义支持分开；修订替代旧工作板 | 自主适配核验机制；精确引用检查保留 |
| Decision | 汇总答案、来源、未解决项 | MDAgents moderator；LangGraph evaluator-optimizer | 从最新来源状态综合，保留冲突和缺证；按任务原生标签作答；一次回查后结束 | 方法参考；图执行实际复用 LangGraph |

每个角色的工作清单位于 `oncofusion/agent_design.py`，通过 `specialist_contracts` 开关启用。清单指导模型行为，实际正确性需开发集和人工引用审查检验。

## 为何选择性复用

**GeneAgent** 针对基因集功能命名。我们审阅的 `worker.py` 使用旧 Azure/OpenAI 接口与最多20轮调用。直接搬用会改变任务、预算及结构约束。采用其外部证据核验原则，使用我们的模型供应商和精确来源契约。

**TxAgent** 的原配置含专用模型和 ToolRAG，README 推荐 H100 >80GB。课程当前使用 API，选择复用同项目的 ToolUniverse SDK。SDK 的所选五种查询均为远端数据库/API 查询；这些功能可由 CPU 执行。

**ToolUniverse precision-oncology skill** 的信息核对顺序很有用，但其中固定治疗映射、当前批准状态、强制 FAERS 和临床试验任务超出课程基准。本项目只适配问题相关的实体、适用性、证据终点和耐药检查；不将固定治疗表作为模型答案。

**PaperQA2** 的完整能力涉及检索规划、embedding、多轮证据摘要和额外模型调用。当前只适配证据组织和冲突核验方法。未来接入其完整包时，必须先包住语料限制、引用偏移、全部模型费用及失败统计，再与现有 Literature 比较。

**PathChat** 的核心输入是病理图像。当前 MTBBench 纵向分支以文本/标本字段为输入，保留 Pathology & Context。图像分支需要独立图像模型、数据与测试。

**MDAgents** 是问题复杂度驱动的协作参考。现有 `routing=adaptive` 按是否存在对应模态跳过角色，和 MDAgents 的复杂度分类不同。

**Biomni/BioMCP** 是可信候选，但分别提供更广的执行环境或重叠工具层。首版固定一种受限读工具 SDK，减少不同源、缓存、费用和许可策略混在一起。

这次选择依据任务匹配、可检查实现和工程验证。当前没有证据表明我们在真实生物医学准确率上优于这些项目。

## 实际工作流

输入白名单/阶段过滤 → Literature → Timeline → Genomics → Pathology & Context → Drug → Verifier →（必要时一次 Literature + Verifier）→ Decision。

`workflow_backend=langgraph` 真正构造并运行 `StateGraph`；`native` 使用同一节点函数与条件。节点保持串行，便于预算与消融比较。本轮不启用图并行或持久化 checkpoint 恢复；已有任务终态与实验级 resume 保持原行为。`GET /v1/workflows` 明确返回这些能力。

## ToolUniverse 真实复用边界

`oncofusion/upstream_tools.py` 调用官方 SDK 的初始化、指定工具加载、工具 schema 和执行接口。初始化关闭 hooks 和 workspace 加载；不加载 LLM finder、代码执行、自动总结或用户自定义工具。

五项白名单：MyGene_query_genes、UniProt_get_function_by_accession、DGIdb_get_drug_gene_interactions、OpenTargets_get_associated_drugs_by_target_ensemblID、PubMed_search_articles。参数使用真实 SDK schema 验证，拼错的 `q` 与正确的 `query` 明确区分。SDK、网络与错误响应显式失败。

运行 `scripts/prepare_sources.py` 前人工审核公开实体查询和来源许可；程序只向数据库发送这份查询计划，读取 CaseInput 的函数不向 SDK 传递病历正文。响应、查询、获取时间、版本与 SHA256 保存为快照，额外模型调用为零。

快照只能直接附加到审核过的当前自定义 synthesis 案例。标准 verification/mcq 和历史病例禁止此扩展，避免检索到测试条目结论或未来知识。同一快照供所有对照共用。记录被明确标为数据库/搜索记录，不能当作已经核验的原论文证据；检索结果的全文获取仍应单独审查。

快照去重仅识别相同查询和记录；不同查询返回同一篇论文的跨查询去重需后续提取 PMID/DOI 后增强。来源链接指向实际供应商入口，源许可证依各返回材料而定。

## 对照与验收

旧25预设保持原语义。新增 `experiments/upstream_civic_dev.json` 和 `upstream_mtb_dev.json`，每个24种配置×3重复，选择5个开发集来源组：旧Full、仅图运行、仅证据先行、仅专业清单、仅最新板、完整候选、两个单Agent基线、七角色委派、九机制消融。

先验证 native/graph 同输入输出等价，再检验证据顺序、清单和工作板贡献。图框架本身是基础设施，不算模型能力提升。两套主任务分别报告；新增线上来源属于另一个扩展协议。配置变化使用新的结果目录。

## 原始来源

- GeneAgent: https://github.com/ncbi-nlp/GeneAgent ，https://www.nature.com/articles/s41592-025-02748-6
- TxAgent: https://github.com/mims-harvard/TxAgent
- ToolUniverse: https://github.com/mims-harvard/ToolUniverse ，https://zitniklab.hms.harvard.edu/ToolUniverse/guide/python_guide.html
- 已审查skill: https://github.com/mims-harvard/ToolUniverse/blob/9f6b13919394393311d355c0b2376db63c7ab452/skills/tooluniverse-precision-oncology/SKILL.md
- PaperQA2: https://github.com/Future-House/paper-qa
- LangGraph: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- MDAgents: https://github.com/mitmedialab/MDAgents
- medspaCy: https://github.com/medspacy/medspacy
- PathChat: https://www.nature.com/articles/s41586-024-07618-3
- Biomni: https://github.com/snap-stanford/Biomni
- BioMCP: https://github.com/genomoncology/biomcp

精确包版本和复用层级同时保存在根目录 `upstream_manifest.json`。本项目没有复制上游模型、整仓库源码或完整 skill。
