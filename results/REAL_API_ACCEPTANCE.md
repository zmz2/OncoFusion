# 真实 API 验收（第一版联调）

环境：server21（`/home/zhangmingzhou/BioOncoFusion`），provider `openai_compatible`，
Base URL `http://127.0.0.1:28180/v1`（server21 本机统一网关），模型 `hc-qwen38-27b-fp8`
（Qwen3.8-27B NVFP4，9 个副本：2×RTX5090 + 7×A40）。密钥只从本机
`~/.config/oncofusion/real-api.env`（600 权限，仓库之外）读取，未写入代码、日志或本文。

运行参数（全部对照一致）：`ONCOFUSION_JSON_MODE=true`、`ONCOFUSION_TOKEN_PARAMETER=max_tokens`、
`ONCOFUSION_SEND_TEMPERATURE=false`、`ONCOFUSION_SEND_SEED=false`、`ONCOFUSION_TIMEOUT=900`、
`ONCOFUSION_RETRIES=0`。不发送自创思考预算参数，采用供应商自身上限（总输出 5000、思考自限约 1500）。
价格未提供，故 `known_cost_usd=0` 仅表示可计算项为空，token 按供应商 usage 如实统计。

## 一、供应商协议实测（单请求，真实病例 role-1 请求重放）

| 条件 | 耗时 | finish | prompt | completion | reasoning | 正文字符 | JSON |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `max_tokens=1500`（默认思考） | 106.7s | length | 3523 | 1500 | 1499 | 0 | 空正文 |
| `max_tokens=1500` + latency | 115.1s | length | 3523 | 1500 | 1499 | 0 | 空正文 |
| `max_tokens=400` | 39.6s | length | 3523 | 400 | 400 | 0 | 空正文 |
| `max_tokens=1500` + 思考 300 | 441.1s | stop | 3523 | 941 | 299 | 2305 | 合法 |
| `max_tokens=5000`（供应商默认思考） | 370.4s | stop | 3523 | 2676 | 1499 | 3896 | 合法，schema 键齐全 |

结论：思考 token 计入 `max_tokens`，且默认会填满给定上限；本项目 v1 原声明的 `max_output_tokens=1500`
在本供应商上会把正文挤成 0 字符。采用供应商上限 5000 后正文与 JSON 正常。
`response_format={"type":"json_object"}` 被支持；无 key/错 key→401，非法 `X-HC-Workload`→400，
`max_tokens>5000`→400；`X-HC-Route-Pool` 可为 `rtx5090` 或 `legacy`（A40），实测两种池均能完成。

## 二、真实单示例（`demo --profile v1`，合成病例，非基准）

`results/v1/real_demo.json`：`status=completed`、`simulated=false`、墙钟 1268.2s、
`calls=7`、`http_attempts=7`（零重试）、`estimated_tokens=false`、
`input_tokens=14045`、`output_tokens=4797`、`tool_calls=6`；答案 `SUPPORTS`、2 条引用，
引用 quote 与偏移和来源逐字一致。逐角色 in/out：literature 1242/447、timeline 1353/581、
genomics 1753/693、pathology 2128/781、drug 2434/789、verifier 2472/911、decision 2663/595。

## 三、真实数据上发现并修复的实际缺陷

1. **CIViC 来源 id 无法被引用回填（系统性）**：适配器把每条病例的唯一文献 id 硬编码为 `evidence`
   （`oncofusion/datasets.py`），而模型按语义写出该文章真实 PMID（如 `pmid-25349473`），
   触发 `citation refers to an unavailable document`。首轮真实 CIViC smoke 中 v1 的 5/5 例
   全部在 literature 角色失败。修复：文档 id 改用来源标识（PMID→`pmid-<n>`；
   ASH/ASCO→`source-…`），与 `origin_id` 一致；新增回归
   `test_civic_document_is_addressed_by_its_source_identity`。全量测试 708 通过。
   受影响数据按 TASK 要求从原始文件重导到新目录 `data/civicfact-pmidids`：
   12476 例/1409 组，`inputs_sha256=165c8d3415eb8588dcbafcc10eae378e1a3d0be30c1b9698bfae78b2b2d7183d`，
   `labels_sha256=f3221fa1…` 与修订前相同（标签未变、仅输入身份变化，新旧结果不混算）。
