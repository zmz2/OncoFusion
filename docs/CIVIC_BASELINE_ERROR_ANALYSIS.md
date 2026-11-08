# CIViC-Fact 旧版 150 例错误分析

本文件仅使用 `results/v1/civic_test150_frozen_20261108/` 中已有的 300 次执行，
没有新增模型调用。旧成绩保留原口径，不再作为新方法的独立测试集。

## 混淆矩阵

| Gold | 多 Agent SUPPORTS | 多 Agent REVISIONS | 多 Agent NEI | 单 Agent SUPPORTS | 单 Agent REVISIONS | 单 Agent NEI / failed |
|---|---:|---:|---:|---:|---:|---:|
| SUPPORTS | 30 | 14 | 6 | 35 | 11 | 3 + 1 failed |
| REVISIONS | 7 | 14 | 29 | 9 | 19 | 22 |
| NEI | 2 | 1 | 47 | 5 | 0 | 45 |

多 Agent 的 REVISIONS 召回为 0.28。主要方向是 REVISIONS→NEI（29/50），
其次是 SUPPORTS→REVISIONS（14/50）和 REVISIONS→SUPPORTS（7/50）。
单 Agent 也有同一方向，但 REVISIONS→NEI 为 22/50。

## 互补性与配对

“至少一个系统正确”的比例为 74.7%，只作为诊断上限。

- 单 Agent 正确、多 Agent 错误：21/150。
- 多 Agent 正确、单 Agent 错误：13/150。
- 两系统都错：37/150；其中 22 例同时预测 NEI，6 例同时预测 SUPPORTS，
  4 例同时预测 REVISIONS，5 例两系统给出不同的错误标签。

## 已确认的机制问题

### 1. 局部证据方向与全局 stance 标签混淆

`civic-ecce754b-5c30-4ef5-bb73-9f2c6c5baabe`，gold REVISIONS。
原文报告 gilteritinib 在 FLT3-D835Y 细胞模型中具有抑制活性；原主张却写成
“resistance”。Drug 与单 Agent 都提出了正确的最小修订：把 resistance 改为
sensitivity/activity。多 Agent 的 Decision 又将该局部方向冲突解释为整题 NEI。

首次出错节点：Decision 把“证据不支持 significance=resistance”放大成
“证据与主张无关”，而原始证据明显与分子、药物和疾病相关。

建议修改：Decision 分开判断 evidence relevance、原主张是否完整成立和需修订字段；
相关且需字段修正时映射为 REVISIONS，不按局部 claim 方向改写整题。

### 2. 疾病特异性修正被当作无关证据

`civic-9b2778b5-e8d6-4b8b-8b07-650584fb0de0`，gold REVISIONS。
原文研究 NSCLC 中 RRM1 与 gemcitabine 的关系；原主张把癌种写成
pulmonary large cell neuroendocrine carcinoma。Literature、Genomics、Drug
均已识别“方向相符、癌种需要修订”，Verifier 也复述了这一修正，
但 Decision 输出 NEI。

这是“相关但原主张未完全成立”的典型 REVISIONS，不是证据缺失。

### 3. 不适用角色被错误当成整题证据不足

`civic-d4af9bd4-1bff-4a52-aac3-3cdae011c69f`，gold REVISIONS。
Timeline、Genomics、Pathology 在单文献任务中正确登记 not_applicable。
Decision 将局部 not-applicable 与特定 histology/significance 缺口叠加，
把本可修订的临床关系压成 NEI。

角色不适用只说明该专业层没有独立输入，不能证明原主张与文献无关。

### 4. Verifier 往往确认“局部陈述”，没有产出最终字段修订

多 Agent 的 Verifier 会确认 literature/genomics/drug 对原文的局部描述，
但最终标签仍依赖 Decision。例如 `ecce754b...` 的 Drug claim 已标 REVISIONS，
Verifier 又把具体的局部陈述确认为支持，却没有携带
“resistance→sensitivity”的最小全局修订进入 Decision。

需要把逐条核验与全局最小修订显式连接，保留来源，不用多数投票。

### 5. 单 Agent 也会过度扩展或过度保守

`civic-0af63c56-f250-4474-91fd-eb5fe7daa4e4`，gold SUPPORTS。
文献研究 EZH2 Y641 hotspot，原主张写 Y646。单 Agent 假定 Y646 是 Y641 的
异名/笔误并输出 SUPPORTS；多 Agent 严格区分两个残基并输出 NEI。
这是需要数据中真实同义关系或明确字段修订的边界案例，不能仅靠保守提示词解决。

`civic-ae71c1dd-b117-484f-8e06-f2110a575e05`，gold REVISIONS。
原文支持 platinum sensitivity；主张使用更宽的 DNA Adduct Forming Agent。
单 Agent 正确要求收窄 therapy，多 Agent 将 platinum 直接扩展为 broader class 后
输出 SUPPORTS。Drug 的适用范围检查不足。

## 优先级

1. 在 Decision 中加入独立的 revision assessment，固定标签映射，先把
   “相关证据＋局部字段错误”保留为 REVISIONS。
2. 在 Drug 和 Pathology 中显式要求最小字段修订，尤其 therapy class、
   disease specificity、direction 和 endpoint。
3. Verifier 把局部核验转成有来源的最小修订，并明确不适用角色与全局缺证的边界。
4. 在 60 条 dev 上先检验第一项；只有净纠错收益和一致接口通过后，再叠加后两项。

## 为什么先不改提示词堆叠

当前失败已呈现稳定的语义模式：局部证据相关、具体字段错误，但整题被压成 NEI。
新增更多“谨慎”措辞会增加 NEI 偏好。先改变状态表示和标签映射，能让错误进入
可测试的结构，再讨论角色提示优化。
