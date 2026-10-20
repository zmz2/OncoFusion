# 六例课堂样例：机械定位核对

生成方式同验收文件；“逐字命中”指引用 quote 与 `document_id[start:end]` 完全相等，不涉及语义是否支持结论。语义层面的逐条判断在 `results/SEMANTIC_CHECK_CLASS6_AI.md`（由代理逐条阅读后填写，明确标注为 AI 辅助，不是人工评审；无引用的主张记 N/A）。

## mtb-P-0006191-q0 · MTBBench dev 课堂样例 · 现行配置（4 问 · 3 位患者）

问题：Given that the patient is 56.1 years old, will the cancer have a recurrence in the next 12 months?

- 状态 completed；答案 B，标签 A；调用 7，51280 in + 16809 out token，1347.8 秒。
- 决策解释：Finding 1 (temporal status; measured; present): The latest visible dated observation is at age 56.082, where the CT record reports HAS CANCER: No and states that the cancer has NOT progressed; this is the most recent measured status before the requested 12-month window. Citations: file-e6d046651c468858ce2d:f07. Finding 2 (historical course; measured; present): The visible timeline records primary 

| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |
| --- | --- | --- | --- | --- | --- |
| `literature-01` | 文献证据 | 资料来源 | context-0 -1-277 | 逐字命中 | The patient is a 55-year-old White female with a diagnosis of lung adenocarcinoma. She ide |
| `literature-02` | 文献证据 | 资料来源 | file-e6d046651c468858ce2d 743-1342 | 逐字命中 | AGE: 55.293, samples > clinical_sample --> SAMPLE_ID: P-0006191-T01-IM5, PATIENT_ID: P-000 |
| `literature-02` | 文献证据 | 资料来源 | file-e6d046651c468858ce2d 2974-3280 | 逐字命中 | AGE: 56.082, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `literature-03` | 文献证据 | 资料来源 | N/A（该主张没有引用） | N/A |  |
| `timeline-01` | 病例时间线 | 时间与事件 | file-e6d046651c468858ce2d 1342-1799 | 逐字命中 | Other Types Of Carcinoma, DIAGNOSIS_DESCRIPTION: Lung and Bronchus, TMB_NONSYNONYMOUS: 2.9 |
| `timeline-01` | 病例时间线 | 时间与事件 | file-e6d046651c468858ce2d 2399-2974 | 逐字命中 | AGE: 55.427, treatment > treatment --> STOP_AGE: 55.5995, SUBTYPE: Chemo, AGENT: PEMETREXE |
| `timeline-02` | 病例时间线 | 时间与事件 | file-e6d046651c468858ce2d 2974-3280 | 逐字命中 | AGE: 56.082, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `timeline-03` | 病例时间线 | 时间与事件 | N/A（该主张没有引用） | N/A |  |
| `genomics-01` | 基因与通路 | 分子与变异 | file-e6d046651c468858ce2d 743-1342 | 逐字命中 | AGE: 55.293, samples > clinical_sample --> SAMPLE_ID: P-0006191-T01-IM5, PATIENT_ID: P-000 |
| `genomics-01` | 基因与通路 | 分子与变异 | file-e6d046651c468858ce2d 1342-1799 | 逐字命中 | Other Types Of Carcinoma, DIAGNOSIS_DESCRIPTION: Lung and Bronchus, TMB_NONSYNONYMOUS: 2.9 |
| `genomics-02` | 基因与通路 | 分子与变异 | N/A（该主张没有引用） | N/A |  |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-e6d046651c468858ce2d 743-1342 | 逐字命中 | AGE: 55.293, samples > clinical_sample --> SAMPLE_ID: P-0006191-T01-IM5, PATIENT_ID: P-000 |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-e6d046651c468858ce2d 1342-1799 | 逐字命中 | Other Types Of Carcinoma, DIAGNOSIS_DESCRIPTION: Lung and Bronchus, TMB_NONSYNONYMOUS: 2.9 |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-e6d046651c468858ce2d 743-1342 | 逐字命中 | AGE: 55.293, samples > clinical_sample --> SAMPLE_ID: P-0006191-T01-IM5, PATIENT_ID: P-000 |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-e6d046651c468858ce2d 1342-1799 | 逐字命中 | Other Types Of Carcinoma, DIAGNOSIS_DESCRIPTION: Lung and Bronchus, TMB_NONSYNONYMOUS: 2.9 |
| `pathology-03` | 病理与癌种语境 | 病理与癌种 | N/A（该主张没有引用） | N/A |  |
| `drug-01` | 药物关系 | 既往用药 | file-e6d046651c468858ce2d 2399-2974 | 逐字命中 | AGE: 55.427, treatment > treatment --> STOP_AGE: 55.5995, SUBTYPE: Chemo, AGENT: PEMETREXE |
| `drug-02` | 药物关系 | 药物关系 | N/A（该主张没有引用） | N/A |  |
| `drug-03` | 药物关系 | 既往用药 | N/A（该主张没有引用） | N/A |  |
| `verifier-01` | 主张核验 | 核验 | file-e6d046651c468858ce2d 2974-3280 | 逐字命中 | AGE: 56.082, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `verifier-02` | 主张核验 | 资料来源 | N/A（该主张没有引用） | N/A |  |
| `verifier-03` | 主张核验 | 核验 | file-e6d046651c468858ce2d 743-1342 | 逐字命中 | AGE: 55.293, samples > clinical_sample --> SAMPLE_ID: P-0006191-T01-IM5, PATIENT_ID: P-000 |
| `verifier-03` | 主张核验 | 核验 | file-e6d046651c468858ce2d 1342-1799 | 逐字命中 | Other Types Of Carcinoma, DIAGNOSIS_DESCRIPTION: Lung and Bronchus, TMB_NONSYNONYMOUS: 2.9 |

