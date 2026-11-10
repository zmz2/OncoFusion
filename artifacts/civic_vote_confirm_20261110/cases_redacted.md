# 课堂案例（脱敏公开版）

按固定名单顺序，选择有至少三张有效专业票、且精确来源已核实为可再发布 CC BY 许可的未仲裁案例；再选一个不同来源的实际仲裁案例。为减少病例细节暴露，跳过含年龄的摘录。以下是过程示例，不用于替代总体统计。

## 专业投票示例

### civic-3afae4ed-1396-442c-8f64-3cfa15c62f5b

- 队列：previously_unused；来源 PMID：26445453。
- 待核验主张（原始字段）：
```json
{
  "disease": "Alveolar Rhabdomyosarcoma",
  "evidenceDirection": "SUPPORTS",
  "evidenceType": "PREDICTIVE",
  "molecularProfile": "MET Overexpression AND ALK Overexpression",
  "significance": "sensitivity/response",
  "therapies": [
    "Crizotinib"
  ],
  "variantOrigin": "N/A"
}
```
- 主张中文释义（据原字段直译，非模型输出）：疾病：肺泡型横纹肌肉瘤；证据方向：支持；证据类型：预测性；分子特征：MET 和 ALK 过表达；临床意义：敏感/应答；治疗药物：克唑替尼；变异来源：不适用
- 专业角色：literature, genomics, pathology, drug；选票分布：SUPPORTS 4.
- 初始等权标签：SUPPORTS；仲裁触发：否；仲裁状态：not_triggered。
- 仲裁前/后：SUPPORTS → SUPPORTS；最终标签：SUPPORTS；参考标签：NEI；评测命中：否。
- 仲裁输入与结论：未触发仲裁。
- 原文摘录：“In vitro treatment with crizotinib inhibited ALK and MET proteins, as well as Insulin-like Growth Factor 1 Receptor (IGF1R), with a concomitant …”
- 来源归属：作者：Megiorni F et al.；《Crizotinib-induced antitumour activity in human alveolar rhabdomyosarcoma cells is not solely dependent on ALK and MET inhibition》，PMID 26445453，[PMC全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC4596370/)（[PubMed](https://pubmed.ncbi.nlm.nih.gov/26445453/)）；许可：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。摘录已截短，省略处以省略号标示。
- 摘录中文释义（人工直译，非模型输出）：体外使用克唑替尼处理，抑制了 ALK、MET 蛋白以及胰岛素样生长因子 1 受体（IGF1R），并伴随……
- 角色简短依据（模型原始短输出，公开版截短）：
  - literature: SUPPORTS；依据：The provided evidence demonstrates that crizotinib impairs RMS cell growth and inhibits ALK and MET proteins, confirming therapeutic sensitivity. It also explicitly states that RT-PCR analysis shows ALK and MET mRNAs are expressed at significantly higher levels in ARMS compared to ERMS, directly supporting the claim for MET and ALK overexpression in this …
  - genomics: SUPPORTS；依据：The evidence demonstrates that crizotinib inhibits ALK and MET signaling and impairs RMS cell growth, and explicitly confirms that ALK and MET mRNA expression is significantly higher in ARMS versus ERMS, thereby supporting the predictive claim for crizotinib sensitivity in ARMS with co-overexpression.
  - pathology: SUPPORTS；依据：The supplied evidence directly supports the claim. In vitro treatment with crizotinib impaired RMS cell growth and induced G2/M phase accumulation, demonstrating therapeutic sensitivity. Additionally, RT-PCR analysis confirmed that ALK and MET mRNAs are expressed at significantly higher levels in ARMS compared to ERMS, supporting the overexpression of these …
  - drug: SUPPORTS；依据：In vitro evidence demonstrates that crizotinib impairs RMS cell growth and inhibits ALK and MET proteins. Furthermore, ALK and MET mRNA levels are significantly higher in ARMS compared to ERMS, directly supporting the predictive sensitivity claim for the specified molecular profile.

## 实际触发仲裁示例

### civic-29f6251a-0933-4273-b4d2-9698caaf1c0f

- 队列：previously_unused；来源 PMID：26689995。
- 待核验主张（原始字段）：
```json
{
  "disease": "lung adenoid cystic carcinoma",
  "evidenceDirection": "DOES_NOT_SUPPORT",
  "evidenceType": "PREDICTIVE",
  "molecularProfile": "ERBB3 V737E",
  "significance": "sensitivity/response",
  "therapies": [
    "Afatinib",
    "Pertuzumab"
  ],
  "therapyInteractionType": "SUBSTITUTES",
  "variantOrigin": "SOMATIC"
}
```
- 主张中文释义（据原字段直译，非模型输出）：疾病：肺腺样囊性癌；证据方向：不支持；证据类型：预测性；分子特征：ERBB3 V737E；临床意义：敏感/应答；治疗药物：阿法替尼, 帕妥珠单抗；药物关系：替代；变异来源：体细胞
- 专业角色：literature, genomics, pathology, drug；选票分布：NEI 2, REVISIONS 2.
- 初始等权标签：REVISIONS；仲裁触发：是；仲裁状态：completed。
- 仲裁前/后：REVISIONS → REVISIONS；最终标签：REVISIONS；参考标签：REVISIONS；评测命中：是。
- 仲裁输入：原始主张、允许证据、全部专业选票及其简短依据；仲裁记录的证据编号：pmid-26689995:f01。
- 仲裁结论与依据（模型保存解释）：The supplied evidence evaluates the efficacy of Afatinib and Pertuzumab against the HER3 V855A somatic mutation in non-small cell lung cancer (NSCLC). This directly contradicts the claim's specified molecular profile (ERBB3 V737E) and disease context (lung adenoid cystic carcinoma). While the gene and therapies align, the specific variant and pathology are mismatched. The claim requires revision to align with the documented V855A mutation in NSCLC.
- 原文摘录：“Here, we report a case of an advanced chemotherapy-resistant NSCLC, harboring a novel HER3V855A somatic mutation . . . Afatinib and pertuzumab …”
- 来源归属：作者：Umelo I, Noeparast A, Chen G, et al.；《Identification of a novel HER3 activating mutation homologous to EGFR-L858R in lung cancer》，PMID 26689995，[PMC全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC4823091/)（[PubMed](https://pubmed.ncbi.nlm.nih.gov/26689995/)）；许可：[CC BY 2.5](https://creativecommons.org/licenses/by/2.5/)。摘录已截短，省略处以省略号标示。
- 摘录中文释义（人工直译，非模型输出）：本文报告一例晚期、化疗耐药的非小细胞肺癌病例，携带一种新型 HER3 V855A 体细胞突变……（后文省略）。
- 角色简短依据（模型原始短输出，公开版截短）：
  - literature: REVISIONS；依据：The supplied evidence evaluates Afatinib and Pertuzumab against the HER3 V855A somatic mutation in NSCLC, not ERBB3 V737E in lung adenoid cystic carcinoma. The claim's disease and molecular qualifiers are mismatched with the experimental context, requiring revision to align with the documented variant and pathology.
  - genomics: NEI；依据：The supplied evidence describes a somatic HER3 V855A mutation in NSCLC and demonstrates Afatinib/Pertuzumab efficacy against this specific mutant. It does not address the claimed ERBB3 V737E variant in lung adenoid cystic carcinoma, making the evidence insufficient to support or contradict the specific claim.
  - pathology: REVISIONS；依据：The supplied evidence describes an ERBB3 (HER3) V855A somatic mutation in non-small cell lung cancer (NSCLC), which contradicts the claim's specified disease (adenoid cystic carcinoma) and variant (V737E). While afatinib and pertuzumab demonstrate efficacy against the reported HER3-V855A mutation, the claim's specific pathological and molecular details are …
  - drug: NEI；依据：The supplied evidence describes in vitro sensitivity of afatinib and pertuzumab to the HER3 V855A mutation in NSCLC, which does not match the claimed ERBB3 V737E variant or lung adenoid cystic carcinoma disease context. No evidence addresses the specific claim.
