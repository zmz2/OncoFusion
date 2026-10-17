# 第一版范围与风险审查

审查基线：`c33a7898864ec896df4d95f75ce88776b35b065b`。本轮以课程题目一致性、模块复用、评测隔离及简单可靠的运行路径为优先级。

## 第一版定案

**课题：肿瘤异构生物医学证据的多智能体整合与核验。**

采用 LangGraph 固定专家工作流、统一模型 API、共享结构化证据、独立核验与最终协调。基础结构是预定义 specialist workflow，而非自由调度的自治群体。第一版固定七角色、串行执行、零自动回查；通常七次模型调用。每个角色可单独委派或关闭内部机制。LangGraph 实际执行节点；原生执行器用于等价回归和轻量离线测试。

链路：输入与阶段检查 → 文献证据汇集 → 时间线 → 基因 → 病理语境 → 药物证据 → 核验 → 决策。研究输出为答案、来源引用、适用条件与未解决问题。七角色分工保留，但解释性链条中的每一步需要相应资料；缺失的通路功能或临床疗效证据留为未知。

模型推理和工具采用分层设计：核心 Agent 读取封闭的来源集合；ToolUniverse 在运行前根据审核过的公开实体查询准备快照。首版的网络来源由操作者明确选择和冻结，所有对照共用。这样角色比较不会同时混入不同的工具访问权限和时点。

## 明显风险与处置

| 风险 | 实际问题 | 本轮处置与剩余边界 |
|---|---|---|
| 题目与标签错位 | MTBBench 标签衡量病例问答；CIViC 标签衡量主张核验。两者都没有为每位患者标注唯一最佳治疗 | MTBBench 为病例整合主任务，CIViC 为证据核验组件任务；分别报告。药物关系输出保留证据终点，项目成绩不解释成治疗推荐有效率 |
| 角色有名无可测输入 | 部分病例缺少某模态；给定证据核验通常只有一份文献 | 增加输入覆盖审计和 `/v1/cases/inspect`；报告各角色结构化输入覆盖数。人工确认适用子集；单文献数据上的检索重排交给独立检索任务评测 |
| 架构和实验过早扩张 | 默认旧版仍有回查；一次执行几十配置难以定位成本和质量问题 | 明确 `v1` 配置；先3个系统×1次×3个组，接通后再11配置×3次。旧25/41/24配置保留为后续实验资料 |
| 将提示参考误称完整Agent复用 | 原七角色仍是自有节点+统一模型，GeneAgent、PaperQA2没有完整加载 | 保持精确复用清单：LangGraph、ToolUniverse为运行依赖；专业方法属于适配。原论文性能不迁移为本项目性能 |
| 通路步骤缺工具 | 原SDK白名单没有专门的通路查询 | 实际接入 ToolUniverse 的 Reactome protein→pathways 与 pathway详情工具；共7项只读工具。成员关系不等于患者通路激活 |
| 重复证据占满检索名额 | 原代码先top-k后去重，可把另一条来源挤掉 | 检索前先按原始来源+原文内容去重；消融关闭时保留原行为。不同段落不合并 |
| 补证耗尽最终回答预算 | 初轮证据已经得到，但额外两次模型调用可使Decision无法执行 | 第一版关闭补证；旧回查配置增加模型/工具/估算token预留检查，预算不足时记录 `requery_skipped` 后汇总现有证据 |
| 核验标签只告知最终决策 | 专家Analysis原始schema可提示错误的REFUTES词表 | 原生标签定义送给全部角色，Analysis schema同步约束；两种词表分别评测 |
| 同患者分组别名漏检 | 仅检查Gold group，调用者能把同患者阶段标成两个group跨划分 | 在加载、选择和评测前联合校验Case patient_id与Gold group，拒绝一患者多组；每题gold也检查自己的选项集合 |
| JSON修复实为盲重试 | 原修复请求没有带回失败原文和具体错误 | 传入有界原始输出及去除输入回显的校验错误；仍按统一模型预算计费。正式比较采用相同修复设置 |
| 截断响应费用遗漏 | HTTP200但finish_reason=length时先报错，已经返回的usage丢失 | 先解析usage，再检查正文；失败轨迹保留已报告token，已知费用继续计入。未返回usage的请求保留不完整费用标志 |
| 安装、隐私、网页状态 | 未装图依赖也能创建任务；未审核上传可被明确同意标志绕过；证据图没有最终决策 | 创建任务前校验依赖与data_class；未审核资料先人工脱敏；图补最终答案及直接引用。保留幂等与SSE |
| 工程测试被当成科学结果 | 模拟器按固定规则作答，无法验证专业提示的医学价值 | 所有模拟报告保留simulated。真实API、语义引用双人审查与消融结果仍是科学验收必需项 |