2. **工程侧可运行性**：`scripts/run_study.py` 原为严格串行。单调用实测 40–450s，
   smoke（63+30 执行、≤1116 次调用）串行需 10 小时以上。新增 `--workers`（默认 1，行为不变），
   结果按病例顺序确定；并行与串行的逐样本指纹、状态、指标与 bootstrap 表在测试中完全一致。
3. **数据获取镜像**：`huggingface.co` 从 server21 不可达（000 超时），
   `acquire_mtb` 的三处官方域名改为可经 `ONCOFUSION_HF_ENDPOINT`/`HF_ENDPOINT` 覆盖，
   默认仍为官方域名，且实际 host 记入 `acquisition.json`；回归
   `test_acquire_mtb_honours_endpoint_override`。MTBBench 经镜像 revision 固定导入成功。

真实失败样本按规则保留为证据，未删除：
`results/v1/ABORTED_real_{mtb,civic}_smoke_cap1500`（输出 cap 1500 的截断）与
`results/v1/ABORTED_real_{mtb,civic}_smoke_docid_evidence`（自造引用 id）。

## 四、真实 smoke（进行中）

计划：`experiments/v1_{mtb,civic}_smoke_api5000.json`（由 v1 smoke 计划仅改
`max_output_tokens=5000` 生成，原 v1 计划文件保持不变）。
MTB：21 例/3 个 dev 患者组×3 系统=63 执行，≤756 调用，10 并发；
CIViC：10 例/3 个 dev 文章组×3 系统=30 执行，≤360 调用，6 并发（合计 16 在途）。

修复后 MTB 首例失败原因已变为真实模型行为：`quote must match exactly once when offsets are omitted`
（引文非逐字唯一），不是 id/协议问题。失败继续计入分母；是否在开发集统一启用
`schema_retries=1`（TASK §4 允许、所有对照一致、额外调用计费）待 smoke 量出真实失败率后决定。

## 五、剩余事项

- smoke 完成度、失败率、逐角色 token、p95 耗时、引用 quote 定位核验（`scripts/real_metrics.py`）。
- 真实开发集主对照（`v1_mtb_dev_main_api5000`：8 组/43 例/387 执行；
  `v1_civic_dev_main_api5000`：12 组/43 例/387 执行）；七机制消融按决定后置。
- 双人语义引用审查（精确 quote 只证明定位正确）、`DATA_ACCEPTANCE.md`、`FROZEN_PROTOCOL.md`、
  `FINAL_REPORT.md`。模拟与真实结果始终分开。

---

## 六、v1_fast（2026-10-18 阶段目标调整后新增）

阶段目标改为「真实 API 下稳定流畅的七 Agent 后端」。旧的三系统大计划链（774 次执行）已停止，
不再自动接力；中断前的结果保留在原目录。

**保持不变的**：七角色顺序与职责、来源/阶段隔离、引用必须落在可见来源、`/v1` 接口与
RunResult/Citation/Finding 结构、v1 配置与全部原 v1 计划文件。
**新增**：`oncofusion/profiles.py:v1_fast_config`（CLI `--profile v1_fast`，`GET /profiles` 目录新增 `v1_fast` 项）。

**关键机制：证据片段编号 + 服务端回填**
- `evidence.fragment_documents()` 把每份可见来源切成确定性编号片段（`<doc_id>:f01`，句子边界优先，
  每片段≤600 字符、每文档≤8 片段），角色只看到片段列表与去正文的来源花名册。
- 模型输出改为 `{"evidence_id": ...}`（`FragmentCitation`），后端 `resolve_fragment_citations()`
  回填 `document_id/quote/start/end` 后仍走原有 `check_citations` 与反射、跨来源、断言需引用等校验。
- 未知或外部编号（如 `d1:f99`、别的病例的 id、未来阶段文档的片段）一律 `ValueError`，运行可见失败；
  未来阶段文档根本不进入片段列表。
