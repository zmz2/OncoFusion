# 课堂演示三组整改验收

本轮只做三组整改，并在两条新的真实运行上取证：

1. 核验结论真正进入综合决策（`civic-3e09dc9e…`）；
2. 用药等关键事实按原始 offset 保底送入（`mtb-P-0022916-q6`）；
3. 网页用量在实时、完成态与回放里共用一次归约。

同一时间窗内只补了这两条真实运行；其余六个课堂案例与历史回放保持不变。
没有启动方差分析、多 seed 重复、完整消融或 31 例验收。样本量只够课堂演示与试运行读数，
不构成显著性结论。

分支 `codex/v1-fast-real-api-20261019`（PR #6），基线 `650e627`。
验收时可回放的两个置顶按钮在 `/app` 的「5 · 历史真实结果回放」里：

- `验收 · 用药事实保底（q6）`
- `验收 · 核验账本进入决策`

---

## 1. 核验结论进入综合决策

### 改了什么

- `oncofusion/engine.py` 新增 `verification_ledger()`：把每条 `ClaimVerdict` 连同
  `target_claim_id`、`claim_author`、`reviewer`、`verdict`、`reason`、`final`、`citations`
  一起记录下来。`final` 只由服务器按 `reviewer == "verifier"` 判定；专业角色的反馈也是 verdict，
  但不是最终判定。
- 调用 Decision 前组装 `payload.verification_ledger`，并把每条主张的最终判定写入
  `payload.claim_roster[].verifier_verdict`。同时发一条 `verification_ledger` trace 事件，
  记在该事件实际喂给的那次 Decision 调用上，回放能回答「Decision 当时看到了什么」。
- Decision 的输出必须点名 `adopted_claim_ids` 与 `rejected_claim_ids`；同一 ID 不得同时出现在两边，
  也不得出现不存在的 ID。verifier 的 `rejected` / `insufficient` 清单也写进 ledger 事件。
- 主张 ID 的注册改为原子提交：一条响应的 findings、verdict、引用、scope、资料状态全部通过校验、
  且报告已存在之后，ID 才写入 `known_claims`。失败或待修复的响应不留任何幽灵 ID；
  `used_claim_ids` 只能引用已提交的 ID 或同一响应内更早的主张。
- 报告与页面把 `reviewer_role=verifier` 的最终判定与专业角色的反馈分行显示，
  并明确「一张表出现多行 verdict 不代表 Verifier 运行了多次」。

### 确定性测试

```bash
.venv/bin/python -m pytest -q tests/test_verification_ledger.py tests/test_claim_scopes.py
# 13 passed
```

`tests/test_verification_ledger.py`：

- `test_only_the_verdict_changes_what_the_decision_receives`：同一份上游主张，只改 Verifier 的
  verdict（confirmed ↔ rejected），Decision 收到的 ledger 与 `verifier_verdict` 随之改变；
  答案保持 NEI，没有被强行翻转——验收的是输入随核验状态变化，不是答案必须变。
- `test_ledger_rows_name_reviewer_verdict_reason_and_citations`：ledger 同时含专业角色反馈与
  Verifier 最终判定，逐行保留审核者、判定、理由与引用；Verifier 只被调用一次。
- `test_adopted_and_rejected_are_mutually_exclusive`：同一 ID 同时采用与排除的首次响应被拒；
  一次结构修复后完成，两个清单不相交。

`tests/test_claim_scopes.py`（10 passed）覆盖越界 scope、缺资料主张不得引用/断言、
失败响应不留 ID、`used_claim_ids` 只能引用已提交或同一响应内更早的 ID、findings 上限等。

页面显示另有一条 node 断言 `test_claims_table_separates_verifier_final_from_role_feedback`
（在 `tests/test_demo_app.py`，无 node 的服务器自动 skip）：把页面里的
`reviewer === "verifier"` 改成恒真后该测试失败，说明它确实能抓住“把反馈混成最终判定”的旧行为。
本机对同一页面脚本运行 `node --check` 与断言 harness 均返回 0。

### 真实运行：civic-3e09dc9e

