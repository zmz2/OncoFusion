# 关键引用的逐条语义核对（AI 辅助，不是人工评审）

核对人：本会话的代理（同一个执行者，非独立第二人）。方法：把结果行里每条 `Finding.statement` 全文，与它自己引用的
`quote`（`document_id[start:end]`，已由后端从片段号回查）逐段对照，判断**这段原文是否真的支撑这句话**。
定位层面的机械检查（quote 是否与原文偏移完全相等）不在这里，见 `results/SEMANTIC_REVIEW_CLASS6.md`。

判定用三档：

- `支持`：引文里能看到该主张点名的字段或句子。
- `部分支持`：引文确实来自同一条记录，但主张点名的某个具体字段在我截取的前段里看不到，需要展开完整片段才能确认。
- `N/A`：该主张没有引用任何片段（这些主张自己写的是 `unknown` 或 `not_applicable`，按规则不判）。

范围：课堂现场用的 3 例逐条判；其余 3 例只做案例级结论（它们的 100% 引用定位都逐字命中，见下表）。

## mtb-P-0006191-q0（答 B / 标签 A，答错的一例）

| 主张 | 角色 | 定位 | 语义 | 依据（引文里看到的字段） |
| --- | --- | --- | --- | --- |
| `literature-01` | 文献 | 逐字命中 | 支持 | context-0 前 277 字符就是「55-year-old … lung adenocarcinoma … ages 55 and 56.1 years」 |
| `literature-02` | 文献 | 逐字命中 | 支持 | 两段引文分别是 55.293 的原发样本记录与 56.082 的 `HAS CANCER: No` / `NOT progressed` CT |
| `literature-03` | 文献 | 无引用 | N/A | 主张本身写 `unknown`（56.1 之后无复发记录） |
| `timeline-01` | 时间线 | 逐字命中 | 支持 | 第二段引文含 `STOP_AGE: 55.5995 … PEMETREXED … CISPLATIN` 与 55.569 的随访记录 |
| `timeline-02` | 时间线 | 逐字命中 | 支持 | 56.082 的 `HAS CANCER: No` 与 `cancer has NOT progressed` 逐字在引文内 |
| `timeline-03` | 时间线 | 无引用 | N/A | `unknown`：56.082 之后无更晚事件 |
| `genomics-01` | 基因 | 逐字命中 | 部分支持 | `GENE_PANEL: IMPACT410`、`TMB_NONSYNONYMOUS: 2.936159093` 在引文内；`MSI stable`、`tumor purity 40.0` 属同一条记录的后段，需展开完整片段 |
| `genomics-02` | 基因 | 无引用 | N/A | `unknown`：无基因/变异层面 |
| `pathology-01` | 病理 | 逐字命中 | 部分支持 | `AJCC: IIA`、`PATH_GROUP: 2A`、`ADENOCARCINOMA COMBINED WITH OTHER TYPES` 在引文内；「lower lobe」「区域淋巴结受累」不在这两段的前 457 字符里，属同记录后段字段 |
| `pathology-02` | 病理 | 逐字命中 | 部分支持 | 同上：`IMPACT410`、TMB 可见，MSI/purity 在同记录后段 |
| `pathology-03` | 病理 | 无引用 | N/A | `unknown`：无 57.8 后的病理标本 |
| `drug-01` | 药物 | 逐字命中 | 支持 | `AGENT: PEMETREXED` / `AGENT: CISPLATIN`，起止 55.427→55.5995 逐字可见 |
| `drug-02`、`drug-03` | 药物 | 无引用 | N/A | `unknown`：无分子-药物关系、无后续用药 |
| `verifier-01` | 核验 | 逐字命中 | 支持 | 复用的正是 56.082 那段 CT |
| `verifier-02` | 核验 | 无引用 | N/A | `unknown`：无 56.082 之后事件 |
| `verifier-03` | 核验 | 逐字命中 | 部分支持 | 与 `genomics-01` 同一处依赖记录后段字段 |

案例级：17 条主张 / 16 次引用全部逐字命中；7 条 `unknown` 主张一律不带引用（后端会拒绝带引用的 `unknown`）。
答错的 B/A 不在引用层面——引用都成立，是**外推方向**错了（最新 CT 无癌 ≠ 未来 12 个月不复发），
而未解决项恰好把这条写了出来：「56.082 之后没有任何复发或随访记录」。

## mtb-P-0027883-q7（答 A / 标签 A，长时间线 + 真实分子）