## 组件选择与复用层级

| 层 | 第一版采用 | 直接复用/保留的理由 |
|---|---|---|
| 多Agent编排 | LangGraph `StateGraph` | 用上成熟的固定工作流与条件节点接口；不重复造执行框架 |
| 生物医学查询 | ToolUniverse固定版本SDK、7项白名单 | 共用真实参数定义与执行实现；hooks/workspace自动加载关闭 |
| 通路资料 | Reactome，通过ToolUniverse | 补齐基因到通路的可追溯资料来源；只用于适用的固定快照扩展 |
| 专家语义方法 | GeneAgent、TxAgent、PaperQA2相关检查清单 | 适配课程输入和证据标签，保留统一模型与调用预算 |
| 检索 | 当前本地BM25+实体重排 | 透明可测基线；完整PaperQA2接入是未来可选项，需统一额外模型/embedding费用与语料约束 |
| 数据 | 固定MTBBench文本、CIViC-Fact原生版本、独立段落检索 | 复用已有标签、原始来源与分组；首版不新增自制医学gold |
| 评测/服务 | OncoFusion现有模块 | 标签隔离、引用偏移、成本、SQLite、幂等、SSE保留 |

选择依据是任务匹配和工程复杂度，而非声称自有Agent在医学性能上超过原项目。ToolUniverse是工具库，LangGraph是编排框架；七个专业角色仍是我们的应用适配节点。`THIRD_PARTY.md`、`upstream_manifest.json`记录出处。

## 数据与论文结论的边界

MTBBench主结果为逐阶段Accuracy、患者平均表现和成本。CIViC-Fact为原生三分类，当前固定词表为SUPPORTS/REVISIONS/NEI。独立段落检索使用已有人工跨度构造的本项目评测适配，排除项和实际分母留在审计中。其成绩不冒充不同版本论文的同协议排行榜。

输入覆盖是结构统计：同一文献可能叙述多个生物医学领域，也可能没有足够病例事实。`explicit_role_inputs`既不证明Agent有效，也不决定自动跳过角色。它只帮助提前发现任务与角色不匹配。七项机制分别映射基因、病理语境、药物方向、文献重排、时间整理、核验和最终来源去重；相应机制在适用任务上评测。若统计贡献为零，报告零并解释覆盖和职责重叠。

新增 `synthetic-integration` 覆盖五类来源、两份文献，所有基因/药物关系均标为虚构，仅用于端到端工程展示。真实模型试验采用正式数据；人工病例需要审核、去标识化，并明确外发同意。数据class是操作者声明，系统没有自动完成医学去标识化审查。

首版为可信研究工作区：同一Bearer令牌共享病例与任务，尚无多用户访问隔离；保留单ASGI进程。公开网页多用户、病理图像、持久化graph checkpoint、在线自主工具规划均后置。

## 一手参考

- LangGraph工作流与Agent：https://docs.langchain.com/oss/python/langgraph/workflows-agents
- 简单可组合的Agent架构：https://www.anthropic.com/engineering/building-effective-agents
- MTBBench论文：https://arxiv.org/abs/2511.20490
- CIViC-Fact数据代码：https://github.com/creisle/civicfact
- ToolUniverse SDK：https://zitniklab.hms.harvard.edu/ToolUniverse/guide/python_guide.html
- 本轮核查Reactome配置：https://github.com/mims-harvard/ToolUniverse/blob/9f6b13919394393311d355c0b2376db63c7ab452/src/tooluniverse/data/reactome_tools.json

代码测试与实际结果由 `verification/V1_AUDIT.md` 和对应CI报告记录。