`results/v1/real_class6d_civic/v1_class/0/civic-3e09dc9e-43af-4022-88ec-a31f18cfaf42.json`

| 项 | 值 |
| --- | --- |
| 状态 | completed |
| 答案 / 标签 | REVISIONS / REVISIONS |
| 模型调用 | 10 次（7 角色 + literature、verifier、decision 各 1 次结构修复） |
| token | 34,885 in + 18,383 out |
| 耗时 | 206.2 s |

- 6 条主张全部 `confirmed`；Decision 采用全部 6 条、排除 0 条。
- ledger 共 6 行，全部 `reviewer=verifier`、`final=true`；其中 5 行各带 1 条引用
  （`pmid-25349473:f01`），`pathology-01` 没有引用。
- Decision 被修复一次，因此 trace 里有 2 条 `verification_ledger` 事件，每条都是 6 行；
  页面与回放展示的是最后一次 Decision 实际收到的账本。
- 页面回放显示「综合决策收到的核验账本 6 条（最终判定 6 条，专业角色反馈 0 条）」，
  每行给出主张、审核者、判定、理由、引用数；六条主张的「决策处理」均为「决策采用」。

### 限制

- q6 的 verifier 在 9 条 verdict 里没有给出引用（`citations` 为空），所以该例 ledger 的引用列是 0；
  ledger 保留引用的字段逻辑由 civic 的 5 条引用与确定性测试覆盖。模型不给引用时不会伪造。
- 账本说明“核验状态已被 Decision 看到”，不等于答案一定正确；civic 的答案恰好与标签一致，
  q6 的标签一致也与该组无关。

---

## 2. 关键事实按原始 offset 保底送入

### 改了什么

- `oncofusion/evidence.py` 增加按记录语法识别的 `MODALITY_PATTERNS`（治疗、分子、病理）与
  `ROLE_MODALITY`：timeline/drug 必须拿到治疗记录，genomics 拿分子记录，pathology 拿病理记录，
  verifier 与 decision 拿三类。
- 片段规划改为两档保底：角色自己的模态记录优先，其次是一份文档的首记录、末记录与最新日期观测；
  其余片段才按关键字段与问题重叠度竞争剩余字符预算。保底 span 用**原始记录 offset** 标记，
  不因入选顺序改变位置。
- 候选仍然只来自该阶段可见的资料，后续阶段的记录不会成为候选；只有真正送入的 ID 才能被引用。
- 保底集合本身超过字符预算时，计划停在预算内，并把每个没送进去的保底 span 连同
  `document_id`、`record_span`、字符数、保底类型和 `reason="character budget"` 写入
  `guaranteed_unsent`，不会静默超预算。
- 缺资料主张由服务器写入 `material_basis`：`not_recorded`（原文没有这类记录）、
  `selection_not_covered`（有候选但本阶段没送）、`supplied`（所需资料已送入）。
  页面用中文标签区分，不再把“选集没覆盖”说成“原文没记录”。
- `tail_dropped` 的口径统一为「该节点有候选片段没进提示」，未送入的片段可以在任何位置，
  不只是尾部前缀。

### 确定性测试

```bash
.venv/bin/python -m pytest -q tests/test_evidence_guarantees.py
# 5 passed
```

- `test_the_record_naming_the_agent_is_sent_even_when_the_budget_is_tight`：合成 40 条记录、
  FLOXURIDINE 位于 offset 3623 的时间线，紧预算下仍按原始 span 送入；普通规划不会送它。
- `test_a_future_stage_record_is_neither_a_candidate_nor_sent`：后续阶段记录不成为候选。
- `test_a_guaranteed_span_that_cannot_fit_is_recorded_not_silently_dropped`：保底 span 放不下时
  记入 `guaranteed_unsent`，原因写明字符预算。
- `test_material_basis_separates_not_recorded_from_not_selected`：两种缺失来源可区分。
- `test_missing_material_claims_carry_the_server_side_basis`：缺资料主张带上服务器算出的 basis。

### 真实运行：mtb-P-0022916-q6

