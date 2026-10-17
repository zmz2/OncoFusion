# OncoFusion v0.2：Agent 来源审查与分层复用

## 结论与当前状态

原版七个角色由同一个 Provider、七条简短职责提示和确定性预处理组成。工程回归充分，专业机制与外部工具的实现较薄。原版保留为 `full` 基线；新增 `grounded_v2` 为推荐的开发集候选，`grounded_v2_contexts` 进一步启用 PaperQA 的逐段上下文摘要。是否提升生物医学质量，以同模型、同语料、同预算上限的真实开发集结果决定。

新版采用分层复用：LangGraph 负责图执行；ToolUniverse 负责知识接口；GeneAgent 提供可移植的基因集富集函数与逐主张核验思路；PaperQA 提供直接复制的 RCS 提示模板；MDAgents 提供协作组织参考。病例可见性、评测器、预算、原文引用校验、持久化与 `/v1` 契约保留 OncoFusion 实现。

## 逐角色设计与选择

| 角色 | 原实现 | 本轮实现 | 复用层次 |
|---|---|---|---|
| Genomics | 蛋白变异简写规则、基因/变异匹配、短提示 | 明确基因、变异功能、通路成员关系与实际活动的区别；可使用 MyGene/Reactome 冻结知识；提供 GeneAgent 富集函数适配 | GeneAgent 函数改编；ToolUniverse SDK 直接调用；职责提示自行适配 |
| Pathology & Context | 病理字段正则、癌种字符串匹配 | 保留文本/元数据分析，增加标本、部位、原发/转移、历史/当前适用性；接入 OncoTree 标准术语查询 | 自有语境逻辑 + ToolUniverse 的 OncoTree 工具 |
| Drug | 敏感/耐药词汇规则、短提示 | 按靶点机制、实验响应、临床响应、耐药、监管状态分别形成主张；可使用 ChEMBL/OpenTargets 冻结响应 | 直接复用 TxAgent 所依赖的 ToolUniverse 工具层；治疗推理协议适配 |
| Literature | 自制 BM25 + 实体词汇重排 | 检索提前；可启用 PaperQA 逐段相关摘要和 0–10 相关分；原文仍供下游核验 | 两个 PaperQA 提示模板逐字复用；Provider/预算/语料边界使用自有实现 |
| Timeline | 阶段/时间过滤和排序 | 保留时间可见性，补齐观察时间、报告时间、历史暴露与当前状态的协议 | 保留；直接契合纵向基准 |
| Verifier | 对板上结论整体复核 | 稳定主张 ID、按角色轮转选取核验目标、每个目标一个判定、检查完整覆盖、显式传递未核验项 | GeneAgent 核验思想的自有批处理实现；未运行其旧版 Azure AgentPhD |
| Decision | 汇总提示与来源去重 | 汇总最新角色报告、逐主张判定和遗留问题；把重复同源证据与真正独立证据区分 | MDAgents 协作/协调机制参考 + 自有来源约束 |

`GROUNDED_DUTIES` 在 `oncofusion/protocols.py`。每个角色共用当前 API Provider，通过不同职责、输入和严格输出 schema 实现。分工本身的收益仍通过角色委派实验验证。

## 实际复制、依赖与机制参考

### GeneAgent

原研究是基因集功能解释，发表在 Nature Methods 2025。审阅了 `main_cascade.py`、`worker.py`、`topic.py` 和工具函数。整体代码绑定旧版 Azure OpenAI 调用与本地文件，直接替换病例 Agent 会引入不匹配的任务与运行依赖。

- 实际改编：`apis/get_pathway_for_gene_set.py` → `oncofusion/vendor/geneagent_enrichment.py`。
- 保留上游 `addList → 多个库 enrich` 流程；改用 HTTPS、超时、显式失败，保留原始与调整后 p 值、库名和重叠基因。
- 富集针对至少两个已审核基因；其结果是基因集上下文，不能作为患者通路激活或药物有效性的直接标签。
- 核验逻辑参考“自包含主张 → 原始来源核验 → 修订”，实现为预算内的批量结构化判定。
- NLM public-domain notice 完整保存在 `third_party/geneagent.LICENSE`。

### TxAgent / ToolUniverse

TxAgent 原版面向治疗推理，运行栈包含本地特定模型、vLLM 和 ToolRAG。这里复用其同源工具基础设施 ToolUniverse，继续使用用户的 API 模型。

`oncofusion/biomedical.py` 直接导入 `tooluniverse.ToolUniverse`，只载入六个上游工具：MyGene、Reactome、OncoTree、ChEMBL、OpenTargets、PubMed。关闭 workspace 加载和输出 hooks，执行前检查允许参数，原工具继续执行自身 schema 校验。网络或上游错误留为失败。

工具在独立的证据准备阶段调用；保存版本、参数、获取时间、响应和 SHA-256。`freeze_biomedical.py` 可以把这些响应接入明确的 synthesis 病例。CIViC-Fact 给定证据任务和 MTBBench 的封闭选择题保持原语料，避免通过外部资料引入答案。PubMed 附加资料按 PMID 分文档，只有实际摘要能够进入文献证据；元数据或获取失败的 stub 保留在原始快照中。

