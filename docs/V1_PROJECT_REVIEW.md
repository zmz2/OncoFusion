# 第一版项目审查与收敛

审查起点：c33a7898864ec896df4d95f75ce88776b35b065b。目标：肿瘤异构生物医学证据的多智能体整合与核验。工程测试、数据适配、真实科学效果分别验收。

## 1. 题目与数据

患者级主评测继续采用 MTBBench 纵向文本任务，评测基因、病理语境与临床时间线整合后的问答。CIViC-Fact 是专业模块补充评测：一条原主张与一组证据的核验；独立段落检索评价 Literature。两者分表报告，均不以“最佳治疗方案”作为已有金标准。

这次确认原设计的任务适配风险：给定证据数据可以只有一个文献文档；强制七角色容易制造空任务。临床治疗史又常位于 clinical 类型，旧 adaptive 可能跳过 Drug。新版使用任务与可见输入决定适用性，并在轨迹、逐样本结果和数据审计中记录；缺失输入与阴性结果区分。

`claim_fields` 只读取原 claim.content 中的 molecularProfile/evidenceType/significance/therapies/disease（兼容旧名 diseases）。复杂分子组合完整保留；不把多基因组合强行压成单一变异。此处只提供结构化原主张，不读取标签、reviews、civic.description、revised_claim 或增强生成元数据。

先运行 `scripts/audit_dataset_scope.py`，核对真实模态和各角色适用样本数。主患者级数据需存在异构资料；单文献子任务只支持相应组件的结论。零适用样本的消融在报告中标记 N/A。单文献上的检索重排、没有临床记录时的时间线、复杂分子组合上的蛋白替换归一化，都应明确适用子集；用独立检索和原文抽样评审补充，而非强行宣称七项提升。

## 2. 稳妥的架构和复用

采用 LangGraph 执行的有界协调器—专业模块工作流：输入与可见性检查 → Literature（有文献时）→ Timeline/Genomics/Pathology/Drug（按适用性）→ Verifier → 有未读取文献且需要补证时一次回查 → Decision。

具体模块在 `specialists.py` 注册。各模块有稳定角色、允许的资料类型与适用条件，使用统一 provider、模型结构、来源校验和预算。专业角色委派给通用角色时保留相同资料视图。Drug 保守读取 clinical 治疗史。病理角色不会额外读取原始基因/药物数据；共享的临床背景与相关文献仍可访问。信号和证据板同步过滤，避免被排除资料通过预处理信号进入模型。

真实运行依赖：LangGraph 1.2.16、ToolUniverse 1.5.7、可选 medspaCy 1.3.1。medspaCy 的 ConText/TargetMatcher/PyRuSH 用于英语临床提及的否定、家族史、历史、假设及不确定属性，保留原文偏移；每个病例独立构建管线。它是规则型 NLP 工具，不是完整病理 Agent 或影像诊断模型。

GeneAgent 的外部查证、TxAgent 的药物证据检查、PaperQA2 的证据组织仍为方法适配。首版直接使用稳定工具组件和统一任务契约；完整复用这些 Agent 会带来不同任务、额外模型调用与依赖。已接入的组件有实际执行测试；尚未接入的完整 Agent 在清单中明示。真实模型效果比较前保留旧配置作为对照。

LangGraph 节点仍串行，补证最多一次。已有 SQLite 任务持久化保留；没有伪称支持节点级断点恢复、无限自主规划或自动治疗决策。ToolUniverse 只准备审核过的当前自定义研究查询快照，标准 benchmark 不接入实时知识。

## 3. 修复清单