`results/v1/real_class6d_mtb_r2/v1_class/0/mtb-P-0022916-q6.json`

| 项 | 值 |
| --- | --- |
| 状态 | completed |
| 答案 / 标签 | A / A |
| 模型调用 | 8 次 |
| token | 144,220 in + 16,760 out |
| 耗时 | 207.0 s |

Drug 角色实际收到的证据：

- 候选 47 段，送入 27 段；原文 22,811 字符，送入 11,969 / 12,000 字符。
- 必需层 `treatment`：候选 3、送入 3、`unsent=[]`；`guaranteed_unsent=[]`。
- 送入集合包含 `file-ab603d3661c049070b15:f07`，其原始记录 span 为 `[3113, 3678]`；
  该 span 内 offset 3623 处是 `AGENT: FLOXURIDINE`，后一条 `f08` 从 3678 开始。
- 该 span 是 Drug 角色自己的模态保底，不靠问题词重叠或入选顺序碰巧命中。

Decision 实际收到的覆盖：送入 26 段、11,598 字符；
`treatment` 3/3、`molecular` 10/10、`pathology` 3/3，`guaranteed_unsent=[]`。

Drug 的输出从上一轮的“无用药”变成两条暴露记录：

- `drug-01`：54.98–55.58 岁接受辅助 FOLFOX（leucovorin、fluorouracil、oxaliplatin）；
- `drug-02`：57.25–57.67 岁接受二线 FLOX（leucovorin、fluorouracil、irinotecan）；
  状态为 `corrected`（Verifier 指出 FLOX 通常含 oxaliplatin，措辞需更正）；
- `drug-03`：药物关系未知，资料状态为 `supplied`（所需资料已送入，不是选集遗漏）。

### 限制（如实记录）

- 模型的两条暴露陈述只写了 leucovorin / fluorouracil / oxaliplatin / irinotecan，
  **没有逐字写出 FLOXURIDINE**；Verifier 的更正也没有写。保底验收的层级是“输入已送入、
  可按原始 offset 复核”，不是“模型一定抽取到该药名”。Literature 与 Genomics 在这一轮
  各返回 0 条结论。这是模型阅读/抽取差异，不是选择遗漏，不能写成“已修复用药事实抽取”。

---

## 3. 实时、完成态与回放共用一次用量归约

### 改了什么

- `oncofusion/web/index.html` 用 `reduceUsage` / `applyUsageEvents` / `usageTotals` 统一处理
  `model_usage` 事件：按 trace `sequence` 去重，重复帧只算一次；实时累加、`finish` 收尾、
  历史回放、刷新后按 `run_id` 重查、断线重连都走同一条路径。
- 总调用数与 token 总数读 `RunResult.usage`；端到端秒数读 `duration_seconds`；
  逐角色累加该角色的每一次调用（含结构修复），不再按角色个数计数。
- 修掉旧实现的三个错误：`applyEvent` 重复累加、`finish` 用最后一次调用覆盖总量、
  `showAnswer` 数角色而不是调用次数。

### 确定性测试

`tests/test_demo_app.py::test_usage_is_one_reduction_for_live_finish_and_replay`（node）：

- 合成两通调用 100 in / 10 out / 2 s 与 200 in / 20 out / 3 s，实时显示必须是
  **300 + 30 / 5 s / 2 次**；
- 重复 frame 不得重复计数；
- `finish` 与已应用的实时帧一致；
- 按角色拆分得到 [100, 200]；
- 断开重连后一致；
- 回放不论是否带存储用量都一致；
- 修复案例显示 2 次调用、150 in / 15 out / 3 s。

页面脚本 `node --check` 通过；同一脚本的两段 node 断言 harness 返回 0。
服务器无 node，因此该测试在服务器套件中计入 3 个 skip，需要在有 node 的机器上跑。

### 页面实测（回放两条验收结果）

| 案例 | 页面用量 | 与结果文件 |
| --- | --- | --- |
| q6 r2 | 8 次 · 144220 + 16760 · 207s | `usage.calls=8`，144,220 / 16,760，206.99 s |
| civic | 10 次 · 34885 + 18383 · 206s | `usage.calls=10`，34,885 / 18,383，206.18 s |

