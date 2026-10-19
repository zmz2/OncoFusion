# 可追溯人工检查案例（真实 API，脱敏：只含结构断言，不含病例正文或论文片段）

| # | 类别 | 病例 | 七Agent 判定/正确 | 单调用 判定/正确 | 引用数 | quote 逐字命中 | offset 与原文一致 | 跨来源检查 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | budget_or_failure | `mtb-P-0027883-q6` | None/0 | B/1 | 0 / 3 | True / True | True / True | True / True |
| 2 | disagreement | `mtb-P-0022916-q2` | B/0 | A/1 | 3 / 2 | True / True | True / True | True / True |
| 3 | disagreement | `mtb-P-0022916-q3` | B/1 | A/0 | 3 / 2 | True / True | True / True | True / True |
| 4 | disagreement | `mtb-P-0027883-q3` | B/1 | A/0 | 2 / 2 | True / True | True / True | True / True |
| 5 | both_correct | `mtb-P-0009786-q0` | B/1 | B/1 | 3 / 2 | True / True | True / True | True / True |
| 6 | both_correct | `mtb-P-0009786-q1` | B/1 | B/1 | 3 / 3 | True / True | True / True | True / True |

判定/正确列：模型答案与 `_gold` 标签的是否一致（1 对 0 错）；
quote 逐字命中与 offset 一致列：七Agent / 单调用 两臂分别对全部引用做机械校验的结果；
跨来源检查确认每条引用的 `document_id` 都在该病例本阶段可见来源内。
双人语义审查用 `scripts/review_citations.py export/score`，本表只证明定位正确，不替代语义支持判断。