## mtb-P-0022916-q2 · MTBBench dev 课堂样例 · 现行配置（4 问 · 3 位患者）

问题：Given that the patient is 57.8 years old, will the cancer progress in the next 12 months?

- 状态 completed；答案 A，标签 A；调用 7，111152 in + 17575 out token，1315.8 秒。
- 决策解释：The visible record supports a prediction of progression over the next 12 months, but with explicit uncertainty because no post-57.8 outcome is visible. The documented history is bounded at age 57.8, and the latest visible observation is CEA 2.0 ng/mL at 57.765, so the future outcome is not directly measured. The strongest source-grounded premise is that this patient has already had recurrent/metas

| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |
| --- | --- | --- | --- | --- | --- |
| `literature-01` | 文献证据 | 资料来源 | context-0 -1-372 | 逐字命中 | The patient is a 54.8-year-old White female of non-Hispanic ethnicity with a diagnosis of  |
| `literature-01` | 文献证据 | 资料来源 | context-3 -1-248 | 逐字命中 | The patient has experienced a recurrence of cancer within 9 months. A detailed medical his |
| `literature-02` | 文献证据 | 资料来源 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |
| `literature-02` | 文献证据 | 资料来源 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `literature-03` | 文献证据 | 资料来源 | file-ab603d3661c049070b15 1551-2143 | 逐字命中 | AGE: 56.883, labtest > cea_labs --> CEA: 4.7000 ng/ml           AGE: 57.108, diagnosis > c |
| `literature-03` | 文献证据 | 资料来源 | file-ab603d3661c049070b15 5921-5985 | 逐字命中 | AGE: 57.765, labtest > cea_labs --> CEA: 2.0000 ng/ml            |
| `timeline-01` | 病例时间线 | 时间与事件 | context-0 -1-372 | 逐字命中 | The patient is a 54.8-year-old White female of non-Hispanic ethnicity with a diagnosis of  |
| `timeline-01` | 病例时间线 | 时间与事件 | context-3 -1-248 | 逐字命中 | The patient has experienced a recurrence of cancer within 9 months. A detailed medical his |
| `timeline-02` | 病例时间线 | 时间与事件 | file-ab603d3661c049070b15 1551-2143 | 逐字命中 | AGE: 56.883, labtest > cea_labs --> CEA: 4.7000 ng/ml           AGE: 57.108, diagnosis > c |
| `timeline-02` | 病例时间线 | 时间与事件 | file-ab603d3661c049070b15 3113-3678 | 逐字命中 | AGE: 57.195, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `timeline-03` | 病例时间线 | 时间与事件 | file-ab603d3661c049070b15 5921-5985 | 逐字命中 | AGE: 57.765, labtest > cea_labs --> CEA: 2.0000 ng/ml            |
| `timeline-03` | 病例时间线 | 时间与事件 | context-3 -1-248 | 逐字命中 | The patient has experienced a recurrence of cancer within 9 months. A detailed medical his |
| `genomics-01` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `genomics-02` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 566-1002 | 逐字命中 | DOT1L,0,MSKCC,GRCh37,19,2210451,2210451,+,missense_variant,Missense_Mutation,SNP,C,C,T,P-0 |
| `genomics-02` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 1002-1434 | 逐字命中 | BLM,0,MSKCC,GRCh37,15,91306247,91306247,+,missense_variant,Missense_Mutation,SNP,A,A,G,P-0 |
| `genomics-03` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `genomics-03` | 基因与通路 | 分子与变异 | context-3 -1-248 | 逐字命中 | The patient has experienced a recurrence of cancer within 9 months. A detailed medical his |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-88cacc98f0b9ef7d5a14 582-1021 | 逐字命中 | "ICD_O_HISTOLOGY_DESCRIPTION": "Adenocarcinoma In Polyp,Nos", "DIAGNOSIS_DESCRIPTION": "Re |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `pathology-03` | 病理与癌种语境 | 病理与癌种 | N/A（该主张没有引用） | N/A |  |
| `drug-01` | 药物关系 | 既往用药 | file-ab603d3661c049070b15 3113-3678 | 逐字命中 | AGE: 57.195, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `drug-02` | 药物关系 | 药物关系 | N/A（该主张没有引用） | N/A |  |
| `verifier-01` | 主张核验 | 资料来源 | context-3 -1-248 | 逐字命中 | The patient has experienced a recurrence of cancer within 9 months. A detailed medical his |
| `verifier-01` | 主张核验 | 资料来源 | file-ab603d3661c049070b15 5921-5985 | 逐字命中 | AGE: 57.765, labtest > cea_labs --> CEA: 2.0000 ng/ml            |
| `verifier-02` | 主张核验 | 核验 | file-ab603d3661c049070b15 1551-2143 | 逐字命中 | AGE: 56.883, labtest > cea_labs --> CEA: 4.7000 ng/ml           AGE: 57.108, diagnosis > c |
| `verifier-02` | 主张核验 | 核验 | file-ab603d3661c049070b15 2143-2652 | 逐字命中 | AGE: 57.118, diagnosis > cancer_presence --> HAS CANCER: Yes, SUBTYPE: HasCancer, PROCEDUR |
| `verifier-03` | 主张核验 | 核验 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `verifier-03` | 主张核验 | 核验 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |

## mtb-P-0022916-q6 · MTBBench dev 课堂样例 · 现行配置（4 问 · 3 位患者）

问题：Given that the patient is 60 years old, will the patient be still alive in the next 12 months?

- 状态 completed；答案 A，标签 A；调用 7，127960 in + 15798 out token，1109.1 秒。
- 决策解释：Adopted claim ids: timeline-01, timeline-02, timeline-03, verifier-01, verifier-02, literature-02. Excluded claim ids: none. Finding 1 (scope: temporal; evidence level: measured; material status: present): the latest visible dated observations are CT no cancer/no progression at age 59.735 and CEA 1.5 ng/mL at age 59.951, with no visible dated record after age 59.951, so the post-60 outcome is not 

| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |
| --- | --- | --- | --- | --- | --- |
| `literature-01` | 文献证据 | 资料来源 | context-0 -1-372 | 逐字命中 | The patient is a 54.8-year-old White female of non-Hispanic ethnicity with a diagnosis of  |
| `literature-01` | 文献证据 | 资料来源 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |
| `literature-02` | 文献证据 | 资料来源 | file-ab603d3661c049070b15 1551-2143 | 逐字命中 | AGE: 56.883, labtest > cea_labs --> CEA: 4.7000 ng/ml           AGE: 57.108, diagnosis > c |
| `literature-02` | 文献证据 | 资料来源 | file-b03014e21edb2aed9af5 1419-1982 | 逐字命中 | AGE: 59.735, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `literature-03` | 文献证据 | 资料来源 | N/A（该主张没有引用） | N/A |  |
| `timeline-01` | 病例时间线 | 时间与事件 | file-b03014e21edb2aed9af5 1419-1982 | 逐字命中 | AGE: 59.735, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `timeline-01` | 病例时间线 | 时间与事件 | context-12 -1-265 | 逐字命中 | The patient has no evidence of cancer recurrence or progression within the past 12 months. |
| `timeline-02` | 病例时间线 | 时间与事件 | file-ab603d3661c049070b15 1551-2143 | 逐字命中 | AGE: 56.883, labtest > cea_labs --> CEA: 4.7000 ng/ml           AGE: 57.108, diagnosis > c |
| `timeline-02` | 病例时间线 | 时间与事件 | file-34fa9f8e18053f97f0cd 2100-2407 | 逐字命中 | AGE: 58.902, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `timeline-03` | 病例时间线 | 时间与事件 | N/A（该主张没有引用） | N/A |  |
| `genomics-01` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `genomics-01` | 基因与通路 | 分子与变异 | file-e963cfe9790b48136a60 -1-600 | 逐字命中 | AGE: 54.850, samples > clinical_sample --> SAMPLE_ID: P-0022916-T01-IM6, PATIENT_ID: P-002 |
| `genomics-02` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 566-1002 | 逐字命中 | DOT1L,0,MSKCC,GRCh37,19,2210451,2210451,+,missense_variant,Missense_Mutation,SNP,C,C,T,P-0 |
| `genomics-02` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 1002-1434 | 逐字命中 | BLM,0,MSKCC,GRCh37,15,91306247,91306247,+,missense_variant,Missense_Mutation,SNP,A,A,G,P-0 |
| `genomics-03` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 1434-1879 | 逐字命中 | HOXB13,0,MSKCC,GRCh37,17,46804385,46804386,+,frameshift_variant,Frame_Shift_Ins,INS,-,-,A, |
| `genomics-03` | 基因与通路 | 分子与变异 | file-9e8b7ad77b2cb34fd593 1879-2119 | 逐字命中 | TCF7L2,0,MSKCC,GRCh37,10,114711033,114711034,+,splice_donor_variant,Splice_Site,DNP,GT,GT, |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-88cacc98f0b9ef7d5a14 582-1021 | 逐字命中 | "ICD_O_HISTOLOGY_DESCRIPTION": "Adenocarcinoma In Polyp,Nos", "DIAGNOSIS_DESCRIPTION": "Re |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-88cacc98f0b9ef7d5a14 582-1021 | 逐字命中 | "ICD_O_HISTOLOGY_DESCRIPTION": "Adenocarcinoma In Polyp,Nos", "DIAGNOSIS_DESCRIPTION": "Re |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-e963cfe9790b48136a60 -1-600 | 逐字命中 | AGE: 54.850, samples > clinical_sample --> SAMPLE_ID: P-0022916-T01-IM6, PATIENT_ID: P-002 |
| `pathology-03` | 病理与癌种语境 | 病理与癌种 | N/A（该主张没有引用） | N/A |  |
| `drug-01` | 药物关系 | 既往用药 | N/A（该主张没有引用） | N/A |  |
| `drug-02` | 药物关系 | 药物关系 | N/A（该主张没有引用） | N/A |  |
| `verifier-01` | 主张核验 | 核验 | file-b03014e21edb2aed9af5 1419-1982 | 逐字命中 | AGE: 59.735, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `verifier-01` | 主张核验 | 核验 | context-12 -1-265 | 逐字命中 | The patient has no evidence of cancer recurrence or progression within the past 12 months. |
| `verifier-02` | 主张核验 | 核验 | file-ab603d3661c049070b15 1551-2143 | 逐字命中 | AGE: 56.883, labtest > cea_labs --> CEA: 4.7000 ng/ml           AGE: 57.108, diagnosis > c |
| `verifier-02` | 主张核验 | 核验 | file-34fa9f8e18053f97f0cd 2100-2407 | 逐字命中 | AGE: 58.902, diagnosis > cancer_presence --> HAS CANCER: No, SUBTYPE: HasCancer, PROCEDURE |
| `verifier-03` | 主张核验 | 资料来源 | file-88cacc98f0b9ef7d5a14 -1-582 | 逐字命中 | {"SAMPLE_ID": "P-0022916-T01-IM6", "PATIENT_ID": "P-0022916", "CANCER_TYPE": "Colorectal C |
| `verifier-03` | 主张核验 | 资料来源 | file-9e8b7ad77b2cb34fd593 -1-566 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |

## mtb-P-0027883-q7 · MTBBench dev 课堂样例 · 现行配置（4 问 · 3 位患者）

问题：Given that the patient is 53 years old, will the patient be still alive in the next 12 months?

- 状态 completed；答案 A，标签 A；调用 7，126026 in + 16049 out token，1207.8 秒。
- 决策解释：Adopted claim ids: verifier-01, timeline-02, timeline-01, literature-01. Rejected claim ids: none. Findings: (1) Current status layer: the latest visible summary covers ages 51.3 to 53 and states the cancer has neither progressed nor recurred within the past 12 months, while the latest dated observation at age 52.859 reports cancer present on CT but not progressed. This supports a prediction of co

| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |
| --- | --- | --- | --- | --- | --- |
| `literature-01` | 文献证据 | 资料来源 | context-13 -1-233 | 逐字命中 | The patient's cancer has neither progressed nor recurred within the past 12 months. Compre |
| `literature-01` | 文献证据 | 资料来源 | file-4b7ce9a925ffb20dbcf3 2418-2727 | 逐字命中 | AGE: 52.859, diagnosis > cancer_presence --> HAS CANCER: Yes, SUBTYPE: HasCancer, PROCEDUR |
| `literature-02` | 文献证据 | 资料来源 | file-0334e42f620d083c1d18 -1-600 | 逐字命中 | {"SAMPLE_ID": "P-0027883-T01-IM6", "PATIENT_ID": "P-0027883", "CANCER_TYPE": "Pancreatic C |
| `literature-02` | 文献证据 | 资料来源 | file-5e8edfdb3ea25a0175d5 -1-594 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `literature-03` | 文献证据 | 资料来源 | N/A（该主张没有引用） | N/A |  |
| `timeline-01` | 病例时间线 | 时间与事件 | file-0b05e3a83021a83512c8 -1-465 | 逐字命中 | AGE: 48.522, diagnosis > cancer_presence --> HAS CANCER: Yes, SUBTYPE: HasCancer, PROCEDUR |
| `timeline-01` | 病例时间线 | 时间与事件 | file-4b7ce9a925ffb20dbcf3 2418-2727 | 逐字命中 | AGE: 52.859, diagnosis > cancer_presence --> HAS CANCER: Yes, SUBTYPE: HasCancer, PROCEDUR |
| `timeline-02` | 病例时间线 | 时间与事件 | context-13 -1-233 | 逐字命中 | The patient's cancer has neither progressed nor recurred within the past 12 months. Compre |
| `timeline-03` | 病例时间线 | 时间与事件 | N/A（该主张没有引用） | N/A |  |
| `genomics-01` | 基因与通路 | 分子与变异 | file-5e8edfdb3ea25a0175d5 -1-594 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `genomics-01` | 基因与通路 | 分子与变异 | file-5e8edfdb3ea25a0175d5 594-1074 | 逐字命中 | TP53,7157,MSKCC,GRCh37,17,7577114,7577114,+,missense_variant,Missense_Mutation,SNP,C,C,T,P |
| `genomics-02` | 基因与通路 | 分子与变异 | file-397bf17a1496f8b65698 -1-301 | 逐字命中 | SAMPLE_ID,Hugo_Symbol,VALUE P-0027883-T01-IM6,CCND3,2.0 P-0027883-T01-IM6,SMAD4,-2.0 P-002 |
| `genomics-03` | 基因与通路 | 分子与变异 | N/A（该主张没有引用） | N/A |  |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-0334e42f620d083c1d18 -1-600 | 逐字命中 | {"SAMPLE_ID": "P-0027883-T01-IM6", "PATIENT_ID": "P-0027883", "CANCER_TYPE": "Pancreatic C |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | file-0334e42f620d083c1d18 600-1044 | 逐字命中 | "ICD_O_HISTOLOGY_DESCRIPTION": "Infiltrating Duct Carcinoma", "DIAGNOSIS_DESCRIPTION": "Pa |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-0334e42f620d083c1d18 -1-600 | 逐字命中 | {"SAMPLE_ID": "P-0027883-T01-IM6", "PATIENT_ID": "P-0027883", "CANCER_TYPE": "Pancreatic C |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | file-5e8edfdb3ea25a0175d5 -1-594 | 逐字命中 | Hugo_Symbol,Entrez_Gene_Id,Center,NCBI_Build,Chromosome,Start_Position,End_Position,Strand |
| `pathology-03` | 病理与癌种语境 | 病理与癌种 | N/A（该主张没有引用） | N/A |  |
| `drug-01` | 药物关系 | 既往用药 | file-e8efdad1e9b9333775e8 4957-5554 | 逐字命中 | AGE: 50.070, treatment > treatment --> STOP_AGE: 50.1661, SUBTYPE: Chemo, AGENT: CAPECITAB |
| `drug-01` | 药物关系 | 既往用药 | file-0b05e3a83021a83512c8 3036-3621 | 逐字命中 | AGE: 48.591, diagnosis > progression --> CT scan reveals cancer has NOT progressed. AGE: 4 |
| `drug-02` | 药物关系 | 药物关系 | N/A（该主张没有引用） | N/A |  |
| `verifier-01` | 主张核验 | 资料来源 | context-13 -1-233 | 逐字命中 | The patient's cancer has neither progressed nor recurred within the past 12 months. Compre |
| `verifier-01` | 主张核验 | 资料来源 | file-4b7ce9a925ffb20dbcf3 2418-2727 | 逐字命中 | AGE: 52.859, diagnosis > cancer_presence --> HAS CANCER: Yes, SUBTYPE: HasCancer, PROCEDUR |
| `verifier-02` | 主张核验 | 核验 | N/A（该主张没有引用） | N/A |  |
| `verifier-03` | 主张核验 | 核验 | file-0334e42f620d083c1d18 -1-600 | 逐字命中 | {"SAMPLE_ID": "P-0027883-T01-IM6", "PATIENT_ID": "P-0027883", "CANCER_TYPE": "Pancreatic C |
| `verifier-03` | 主张核验 | 核验 | file-e8efdad1e9b9333775e8 4957-5554 | 逐字命中 | AGE: 50.070, treatment > treatment --> STOP_AGE: 50.1661, SUBTYPE: Chemo, AGENT: CAPECITAB |

## civic-3e09dc9e-43af-4022-88ec-a31f18cfaf42 · CIViC-Fact dev 课堂样例 · 现行配置（2 条主张 · 2 篇文献）

问题：{   "disease": "chronic myeloid leukemia",   "evidenceDirection": "DOES_NOT_SUPPORT",   "evidenceType": "PREDICTIVE",   "molecularProfile": "BCR::ABL1 Fusion AND ABL1 T315I",   "significance": "sensit

- 状态 completed；答案 NEI，标签 REVISIONS；调用 7，25105 in + 15211 out token，832.1 秒。
- 决策解释：The supplied claim is a predictive sensitivity/response statement for the exact somatic profile BCR::ABL1 fusion AND ABL1 T315I in CML with ponatinib, with direction DOES_NOT_SUPPORT. The only visible evidence is a single literature fragment reporting 12-month ponatinib response rates in CP-CML and stating that patients with T315I had higher response rates, while T315I was not a significant progno

| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |
| --- | --- | --- | --- | --- | --- |
| `literature-01` | 文献证据 | 资料来源 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `timeline-01` | 病例时间线 | 时间与事件 | N/A（该主张没有引用） | N/A |  |
| `genomics-01` | 基因与通路 | 分子与变异 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `genomics-02` | 基因与通路 | 分子与变异 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `pathology-02` | 病理与癌种语境 | 病理与癌种 | N/A（该主张没有引用） | N/A |  |
| `drug-01` | 药物关系 | 既往用药 | N/A（该主张没有引用） | N/A |  |
| `drug-02` | 药物关系 | 药物关系 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `drug-03` | 药物关系 | 药物关系 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `verifier-01` | 主张核验 | 核验 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |
| `verifier-02` | 主张核验 | 资料来源 | pmid-25349473 -1-312 | 逐字命中 | At 12 months after the initiation of ponatinib therapy, 56% of patients with CP-CML had a  |

## civic-60a33dc8-2af3-4b38-9a5c-951b40aafd27 · CIViC-Fact dev 课堂样例 · 现行配置（2 条主张 · 2 篇文献）

问题：{   "disease": "skin carcinoma",   "evidenceDirection": "DOES_NOT_SUPPORT",   "evidenceType": "PREDICTIVE",   "molecularProfile": "MTOR F2108L",   "significance": "resistance",   "therapies": [     "S

- 状态 completed；答案 NEI，标签 NEI；调用 7，37191 in + 13842 out token，793.4 秒。
- 决策解释：Decision layer: the supplied claim concerns somatic MTOR F2108L in skin carcinoma as a predictive marker of resistance to a serine/threonine kinase inhibitor. The visible source is a BCR-ABL/CML/Ph+ALL tyrosine kinase inhibitor literature source discussing imatinib, dasatinib, nilotinib, ponatinib, and BCR-ABL kinase-domain variants such as T315I and compound BCR-ABL mutations. It does not provide

| 主张 | 角色 | 层面 | 引用 | 定位 | 片段开头 |
| --- | --- | --- | --- | --- | --- |
| `literature-01` | 文献证据 | 资料来源 | pmid-25349473 -1-596 | 逐字命中 | "ntolerance. Dasatinib (Sprycel(r)), a dual-Src family kinase inhibitor, and nilotinib (Ta |
| `literature-01` | 文献证据 | 资料来源 | pmid-25349473 1789-2382 | 逐字命中 | patients who were resistant or had relapsed while they were on the standard of care therap |
| `timeline-01` | 病例时间线 | 时间与事件 | N/A（该主张没有引用） | N/A |  |
| `genomics-01` | 基因与通路 | 分子与变异 | N/A（该主张没有引用） | N/A |  |
| `pathology-01` | 病理与癌种语境 | 病理与癌种 | N/A（该主张没有引用） | N/A |  |
| `drug-01` | 药物关系 | 既往用药 | N/A（该主张没有引用） | N/A |  |
| `drug-02` | 药物关系 | 药物关系 | N/A（该主张没有引用） | N/A |  |
| `verifier-01` | 主张核验 | 资料来源 | pmid-25349473 -1-596 | 逐字命中 | "ntolerance. Dasatinib (Sprycel(r)), a dual-Src family kinase inhibitor, and nilotinib (Ta |
| `verifier-01` | 主张核验 | 资料来源 | pmid-25349473 2382-2982 | 逐字命中 | BCR-ABL, 64% for those with one mutation, 62% for those with two or more mutations, and 74 |
| `verifier-02` | 主张核验 | 核验 | N/A（该主张没有引用） | N/A |  |
| `verifier-03` | 主张核验 | 核验 | N/A（该主张没有引用） | N/A |  |