- 片段模式要求 `external_verification`，否则明确拒绝（反射没有可引用编号，不允许静默降级）。
- 每次 `model_usage` 轨迹新增 `seconds` 与 `evidence_fragments`，用于逐角色耗时表。
- 输出侧收紧：`findings_limit=3`、每发现最多 2 条编号引用、不再重复原文引文；`max_output_tokens`
  沿用已验证的供应商上限 5000；`schema_retries=1` 对所有系统统一。

**协议稳定性验证**：同一 MTB 病例、同配置下，HEAD 与工作树在 quote 模式的七次
`payload_sha256` 逐个相同（`97ed04d3… 79942329… 0c10ded0… 4dcbefb2… 3e5595f6… b0f17520… 6e5bb4e8…`），
即新增键只在 fragment 模式注入，旧 v1 输入字节不变。
遗留待查（不影响 v1_fast 新目录）：12:36–13:56 那批真实 quote 跑记录的 role-1 `payload_sha256`
（`05dcd039…`）与当前代码 mock 重放不同，而 `token_reservation`（18683）与 `source_ids` 完全一致，
说明是等长的内容差异；未在旧协议目录上续跑，故暂不据此下结论。

**真实 API 逐角色实测**（`results/v1/real_fast_civic`，首个完成病例，16 在途以内）

| 角色 | 秒 | in | out | HTTP 尝试 | estimated |
| --- | --- | --- | --- | --- | --- |
| literature | 63.6 | 1294 | 849 | 1 | false |
| timeline | 224.2 | 1620 | 1130 | 1 | false |
| genomics | 132.6 | 1986 | 777 | 1 | false |
| pathology | 98.1 | 2360 | 1093 | 1 | false |
| drug | 98.6 | 3007 | 1117 | 1 | false |
| verifier | 310.4 | 3352 | 1996 | 1 | false |
| decision | 99.6 | 4141 | 1282 | 1 | false |

单例 1,027.8s、in 17,760 / out 8,244；同数据集旧 quote 协议 p50 为 1,935s、in 18,153 / out 12,337
（`results/v1/real_civic_smoke`，14 例）→ 约快 47%、输出 token −33%，且 7 次调用零重试、零估算 usage。

**瓶颈判断**：供应商侧仍是主要约束——网关只有 `hc-qwen38-27b-fp8` 一个模型（`GET /v1/models` 实测），
不存在换更快模型的空间；单调用 60–310s 由思考+生成决定。因此优化方向是不让模型重复输出原文
（片段编号回填）并收紧输出结构，而不是加并发（小范围并行列为次优先级）。

**离线回归**：`tests/test_v1_fast.py` 10 项（片段确定性、回填精确偏移、未知/外部/畸形编号拒绝、
未来来源不进入可引用集合、payload 来源字符数下降、编号缺失可见失败、缺外部核验时拒绝、
逐角色 seconds 记录）；全量 718 通过、分支覆盖 97%。

### 6.1 同例真实对照（quote cap5000 vs v1_fast，11 个 MTB 配对 / 7 个 CIViC 配对）

| 指标 | MTB quote | MTB v1_fast | Δ | CIViC quote | CIViC v1_fast | Δ |
| --- | --- | --- | --- | --- | --- | --- |
| 单例秒 p50 | 2,337 | 2,021 | −370 | 1,935 | 1,561 | −374 |
| 输入 token/例 | 91,813 | 102,298 | +10,485 | 20,561 | 24,594 | +4,032 |
| 输出 token/例 | 17,143 | 14,400 | −2,743 | 13,933 | 12,854 | −1,079 |
| 硬失败 | 35.3%（零修复） | 0/22 例 | — | 27.3%（零修复） | 0/10 例 | — |
| HTTP 重试 | — | 0 | — | — | 0 | — |

同一病例的 mock 成分对照显示每调用传输的来源字符 12,931 → 994（花名册）+ 9,976（片段），整例 payload −12.4%；
但真实跑输入 token 反升，原因是**回填后的片段文本进入证据板被后续角色重复携带**：
真实病例每例 31.7 条引用、仅 4.5 个唯一片段，引用文本累计 12,666 字符而去重后 1,967 字符（约 3.8k token 为重复）。
下一步（当前两臂跑完后再动，避免破坏可比性）：证据板只带 `evidence_id` 与偏移、不带片段正文，
补「board 字符数下降」回归，并在新目录同时重跑 v1_fast 与 single_tools 作为新一轮基线。