| 主张 | 角色 | 定位 | 语义 | 依据 |
| --- | --- | --- | --- | --- |
| `literature-01` | 文献 | 逐字命中 | 支持 | context-13 原句「neither progressed nor recurred within the past 12 months … ages 51.3 and 53」 |
| `literature-02` | 文献 | 逐字命中 | 支持 | 样本 JSON（Pancreatic Adenocarcinoma, IMPACT468）+ mutation.csv 表头 |
| `literature-03` | 文献 | 无引用 | N/A | `unknown`：无 53 岁之后生存记录 |
| `timeline-01` | 时间线 | 逐字命中 | 支持 | 48.522 与 52.859 两段 CT，均 `cancer has NOT prog…` |
| `timeline-02` | 时间线 | 逐字命中 | 支持 | context-13 同句 |
| `timeline-03` | 时间线 | 无引用 | N/A | `unknown` |
| `genomics-01` | 基因 | 逐字命中 | 支持 | `TP53 … p.Cys275Tyr,p.C275Y`、`FLT4 … missense_variant` 逐字在第二段引文里；`KRAS p.G12V` 在同一片段前部 |
| `genomics-02` | 基因 | 逐字命中 | 支持 | CNA 行逐字给出 `CCND3,2.0 SMAD4,-2.0 CDKN2B,-2.0 CDKN2A,-2.0 TEK,-2.0 CDKN2Ap14ARF,-2.0 VEGFA,2.0 YES1,2.0 CDKN2Ap16INK4A,-2.0` |
| `genomics-03` | 基因 | 无引用 | N/A | `unknown`：分子层面不下 12 个月结论；核验第一轮判 `insufficient`、复盘轮判 `confirmed`（两条都留在记录里） |
| `pathology-01` | 病理 | 逐字命中 | 支持 | `Infiltrating Duct Carcinoma`、`TMB_NONSYNONYMOUS: 2.594094285`；`CLINICAL_GROUP_y` 起在同段后部 |
| `pathology-02` | 病理 | 逐字命中 | 支持 | 样本号 `P-0027883-T01-IM6` 同时出现在病理与变异文件里 |
| `pathology-03` | 病理 | 无引用 | N/A | `unknown` |
| `drug-01` | 药物 | 逐字命中 | 支持 | `AGENT: CAPECITABINE`、`STOP_AGE: 50.1661`、`ECOG: 1`、`ca_19-9 … 24` |
| `drug-02` | 药物 | 无引用 | N/A | `unknown`：无分子-药物关系 |
| `verifier-01/03` | 核验 | 逐字命中 | 支持 | 复用 context-13、52.859 CT 与样本/用药记录 |
| `verifier-02` | 核验 | 无引用 | N/A | `unknown` |

## civic-60a33dc8-2af3-4b38-9a5c-951b40aafd27（答 NEI / 标签 NEI，单文献且来源不对题）

| 主张 | 角色 | 定位 | 语义 | 依据 |
| --- | --- | --- | --- | --- |
| `literature-01` | 文献 | 逐字命中 | 支持 | 引文是 CML/Ph+ALL 的 BCR-ABL TKI 综述（dasatinib、nilotinib、ponatinib、T315I），与该主张对来源的描述一致 |
| `verifier-01` | 核验 | 逐字命中 | 支持 | 同一篇引文里确实没有 MTOR / F2108L / skin carcinoma / 丝氨酸-苏氨酸激酶抑制剂耐药的任何字面证据 |
| `timeline-01`、`genomics-01`、`pathology-01`、`drug-01`、`drug-02`、`verifier-02`、`verifier-03` | 各专业 | 无引用 | N/A | 七个角色都写 `unknown`，一条都没编造引用；决策随后**排除 7 条主张**、采用 2 条，答案 NEI |

这一例是「证据不对题时怎么收口」的正面样本：来源确实存在、引用确实逐字命中，但命中不能替代相关性判断。

## 其余三例（案例级）

| 案例 | 主张 | 引用 | 定位 | 案例级语义结论 |
| --- | --- | --- | --- | --- |
| `mtb-P-0022916-q2` | 17 | 28 | 全部逐字命中 | 抽读的关键引用都能对上：`TP53 p.R175H`、`DOT1L/IGF1R/BLM/STAT3/APC` 变异行、floxuridine 用药行、57.108 进展与 57.765 `CEA 2.0` 均逐字出现在被引片段内；2 条主张无引用（含 1 条 `pathologic/absent` 写 unknown） |
| `mtb-P-0022916-q6` | 17 | 24 | 全部逐字命中 | 抽读：59.735 `no cancer / no progression` 与 59.951 `CEA 1.5` 逐字可见；`literature-03` 用的是 `not_applicable`（本题不需要文献包）而不是 `unknown`，两者在页面上分开显示 |
| `civic-3e09dc9e-43af-4022-88ec-a31f18cfaf42` | 11 | 8 | 全部逐字命中 | 引文支持「T315I 患者 12 个月缓解率更高、但 T315I 非独立预后因素」，也支持「片段里没有 BCR::ABL1 融合状态/转录本/检测方法」；系统据此答 NEI，标签是 REVISIONS（答错），但错在**结论档位**而非引用造假 |

## 核对中发现的问题（如实记下）

1. 个别主张点名的具体字段（如 `MSI stable`、`tumor purity 40.0`、`lower lobe`、区域淋巴结）在我截取的引文前段看不到，
   只能判 `部分支持`：它们与被引用的记录同属一条，但**逐字命中只保证「这段原文确实来自这里」，不保证「这句话的每个字段都在这段里」**。
   课堂里如果要展示这一点，就展开那条主张的完整片段。
2. 核验角色分两轮（首轮 + 复盘），同一 `target_claim_id` 可能留下两条不同结论
   （q7 的 `genomics-03`：`insufficient` → `confirmed`）。记录保留两条，页面按两条显示；
   这不算矛盾数据，但报告里不能把它统计成「一次核验一个结论」。
3. `civic-3e09dc9e` 里有一条核验意见的文字写成了「The pathologic layer confirms…」，而它针对的是 `genomics-01`。
   结论本身站得住，**是核验自己写错了层名**，属于提示词层面的措辞问题，不是协议缺陷；已在剩余事项里记下。