ToolUniverse 的精准肿瘤学 skill 含动态监管建议、固定药物映射和额外临床步骤。这次采用工具实现与检索原则，保持课程的证据整合任务。

### PaperQA / PaperQA2

审阅了 `src/paperqa/prompts.py` 与 RCS（相关性条件摘要）流程。直接复制 `summary_json_prompt` 和 `summary_json_system_prompt` 至 `oncofusion/vendor/paperqa_prompts.py`，Apache-2.0 原文随源码和 wheel 分发。

`grounded_v2_contexts` 对最多三个已检索原始片段分别调用同一个 Provider，返回相关摘要及 0–10 分。这些调用全部进入原预算与 usage；相关性高的反证仍保留。摘要在状态中标记 `model_generated_unverified`，原文仍是引用和核验依据。本轮未移植整个 PaperQA 搜索/embedding/外部元数据平台。

### MDAgents、Biomni 与图像病理系统

MDAgents 的任务复杂度分流、专业分工、协调汇总适合作为组织参考。本次审阅的仓库树未发现 LICENSE，因此采用机制参考和自有代码，不复制其实现。当前 `adaptive` 仅依据输入模态跳过空职责；它不是已复现的 MDAgents 复杂度分类器。

Biomni 的通用生物医学代码执行与大型工具环境覆盖更广，但当前受限语料任务以可审计的读操作为主，因此选用更小的 ToolUniverse 允许列表。PathChat/PathAsst 等图像系统需要图像输入和相应模型条件；当前 Pathology 的职责是病理语境，图像分析在接入真实切片任务时单独验证。

## 新工作流

```text
服务端限定当前可见资料
  → Literature：检索原始证据 [可选 PaperQA RCS]
  → Timeline：组织当前状态
  → Genomics：分子证据
  → Pathology：疾病/标本适用性
  → Drug：机制、敏感与耐药证据
  → Verifier：逐条核验 + 未解决事项
      ├─ 足够：Decision
      └─ 存在可检索缺口：定向文献补证 → 再核验 → Decision
```

LangGraph 真正执行各角色节点及条件边；一次补证节点调用 Literature 和 Verifier，共用现有预算。没有把整个旧流程封装成一个空图节点。`orchestrator=python` 提供同一新流程的逐事件等价参考。图不创建 checkpoint 存储、不反序列化客户端图状态；任务持久化继续由现有 Store 负责。

旧版把文献检索放在四个专业角色之后，纯文献输入时早期角色缺少原文。新版在专业判断之前准备可见原文，正是本轮最直接的流程修正。重新检索后，板上使用各角色最新报告，旧版本仍留在审计轨迹中。

## 核验记录的含义

`claim_id` 由主张和原始来源生成。核验目标按专业角色轮转取最多六条，剩余内容显式进入 `unreviewed_claims`。每个已选主张要求一个 `supported / contradicted / needs_revision / insufficient` 判定，并附理由；实质性判定须引用原文。漏项、重复 ID、伪造 ID 和无效引用触发错误。

模型判定是语义核验结果，引用字面校验是来源完整性结果，二者分别评价。模拟器始终把逐条判定标为 insufficient 并注明 SIMULATED，模拟通过不构成生物医学支持。CIViC-Fact 原生 SUPPORTS/REVISIONS/NEI 仍用于最终任务标签，两套词汇分别作用于主张审查与基准答案。

## 实验与采用条件

历史 25 个预设、41 个 treatment 的计划保留。`experiments/*_dev_upstream.json` 是独立开发集计划，比较旧版、工具型单 Agent、计算量对照、新版、RCS、角色委派与单机制关闭。使用相同模型、原语料、划分和预算上限，同时报告实际 tokens/调用数。RCS 增加调用，需要结合预算曲线解释。

工程采用条件：完整旧回归通过；新图与参考驱动等价；实际 SDK 与 HTTP 协议测试通过；版本、许可证和来源可追踪。质量采用条件：真实 API 开发集性能、引用语义支持率和成本符合项目目标。测试集继续使用冻结协议。

## 原始资料

- GeneAgent: https://www.nature.com/articles/s41592-025-02748-6 ; https://github.com/ncbi-nlp/GeneAgent
- TxAgent: https://arxiv.org/abs/2503.10970 ; https://github.com/mims-harvard/TxAgent
- ToolUniverse: https://github.com/mims-harvard/ToolUniverse
- PaperQA2: https://arxiv.org/abs/2409.13740 ; https://github.com/Future-House/paper-qa
- MDAgents: https://github.com/mitmedialab/MDAgents
- Biomni: https://github.com/snap-stanford/Biomni
- LangGraph: https://docs.langchain.com/oss/python/langgraph/workflows-agents

精确审阅 revision 和复用文件指纹见 `third_party/upstream-lock.json`。