### 6.2 下一轮基线（原型已量化，未在运行中的两臂上改动）

隔离树 `/tmp/fast2` 原型（补丁脚本 `/tmp/patch_fast2c.py`）：证据板只带 `evidence_id` 句柄
（句柄不在本调用可见片段内时退化为去掉 quote 的偏移对象），不再重复携带回填后的片段正文。
同一病例 mock 对照（quote vs 压缩版）：

| 病例 | quote payload 字符 | 压缩后 payload 字符 | Δ | board 占比 |
| --- | --- | --- | --- | --- |
| mtb-P-0022916-q0 | 140,588 | 113,443 | −19.3% | 17% → 8% |
| mtb-P-0009786-q2 | 193,296 | 181,878 | −5.9% | 21% → 9% |
| mtb-P-0027883-q7 | 305,940 | 288,826 | −5.6% | 19% → 9% |

对照当前上线形状（片段+带正文的板）：同病例 payload 123,163 → 113,443，再降 7.9%。
结论：6.1 的输入上升来自证据板重复携带片段文本（每例引用 31.7 条而唯一片段仅 4.5 个），
修好后片段模式才真正低于 quote 协议。合入条件：当前 v1_fast 与 single_tools 两臂全部跑完之后，
在新目录同时重跑两臂（改动会改变 implementation_digest，禁止与现有目录混算），
并补回归「board 只含句柄、不含 quote 文本」。

## 七、v1_fast 真实四臂完成（2026-10-18 16:50，PIPELINE COMPLETE）

四套 study 全部 `simulated=false`、**0 次 ProviderError 失败、0 次 HTTP 重试、0 例估算 usage**：

| 臂 | 样本 | 状态 | 每例调用 | 每例 token | 每例秒 p50/p95 | 引用完整性 |
| --- | --- | --- | --- | --- | --- | --- |
| MTB v1_fast | 21 例 / 3 组 | 20 completed + 1 budget_exhausted | 7.05 | 118,376 | 1,553 / 2,461 | 9/9 quote+offset |
| CIViC v1_fast | 10 例 / 3 组 | 10 completed | 7.00 | 34,955 | 1,399 / 1,629 | 8/8 quote+offset |
| MTB single_tools | 21 例 / 3 组 | 21 completed | 1.00 | 13,720 | 203 / 481 | 8/8 |
| CIViC single_tools | 10 例 / 3 组 | 10 completed | 1.00 | 3,164 | 133 / 224 | 8/8 |

逐角色耗时（v1_fast，秒 p50/p95）：
MTB literature 193/505、timeline 177/440、genomics 175/460、pathology 267/444、drug 226/425、verifier 295/428、decision 176/291；
CIViC literature 197/310、timeline 225/308、genomics 226/436、pathology 153/207、drug 154/244、verifier 174/236、decision 150/213。

失败分类（真实数据、全协议）：
- 硬失败 0（旧 quote 协议零修复时为 MTB 35.3%、CIViC 27.3%，全部 `schema/source-integrity` 类）。
- 唯一不完整样本 `mtb-P-0027883-q6` 为 `budget_exhausted`（输入 124,760 token，触发 v1 声明的 200,000 预检），
  按错误计入分母，不切换为成功。
- 费用：`known_cost_usd=0` 表示价格未提供（可计算项为空），不代表免费。

### 7.1 初步同例配对（v1_fast vs single_tools，同模型、同资料、同预算上限）

| 数据集 | 配对例数 | v1_fast 准确率 | single_tools 准确率 | 差值 | 聚类 bootstrap CI | 判定相反的样本 |
| --- | --- | --- | --- | --- | --- | --- |
| MTBBench | 21（3 组） | 0.619 | 0.619 | 0.000 | [0, 0] | 4（两两相反各 2） |
| CIViC-Fact | 10（3 组） | 0.500 | 0.500 | 0.000 | [0, 0] | 0（逐例判定相同） |