| 风险 | 修复与验证 |
|---|---|
| 课程题目退化为泛化问答/疗法演示 | 患者级主任务与组件任务分层；synthesis 增加五项带引用的 integration 输出，缺证链节显式呈现 |
| 空任务和遗漏治疗史 | task_scoped 路由、模块资料视图和 input_scope 审计；Drug 接收 clinical |
| 预处理与证据板带入未分配资料 | 资料视图和 signals/board 同步过滤；future canary 和委派输入一致性测试 |
| 已无新证据仍花两次模型调用 | 受限语料没有未读文献时结束回查 |
| 选择题答案只检验全数据集选项并集 | 每道题独立校验金标准选项，付费推理前失败 |
| 同患者通过不同 gold group 跨分区 | 在选样、评测前验证 patient→group 一致性 |
| 截断/空内容的已报告 token 丢失 | ProviderError 携带可观测 usage，失败轨迹与费用仍计入；五项独立回归先复现后修复 |
| 未审核数据允许远程模型处理 | API/Engine/批量评测入口检查 data_class；API 仍要求远程处理同意 |
| 推荐图配置在默认容器缺依赖 | Docker 使用与上游验收一致的 Python 3.11，安装 graph/clinical；容器测试实际调用 recommended_config |
| 成熟工具组合安装的二进制兼容风险 | 真实 CI 复现 NumPy ABI 冲突；临床环境固定 NumPy1.26.4/spaCy3.7.5/Thinc8.2.5，ToolUniverse 单独准备 JSON 快照，各环境独立执行 CI |
| 原文档示例与真实 CIViC claim 结构不同 | 全量数据元结构审计后适配原生 type=claim 对象（兼容旧 table）、字典 content、disease 单数及 therapies 列表；保留旧对照格式并测试原字段白名单 |
| 接手清单过大、先跑数千次实验 | 先2组×4系统×1次开发集 pilot，随后按适用范围做逐角色消融；旧完整计划继续保留 |

## 4. 发布前仍需的真实验收

模型供应商尚未调用真实 API。Codex 需要固定供应商/模型/参数，先跑小型 pilot，记录结构通过率、错误率、预算耗尽、成本和延迟，再复核原文语义支持。模拟正确率不用于课程性能结论。

基因通路成员关系、具体变异功能、样本通路活动和药物反应分别判断。临床 NLP 的规则属性、关键词方向和字符归一化均是辅助特征，不能单独产生临床结论。中文报告与病理影像属于后续独立扩展。

共享 Bearer 当前提供单团队访问。网页公开给互不信任的多个用户前，新增身份、数据所有权、删除策略与部署限额；真实病例上传须由数据所有者完成脱敏和授权。现阶段示例和公开去标识化数据即可覆盖开发。

软件回归与依赖执行结果见 verification/V1_REVIEW.md；真实效果与人工引用评审按 TASK.md 交接。

## 原始参考

- LangGraph workflow patterns: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- Supervisor/subagents: https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- medspaCy: https://github.com/medspacy/medspacy ，https://pypi.org/project/medspacy/1.3.1/
- ToolUniverse SDK: https://zitniklab.hms.harvard.edu/ToolUniverse/guide/python_guide.html
- GeneAgent: https://www.nature.com/articles/s41592-025-02748-6
- PaperQA2: https://github.com/Future-House/paper-qa
- MTBBench: https://github.com/bunnelab/mtbbench
- CIViC-Fact: https://github.com/creisle/civicfact

## 实际依赖隔离

临床推理使用 `.[dev,graph,clinical]`；来源准备另建 `.venv-tools` 安装 `.[dev,graph,biomedical]`。前者固定已验证的 NumPy 1 ABI，后者使用 ToolUniverse 的 NumPy 2 依赖。两个环境只通过审核后的 JSON 快照衔接，均执行真实包导入和回归。联合安装时依赖解析明确报冲突，避免“安装成功、运行时崩溃”。

## 真实输入覆盖与预算预检

全量 MTBBench 183 道题中，152 道具备至少两类资料，其余31道为临床文本；主数据无独立文献文档，Literature 在该分支标记不适用，使用 CIViC 独立文章内检索验证。每个角色的作用按对应子集报告。

首版四种对照在14道开发题的模拟联调中，单Agent迭代对照出现2次120,000预算预检终止，其他组完整返回。首版所有组统一调整到200,000预算上限，保留原始失败记录与旧120,000对照；真实API仍先小样本测量成本和上下文上限。模拟预检通过只验证执行流程，不等于真实准确率或费用。