两个置顶按钮都点开、刷新页面后重新点开，调用数、token、秒数与 ledger 行数完全一致；
q6 的 Drug 卡显示 27/47 段、11,969/12,000 字符、`treatment` 3/3，并显示
「非选集缺失：所需资料已送入」；civic 的 `pathology-01` 显示「缺失来源：原文未记录」，
`verifier-02` 显示「非选集缺失：所需资料已送入」。

---

## 4. 回归

服务器（Python 3.12，`.venv`）上重跑：

- 三组确定性测试：`tests/test_verification_ledger.py`、`tests/test_evidence_guarantees.py`、
  `tests/test_claim_scopes.py` 共 18 passed；`tests/test_demo_app.py` 8 passed、3 skipped（无 node）。
- 全量 `pytest -q`：749 passed、3 skipped（无 node）、23.51 s，rc 0。
- `scripts/run_checks.py`：749 passed、3 skipped、语句覆盖率 95%，45.95 s，rc 0。
- `scripts/http_smoke.py`：status passed，25 个预设、162 次模型 HTTP 请求，真实 loopback TCP/HTTP，
  4.373 s，rc 0。
- `scripts/stress_offline.py`：status passed，2048 个穷举特征用例 + 2000 个扰动预设用例 =
  4048 次执行，0 失败，76.616 s，rc 0。

以上均在本次提交前的工作树上重跑（脚本刷新了 `results/checks/`、`results/http_smoke.json`、
`results/stress.json`）。等待人工课堂展示与所有者决定是否合入 `main`；本轮没有自动扩量。

---

## 5. 保留的失败记录

第一次 q6 真实运行失败，记录原样保留：

`results/v1/real_class6d_mtb/v1_class/0/mtb-P-0022916-q6.failed.json`，
`error = model output failed schema or source-integrity validation`。

原始 trace 显示 9 次 `model_usage`；失效输出包括 genomics 第二条 finding 的 scope 写成
`temporal`、drug 第二条写成 `molecular`、verifier 的 scope 写成 `temporal`，结构修复后
verifier 仍给出同类越界输出。这是模型行为，不是三组整改的回归；没有为此改代码，
而是把同一计划重跑到新目录 `real_class6d_mtb_r2`，成功记录保留在那里。
失败不会留下 claim ID（`tests/test_claim_scopes.py::test_failed_response_leaves_no_claim_ids_behind`）。

---

## 6. 启动入口

服务器侧（server21）：

```bash
cd ~/BioOncoFusion
set -a; . ~/.config/oncofusion/real-api.env; set +a
export ONCOFUSION_API_TOKEN="$(cat /path/to/demo-token)" ONCOFUSION_RESULTS_DIR=results/v1 \
       ONCOFUSION_DB=runtime/demo.sqlite3 ONCOFUSION_DEMO_REQUIRE_REAL=1
.venv/bin/python -m oncofusion serve --host 127.0.0.1 --port 8180
```

本机：

```bash
ssh -N -o ServerAliveInterval=20 -L 18180:127.0.0.1:8180 server21-direct
# 或再跑一层回环中继，访问 http://127.0.0.1:18181/app 无需粘贴令牌
python scripts/demo_relay.py
```

重启服务器实例必须按启动时记录的 PID 精确结束（共享主机，不要按进程名批量 kill）；
重启命令必须带上 `set -a; . ~/.config/oncofusion/real-api.env; set +a`，否则进程照常应答，
但 provider 会静默回落到 mock，只有 `/healthz` 的 `simulated` 字段会暴露。
完整说明见 `README.md` 的「演示网页 /app」。

---

## 7. 本轮未做

- 未合入 `main`（由项目所有者决定）。
- 未做方差分析、多 seed 重复、完整消融、31 例验收或单 Agent 对照。
- 未改供应商 API 内部；输出上限仍按服务声明的 5,000 执行。
- 语义核对仍是 AI 辅助（`results/SEMANTIC_CHECK_CLASS6_AI.md`），没有第二位人工评审。