如实结论：在这 3 组×21 例与 3 组×10 例的联调样本上，七 Agent **没有观测到准确率收益**，
成本为单调用的 8.6×（MTB）与 11.1×（CIViC）token、7.6×/10.6× 时间；其中一例七 Agent 因预算耗尽判错、
单调用判对。样本量小且只有 3 个聚类，CI 退化，不作任何显著性声明；这也不推翻多 Agent 的价值假设，
只说明**当前形状下成本轴主导**。因此下一步是压缩成本（board 句柄化）而不是增加角色。

### 7.2 已合入的压缩修复与新基线

board 句柄化已合入正式树（证据板只带 `evidence_id`，句柄不在本调用可见片段内时退化为
「去掉 quote 的偏移对象」），并新增 2 条回归：
`test_board_carries_handles_not_resolved_quote_text`、
`test_cross_role_recite_of_a_board_handle_still_resolves`（跨角色复引句柄仍能解析，未破坏功能）。
同病例 mock 实测：board 字符 19,322→9,602、34,106→16,550（约 −50%），
整例 payload 123,163→113,443、199,434→181,878（−7.9%/−8.8%），相对 quote 协议为 −19.3%/−5.9%/−5.6%。
全量回归 **720 通过**（分支覆盖 97%）。压缩后的新基线四臂在 `results/v1/real_fast2_*`
独立目录重跑（代码变更改变 identity，禁止与 `real_fast_*` 混算）。

### 7.3 一处设计冲突（外部核验消融的前置条件）

片段引用模式要求 `external_verification`（缺核验时引擎显式拒绝），因此
`without_external_verification` 消融不能沿用 fragment 形状，只能在 quote 形状下运行；
这意味着该消融与 v1_fast 主臂不同形，须按不同协议分别报告，不能并入同一配对表。

## 八、压缩后新基线（real_fast2_*，19:11–19:50 同一时间窗）

四臂同窗运行，全部 `simulated=false`、**0 硬失败、0 HTTP 重试、0 估算 usage、引用完整性 8/8**：

| 臂 | 状态 | 每例调用 | 每例 token | 每例秒 p50/p95 |
| --- | --- | --- | --- | --- |
| MTB v1_fast2 | 21 completed | 7.00 | 101,880 | 295 / 321 |
| MTB single_tools | 21 completed | 1.00 | 13,710 | 38 / 44 |
| CIViC v1_fast2 | 10 completed | 7.00 | 30,627 | 223 / 236 |
| CIViC single_tools | 10 completed | 1.00 | 3,136 | 28 / 30 |

逐角色（v1_fast2，秒 p50/p95）：MTB literature 42.0/76.3、timeline 41.2/45.0、genomics 42.5/44.4、
pathology 43.5/46.5、drug 43.4/48.1、verifier 43.6/47.7、decision 39.0/42.8；CIViC 各角色 p50 29.4–33.6、p95 ≤35.6。

### 8.1 因果与负载的分离（重要）

同例配对（`real_fast_mtb` vs `real_fast2_mtb`，各 21 例）：token/例 118,376 → 101,880（**−13.9%**）、
CIViC 34,955 → 30,627（**−12.4%**）。这是压缩带来的**成本**效应，可因果归因。

耗时从每例 1,553s 降到 295s **不能**记作压缩效果：两窗口的 literature 首次调用输入 token 完全相同
（均为 8,666.2，因为该角色还没有证据板），而单调用 p50 从 193.3s 变成 42.0s（4.6×）。
相同输入 token、不同耗时，说明这一段差异来自共享网关的时段负载（白天 4 个租户在用、晚间空闲），
不是我们的 payload 形状。因此协议上要求**同一时间窗内跑完对照**，本节四臂满足；跨窗耗时不可比。

### 8.2 唯一预算失败样本已消失（因果）

`mtb-P-0027883-q6`：压缩前 `budget_exhausted`（输入 124,760 token，撞 200,000 预检）→
压缩后 `completed`（输入 102,046 token，判定 B）。原因链清楚：证据板不再重复携带片段正文，
预检的 `usage + reserved` 下降，样本留在有效分母内而不是按错计入。

### 8.3 运行间波动使 n=21/3 组的差异不可解释

同一批 21 例在两窗各跑一次，逐例比对：
- v1_fast：2 例变化（1 例状态由耗尽变完成，1 例答案 B→A），准确率 0.619 → 0.619。
- single_tools：2 例答案翻转（含同一 `mtb-P-0022916-q5` A↔B），准确率 **0.619 → 0.524**。

同窗配对：MTB 七 Agent 0.619 vs 单调用 0.524（差 +0.095，CI 覆盖 0）、CIViC 0.500 vs 0.500（逐例相同）。
但白天窗的同一配对给出 0.619 vs 0.619。两臂都出现约 ±2 例（≈±0.095）的运行间翻转，
所以在 21 例 / 3 个聚会上，**无论“打平”还是“+0.095”都不构成可解释结论**；
这正是协议里 seeds=[0,1,2] 重复存在的原因，下一轮需按重复设计执行后再谈收益。

### 8.4 当前后端状态

七 Agent 在真实 API 上稳定流畅：单窗内 21+10 例、7 角色、约 40 分钟跑完，
零硬失败、零重试、逐角色 30–46s、每例 101,880 / 30,627 token、全部引用可机械定位。
工程回归 720 通过（分支覆盖 97%），`/v1` 与 native/langgraph 双后端契约保持。

## 九、演示网页端到端验收（2026-10-19，真实 API）

页面 `GET /app`（单文件、无外部资源、只用既有 `/v1` 接口），实例绑定 `127.0.0.1:8180`，
`/healthz` 报 `provider openai_compatible`、`simulated:false`。

浏览器实测通过项：徽章显示模型与「配置 v1_fast（七角色 · 片段引用 · 输出上限 5000 · 统一一次修复）」；
7 张角色卡就位；历史列表 62 条真实结果；4 个推荐案例入口（MTB 多模态、CIViC 变异·癌种·药物、
冲突/证据不足、错误样例）；点推荐案例即回放（7 卡片齐、答案 REVISIONS、in 15,892/out 13,167、222.4s、
引用与未解决项可展开）；上传 JSONL 可选择其中一条并完成输入检查；刷新页面后自动恢复到
「真实运行中」的任务（run_id + 状态 + 事件续读）。

两次由网页新发起的真实运行均 `succeeded`（逐角色 `attempts=1`、`estimated=False`）：

| run | 病例 | 答案 | 调用 | in / out token | 逐角色秒（7 角色） |
| --- | --- | --- | --- | --- | --- |
| `run-16330620f5a1…` | synthetic-support | SUPPORTS | 7 | 14,567 / 12,215 | 147.3, 139.3, 115.7, 111.0, 89.3, 109.3, 95.8 |
| `run-3b6dbc0a6caa…` | mtb-P-0027883-q7 | A | 7 | 117,350 / 13,249 | 133.1, 107.1, 150.3, 119.4, 97.0, 145.2, 75.9（40 个证据片段） |

E2E 期间另开的无鉴权实例（仅端口 8181、独立 sqlite）在验收后按精确 PID 关闭，只保留带令牌的 8180；
共享主机上不做按名批量 kill。

PR 阻塞说明：本机可用凭据是 zmz2 的 **SSH 身份**（keychain 无 HTTPS 令牌、无 gh 登录），
分支 `codex/v1-fast-real-api-20261019` 已用 SSH 推送成功，但 GitHub 的 PR 只能经 HTTPS API/CLI 创建，
SSH 身份无法建 PR（GitHub 也不提供 GitLab 式 push option）。需 `gh auth login` 或提供 fine-grained 令牌后代开。

## 十、演示页可读性改版与两条新真实运行（2026-10-19 13:00–13:55）

按「读不到输入是什么、不知道 Agent 之间怎么协作、不知道他们在干什么」的反馈重排信息层：

- 输入面板：任务类型、题号、模型看到的原题逐字（CIViC 的结构化输入折叠展开）、每份可见资料的类别／长度／正文；CIViC 另给后端解析出的主张要素表和病例实体表。
- 角色卡片：中文职责 + 后端递给它的证据片段数 + 前序**已完成**角色交来的结论数与未解决项数 + 本步产出的结论数、原文引用数、移交下去的未解决项 + 逐角色 token、秒、HTTP 重试、结构修复标记。
- 关系图：「来源被哪些角色引用」和「角色之间传递了什么」（逐跳的结论数与未解决项数）。
- 引用对照：模型给出的片段与原文对应区间并排，偏移量可见。
- 数据集页：说明改为中文；逐角色平均耗时补上「综合决策」行并显示真实秒数——此前恒为 0.0，根因是我改了索引聚合却没重启服务进程，旧模块还在应答。
- 删掉两个从未被赋值的字段（上游证据板条目、上游未解决项），改为按实际输出推导，避免页面显示永远为 0 的假指标。

运维教训：手工重启演示服务时漏了 `set -a; . ~/.config/oncofusion/real-api.env; set +a`，进程照常应答但 provider 回落成 mock，一次「真实运行」其实是模拟跑（`run-587099fd954847cc9b57e16afc1694de`，7 次调用 6 秒返回，`/healthz` 的 `simulated` 为 true 才暴露）。看护脚本改为每 2 分钟读 `/healthz`，不可达或发现 mock 就按 pidfile（`/tmp/of_demo_api.pid`）精确重启，README 记录了同样的坑。

事件流早断的恢复：SSE 经回环中继偶尔在任务未结束时被关闭，刷新页面后角色卡片会全空。现在 `attach()` 返回后用 `/v1/runs/{id}/events?after=cursor` 轮询补齐，实测刷新后 5 个已完成角色全部复原（cursor 28，逐角色秒数与来源列表都在）。

新发起的两条真实运行（同一 v1_fast 配置、同一输入、真实 API）：

| 病例 | 状态 | 调用 | in／out token | 端到端秒 | 答案／历史答案／标签 |
| --- | --- | --- | --- | --- | --- |
| `mtb-P-0027883-q7` | succeeded | 7 | 120317／14103 | 961.3 | A／A／A |
| `civic-3e09dc9e-43af-4022-88ec-a31f18cfaf42` | succeeded | 7 | 16130／13650 | 962.2 | REVISIONS／REVISIONS／REVISIONS |

token 轮廓与历史记录一致（±1%），但逐角色 80–170 秒，是原窗口 34–40 秒的 2.5–4 倍；两条并发跑在同一个共享卡池上，所以延迟只能同窗口比较，答案与成本可以同病例配对。

回归：`pytest -q` 726 passed；`scripts/run_checks.py` 覆盖率 97%；`scripts/http_smoke.py` passed；`scripts/stress_offline.py` 4048 例 0 失败。提交 `6b6a675`（页面与索引聚合）、`483b4d9`（措辞与 README）、`f1e0a4b`（事件轮询），均已推到 `origin/codex/v1-fast-real-api-20261019`。

### 10.1 追加：回放一致性与事件流看护（同日午后）

第三、四条新发起的真实运行（同一病例 `mtb-P-0027883-q7`、同一 v1_fast 配置）：

| run_id | 状态 | 调用 | in／out token | 端到端秒 | 答案／标签 |
| --- | --- | --- | --- | --- | --- |
| `run-5c8ad394…` | succeeded | 7 | 120317／14103 | 961.3 | A／A |
| `run-7826ef8c…` | succeeded | 7 | 119033／13756 | 779.7 | A／A |

同一病例两次真实执行的 token 差 1.1%，答案一致；端到端秒数差 19% 仍是卡池负载，不是配置差异。

修掉的三处"刷新后不一致"：

- 事件流能在任务未结束时被中途关掉（回环中继与网络抖动都会造成）。`attach()` 返回后改用
  `/v1/runs/{id}/events?after=cursor` 每 5 秒补取，任务终态才停。
- 单个角色最长 179 秒不产生任何帧，而假死的 SSE 会让页面停在它看到的最后一帧。现在读取最多静默
  90 秒就主动断开回到轮询；实测刷新后七角色、最终答案与"任务结束：succeeded"全部恢复。
- 刷新后页面只恢复了过程，没恢复输入：默认样例会把另一道病例写进输入面板，关系图也没有来源行。
  现在发起运行时把所选输入与 run_id 一起存进本机存储，`resume()` 读回并自动重跑输入检查，
  「发起真实 API 运行」按钮随之可用；若输入确实没被保存，页面明说这一点，不再拿别人的病例冒充。
  引用块在缺正文时显示后端回填的片段并标注，关系图仍列出被引用但不在本页的来源。
