# OncoFusion：稳妥第一版接手任务

## 先锁定目标

课题是**肿瘤异构生物医学证据的多智能体整合与核验**。主任务采用MTBBench逐阶段文本病例问答；CIViC-Fact原生主张核验与段落检索作为组件评测。答案必须保留来源和证据适用条件。药物关系可以作为研究解释，但这两套数据的标准答案不验证最佳治疗方案。

阅读顺序：本文件 → docs/V1_REVIEW.md → docs/DATA.md → docs/EVALUATION.md → verification/README.md。实际复用层级见upstream_manifest.json与docs/AGENT_REUSE_AUDIT.md。

当前第一版配置在`oncofusion/profiles.py:v1_config`：**LangGraph固定七角色、同一模型API、结构化证据、文献先行、最新角色工作板、零自动补证**。角色顺序为 Literature → Timeline → Genomics → Pathology & Context → Drug → Verifier → Decision。第一版所有系统每病例统一200,000 token总上限，模型/工具调用上限各12，常规流程7次模型调用。该数值是总预算上限，实际消费按usage统计；先跑smoke估算费用。固定流程优先；保留原生执行器用于等价测试，原25预设和大型计划作为后续实验。

LangGraph和ToolUniverse是实际运行依赖；GeneAgent/TxAgent/PaperQA2是明确注明的方法适配，完整Agent和专用权重未加载。首版不做网页、图像、自由群聊、强化学习或持久化图checkpoint。已有SQLite任务持久化、SSE、实验resume继续使用。

## 1. 安装与回归

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,graph]'
export ONCOFUSION_PROVIDER=mock
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
python scripts/run_checks.py
python scripts/check_v1.py --out results/v1/contracts.json
python scripts/http_smoke.py
python scripts/stress_offline.py
python -m oncofusion demo --profile v1 --out results/v1/demo.json
```

Python3.11–3.13；CPU可运行。PowerShell使用`.venv\Scripts\Activate.ps1`及`$env:变量="值"`。核心安装`.[dev]`可运行`check_v1.py --backend native`；图依赖缺失必须明确报错。测试数量以当前实际输出为准，旧验证JSON是历史记录。模型响应为模拟器，工程通过不充当真实医学成绩。

## 2. 获取正式数据并审计角色覆盖

```bash
python scripts/prepare_data.py mtbbench --raw data/raw/mtbbench --out data/mtbbench --download --accept-source-terms
python scripts/prepare_data.py civicfact --raw data/raw/civicfact --out data/civicfact --download --accept-source-terms
python scripts/retrieval_study.py prepare --raw data/raw/civic_retrieval --out data/civic_retrieval --download --accept-source-terms
```

下载前阅读docs/DATA的来源条款。原资料留在data/；标签在_gold/，Agent仅见允许输入。MTBBench按患者分组且按阶段暴露资料；CIViC保持来源分组，固定2026.06.09原生SUPPORTS/REVISIONS/NEI词表。REVISIONS是部分支持但主张需修订，与REFUTES分开。标签、gold修订文本和人工解释始终隔离。

重点读audit中的版本、标签、样本数、缺失字段、分区、排除项和新增role_coverage。本轮修复2026版type=claim对象、单数disease和therapies列表解析。已有CIViC prepared资料应由原始文件重导到新目录，重记inputs SHA256；原标签不变，旧结果保持独立。检查各角色实际拥有的输入，尤其CIViC给定证据任务的单文献条件。检索排除项先人工确认，再用已有资料加--allow-exclusions重跑；结果保留真实分母。

`import-civic/import-mtb`命令现在与prepare_data共用适配和审计，避免同一来源走两个入口形成不同输入。导入与评测都联合检查Case patient_id和Gold group_id；同患者改组名无法绕过隔离。

## 3. 先做三系统小规模联调

```bash
python scripts/run_study.py --plan experiments/v1_mtb_smoke.json --dataset data/mtbbench --out results/v1/mock_mtb --dry-run
python scripts/run_study.py --plan experiments/v1_mtb_smoke.json --dataset data/mtbbench --out results/v1/mock_mtb
python scripts/run_study.py --plan experiments/v1_civic_smoke.json --dataset data/civicfact --out results/v1/mock_civic
```

每套为3系统×1次重复×3个开发集患者/文章组（每组全部样本）：v1、single_tools、single_iterative。dry-run显示实际样本数、上限和角色覆盖。这是联调子集，不据此声称科学显著性。

## 4. 接本地已有真实API

密钥通过用户本地环境读取，保持在git之外。使用兼容Chat Completions的供应商：

```bash
export ONCOFUSION_PROVIDER=openai_compatible
export ONCOFUSION_BASE_URL='https://YOUR_PROVIDER/v1'
export ONCOFUSION_MODEL='YOUR_MODEL_ID'
export ONCOFUSION_API_KEY='YOUR_LOCAL_KEY'
export ONCOFUSION_JSON_MODE=true
export ONCOFUSION_TOKEN_PARAMETER=max_tokens
export ONCOFUSION_SEND_TEMPERATURE=false
export ONCOFUSION_SEND_SEED=false
export ONCOFUSION_TIMEOUT=60
export ONCOFUSION_RETRIES=2
# 按供应商实际USD/百万token设置INPUT_PRICE、OUTPUT_PRICE后再估算费用
python -m oncofusion demo --profile v1 --out results/v1/real_demo.json --allow-remote
```

模型端只接已有API，无需训练或GPU。BASE_URL后追加/chat/completions；不同供应商按实际协议设置max_completion_tokens、JSON_MODE等。真实失败必须保留，不切换模拟成功。真实API边界出错按返回定位并加回归测试。

若输出schema失败，轨迹含有界原始输出和校验错误。开发集可明确启用schema_retries=1，但所有对照保持一致；额外调用计入费用。HTTP200输出截断时已返回usage仍统计。usage缺失/HTTP重试可能产生未知费用，报告cost_complete=false。

运行上节smoke，改用results/v1/real_*目录并加--allow-remote。先记录失败率、平均token、p95时间、费用及引用样本。真实调用默认execution-cap=1000，超过时先dry-run并明确提高，不自动扩大消费。未审核自定义资料data_class=unreviewed在Engine/API都拒绝外发，审核后显式标为deidentified并给出外发同意。

## 5. 主实验与七机制消融

```bash
python scripts/run_study.py --plan experiments/v1_mtb_ablations.json --dataset data/mtbbench --out results/v1/real_mtb_dev --dry-run
python scripts/run_study.py --plan experiments/v1_civic_ablations.json --dataset data/civicfact --out results/v1/real_civic_dev --dry-run
```

这两套是11配置×3次重复、全部开发集组：v1、工具型单Agent、七调用通用单Agent、固定五Agent、七项内部机制消融。七机制依次为变异归一化、癌种匹配、药物方向、检索重排、时间整理、外部核验、来源去重。资料、模型、工具可访问范围、修复设置和预算上限一致，实际token差异另行报告。给定单文献数据上的重排不作有效性结论，独立检索任务提供对应评测。

审核费用后明确执行cap并加--allow-remote；resume保留已失败项，只有--retry-failed会重新消费。改代码、模型、数据或配置时使用新目录。七项机制是预注册假设，收益为零也照实报告。旧25预设、41配置、24配置计划后置，不是本轮必做的三套重复任务。

## 6. 来源/通路扩展（可选，与正式基准分开）

需要自定义异构来源研究时：

```bash
python -m pip install -e '.[biomedical]'
python scripts/check_upstream.py --out results/v1/upstream.json
# 额外访问一次公开MyGene数据库，仅此行联网，无商业LLM
python scripts/check_upstream.py --out results/v1/mygene_live.json --live-database
# 示例计划只含公开实体；使用前审核查询和来源条款
python scripts/prepare_sources.py --plan experiments/public_pathway_plan.json --out data/pathway_snapshot --allow-remote
```

白名单7项：MyGene、UniProt、DGIdb、OpenTargets、PubMed、Reactome蛋白到通路、Reactome通路详情。实际SDK负责执行，版本固定。通路成员关系与变异功能、患者通路活动分开；合法空查询结果只表示该查询未命中。需要把快照用于自定义已审核synthesis病例时添加--case；默认不自动提交患者文本或从病历生成外部查询。

快照记录查询、响应、版本、时间和哈希。它们只可附加当前、已审核的自定义synthesis任务。标准MCQ/verification及历史病例继续封闭。固定输入是稳妥第一版的选择；实时自主工具Agent需要额外协议和完整成本跟踪后再开发。

## 7. 报告、冻结测试集和网页契约

主任务报告患者聚类准确率及配对bootstrap；组件任务报告原生Macro-F1、独立检索Recall/AP；所有失败保留在分母。报告角色输入覆盖、至少6个成功/失败/纠错案例及双人语义引用审查。精确quote匹配只证明定位正确，语义支持需实际审查。

```bash
python scripts/build_report.py --study results/v1/real_mtb_dev/study.json --out results/v1/reports/mtb
python scripts/review_citations.py export --study results/v1/real_civic_dev --inputs data/civicfact/inputs.jsonl --out results/v1/review --limit 200
```

在results/FROZEN_PROTOCOL.md冻结代码SHA、模型、提示、预算、源版本、划分及主要比较。由同一v1开发计划只改name/split生成测试计划，冻结后再运行。旧版本test_complete实验计划属于更大的协议，避免混用。

网页继续走/v1：GET /profiles读取v1.config → /profiles/v1/example或上传资料 → POST /cases/inspect检查输入覆盖 → POST /runs带config和Idempotency-Key → 状态/事件/SSE/graph。/graph已包含最终答案与直接来源。缺图依赖返回503并且不创建任务；未审核远程资料返回422。API状态成功为succeeded，result.status为completed。

服务保持单ASGI进程，研究成员共享Bearer工作区。生产多用户需要独立授权与队列设计。保持已有API字段兼容；新网页避免省略config而落入历史默认预设。

交付results/REAL_API_ACCEPTANCE.md、DATA_ACCEPTANCE.md、FROZEN_PROTOCOL.md、FINAL_REPORT.md及脚本结果。（2026-10-19 更新：所有者改为明确指示把 data/ 与 results/ 全量提交进公开仓库，见 data/README.md 的许可提醒；密钥与令牌仍然留本地，提交前已逐文件核对。）下一步的主要工作是实际API与科学验收，不再扩张Agent数量。

## 8. 当前阶段：真实 API 流畅性优先（2026-10-18 起，取代第 5 节的启动顺序）

阶段目标改为**在真实 API 上交付稳定、流畅的七 Agent 后端**。第 3 节的三系统×全 dev 计划与第 5 节的
11 配置×3 次重复矩阵不再自动接力；`results/v1/ABORTED_*` 保留为历史证据，不并入新协议统计。

### 8.1 供应商实测事实（server21 统一网关，模型 `hc-qwen38-27b-fp8`）

- `GET /v1/models` 只返回这一个模型，不存在“换更快模型”的选项；瓶颈在单调用生成时间。
- 思考 token 计入 `max_tokens`，且不显式设预算时会填满给定上限：`max_tokens=1500` 实测
  `reasoning=1499`、正文 0 字符；`max_tokens=400` 同理。采用供应商上限 5000 后
  `reasoning=1499` 自限、正文 3896 字符、JSON 合法。
- 单调用 60–450s（池不同：`rtx5090` 与 `legacy`/A40），因此 `ONCOFUSION_TIMEOUT=900`、
  `ONCOFUSION_RETRIES=0`、`ONCOFUSION_SEND_TEMPERATURE=false`、`ONCOFUSION_SEND_SEED=false`、
  `ONCOFUSION_JSON_MODE=true`、`ONCOFUSION_TOKEN_PARAMETER=max_tokens`。
  密钥只从本机 `~/.config/oncofusion/real-api.env`（600，仓库外）读取，不进代码、日志或提交。
- A40 租约至 2026-10-21 16:56:56，到期后不能把该池计入容量。

### 8.2 v1_fast 配置

`oncofusion/profiles.py:v1_fast_config`，CLI `--profile v1_fast`，`GET /profiles` 增加 `v1_fast` 项。
保留七角色、来源/阶段隔离、共享证据板与 `/v1` 接口；变化是：

1. **证据片段编号**：后端把可见来源切成确定性的 `<doc_id>:fNN` 片段，角色读片段、输出
   `{"evidence_id": ...}`，由 `resolve_fragment_citations()` 回填 `document_id/quote/start/end`，
   再走原有引用完整性校验。未知编号、外部病例编号、未来阶段文档编号都显式失败；
   片段模式要求 `external_verification`，缺核验时拒绝而不是静默降级。
2. **输出收紧**：`max_output_tokens=5000`（供应商上限）、`findings_limit=3`、每发现最多 2 条编号引用，
   角色不再重复抄写原文；`schema_retries=1` 对所有系统统一。
3. **来源去重复**：片段模式下去掉 `sources` 的正文字段，另给来源花名册与真实字符数，
   减少同一原文在多角色间反复传输。
4. 逐角色耗时进入轨迹（`model_usage.seconds`、`evidence_fragments`），供耗时表与预算核算使用。

旧 v1 输入字节未变：同一病例同配置下，HEAD 与工作树的七次 `payload_sha256` 逐个一致。

### 8.3 本阶段执行顺序

1. `experiments/v1_fast_{mtb,civic}_smoke.json`：沿用第 3 节样本（21 例 MTB、10 例 CIViC，各一次），
   先交付七 Agent 的可靠性与速度：失败率、逐角色耗时、实际 token、重试与 usage 完整性。
2. 达标后再跑 `experiments/v1_fast_{mtb,civic}_control.json`（`single_tools`，同样 31 例）作对照。
3. `single_iterative`、三次重复、完整消融与测试集评测全部后置；只有在余量内才在预先固定的 10 例上做
   一项外部核验消融。小范围并行（`run_study.py --workers`，默认 1、并行与串行逐样本一致）属次优先级，
   先保证共享状态与预算安全。
4. 每步产出写入新目录；新旧协议、模拟与真实结果分开，失败与超预算样本保留在分母。

### 8.4 交付物

`results/REAL_API_ACCEPTANCE.md`（供应商协议实测、缺陷与修复、逐角色耗时表、失败分类、token/费用）、
逐角色耗时表与初步对照（`scripts/real_metrics.py`）、6 个可人工检查案例
（`scripts/review_citations.py export`）、`DATA_ACCEPTANCE.md` 与冻结协议说明。

### 8.5 本轮实测结果（2026-10-18 16:50，真实 API）

四臂全部完成且 **0 次硬失败、0 次 HTTP 重试、0 例估算 usage**：
七 Agent MTB 21 例 = 20 completed + 1 `budget_exhausted`、CIViC 10 例全 completed；
逐角色 p50 149–295s、p95 ≤505s；每例 token：MTB 118,376 / CIViC 34,955（单调用 13,720 / 3,164）。
p50 在全文统一指**中位数**：样本数为偶数时取中间两数均值，`compare_arms.py`、`real_metrics.py` 与
`library.dataset_summary` 用同一函数，数据集页不再取“中间偏上”的那个样本。

同例配对：**v1_fast 与 single_tools 准确率相同**（MTB 0.619/0.619，CIViC 0.500/0.500，
CI 退化 [0,0]，仅 3 个聚类，不作显著性声明）；七 Agent 成本为 8.6×（MTB）、11.1×（CIViC）token。
结论：当前形状下成本轴主导。下一轮基线已把证据板改为只带 `evidence_id` 句柄
（同例 payload −7.9%~−19.3%，board 字符约 −50%），压缩后的四臂在 `real_fast2_*` 新目录重跑。
交付表与失败分类见 `results/REAL_API_ACCEPTANCE.md` 第七节，案例清单
`results/HUMAN_CHECK_CASES.md`，数据审计 `results/DATA_ACCEPTANCE.md`，
逐角色表由 `scripts/real_metrics.py` 生成，同例配对由 `scripts/compare_arms.py` 生成。

待办：`without_external_verification` 消融与片段模式不同形（引擎显式要求核验开启），
只能在 quote 形状下单独报告，不并入本配对表；三次重复、完整消融与测试集仍后置，
且 CIViC 全 dev（1,044 例）在共享网关上不可行，需要预先固定的抽样协议。

### 8.6 压缩后新基线结论（19:50，同窗四臂，全部真实 API）

七 Agent 后端已达成阶段目标：21+10 例在同窗约 40 分钟跑完，**0 硬失败、0 HTTP 重试、0 估算 usage、
引用 100% 可机械定位**；逐角色 p50 30–44s、每例 token 101,880（MTB）/ 30,627（CIViC），
比压缩前分别 −13.9% / −12.4%，且原本唯一触发 200k 预检耗尽的 `mtb-P-0027883-q6` 现在正常完成。

耗时在同窗内大幅下降（每例 1,553s→295s）主要是共享网关时段负载：两窗 literature 首次调用输入 token
完全相同（8,666.2）而单调用 193s→42s，故跨窗耗时不可比，实验必须同窗跑完对照。

准确率仍不可解释：同窗配对 MTB 0.619 vs 单调用 0.524、CIViC 0.500 vs 0.500，
但同一批病例在两个时段各有约 2 例答案翻转（single_tools 0.619→0.524），
n=21/3 个聚类下 ±0.095 属运行间噪声。下一步若继续，只做 seeds=[0,1,2] 的重复主对照（同窗、同预算上限），
不再扩角色；`without_external_verification` 消融只能在 quote 形状下单独报告。
外部核验消融、三次重复与完整矩阵仍按剩余资源决定；A40 租约 10-21 16:56:56 到期前需完成真实数据实验窗口。

## 9. 演示优先阶段（2026-10-19 起，本轮唯一主线）

本轮只交付**可直接打开、操作、展示的 OncoFusion demo**：现有七 Agent 后端 + 真实 API + 一轮真实数据集结果。
方差分析、多 seeds、显著性检验、完整消融与全量开发集统一后置；`pipeline4` 自动接力已关闭，
`results/v1/real_var_mtb` 保留已完成的 21 条样本，不与后续混算。

### 9.1 已实现

允许新增**最小网页展示层**（单文件、无构建、不加载外部资源）：`GET /app` 由现有 FastAPI 服务提供，
只复用既有 `/v1` 接口；新增只读接口 `GET /v1/configs/demo`（返回 v1_fast 配置，避免前端落入历史默认预设）、
`GET /v1/library`、`GET /v1/library/item?item_id=…`、`GET /v1/datasets/summary`。
结果回放走 `oncofusion/library.py` 的显式白名单（只索引 `real_fast2_*` 四套已完成真实运行），
调用方拿不透明 id，越界或路径样式 id 直接 404，不公开 results 目录结构。

页面闭环：选择输入（内置示例 / MTBBench 与 CIViC-Fact 真实开发集样例 / 上传 JSON 或 JSONL 并选其中一条）
→ 输入检查（任务类型、问题、资料类别、可见性警告）→ 发起真实运行（202 + run_id + 状态）
→ 事件驱动七角色卡片（running/done/failed、逐角色 token 与秒、结构化发现、引用、未解决项，
新增 `agent_reported` 事件让角色产出在完成时就可见）→ 最终答案、解释、引用可展开原文片段与偏移、
总耗时/调用/token → 失败给出原因并保留已完成步骤 → 62 条历史真实结果回放（明确区分“真实运行中”与“历史回放”）
→ “数据集结果”页展示 MTB 21 例与 CIViC 10 例的七 Agent 与 single_tools 对照。
刷新或重开后可凭 run_id 继续查询（浏览器保存 last run，服务器 `GET /v1/runs` 列最近任务）。
密钥只在服务器环境变量与本机演示令牌中，页面不显示。

### 9.2 本轮验收

`/app` 可打开；内置示例可发起真实运行；上传协议内 JSON 可完成检查与运行；七 Agent 过程可见；
答案与引用可展开；历史真实结果可回放；数据集页展示两组对照；刷新后可查已有任务。
真实链路至少完成两次新发起的运行。回归：`run_checks.py`、`http_smoke.py`、`stress_offline.py`
与新增 `tests/test_demo_app.py`（页面自包含、demo 配置、七角色事件顺序、回放白名单与越界拒绝）。

### 9.3 展示数据集结果（同版本真实结果，小规模开发集）

MTBBench dev 3 组 21 例：v1_fast 准确率 0.619、完成率 21/21、7 调用/例、约 101,880 token/例；
single_tools 0.5238、1 调用、13,710 token/例。CIViC-Fact dev 3 组 10 例：两臂均 0.500，
七 Agent 30,627 token/例、单调用 3,136。页面注明这是开发集验收，不宣称七 Agent 显著更优。

### 9.4 可读性迭代与运维护栏（2026-10-19 下午）

评审指出「读不到输入是什么、不知道 Agent 之间怎么协作、不知道他们在干什么」，页面据此改为：
输入面板给出原题逐字与每份可见资料的正文；每张角色卡写明职责、后端递给它的证据片段数、
前序已完成角色交来的结论数与未解决项数、本步产出与移交；关系图给出「来源→引用角色」和
「角色→下一角色传递了什么」；引用块并排显示模型片段与原文偏移；数据集页说明中文化，
逐角色耗时补上综合决策行。两个从未赋值的假指标字段（上游证据板条目、上游未解决项）已删除。

两条新发起的真实运行（`mtb-P-0027883-q7` 961.3s／A，`civic-3e09dc9e…` 962.2s／REVISIONS）
都与历史答案和标签一致，token 轮廓 ±1%，但逐角色 80–170s 是原窗口 34–40s 的 2.5–4 倍，
说明延迟只能同窗口比较。

护栏：重启演示服务必须带 `real-api.env`，否则进程照常应答而 provider 静默回落 mock
（本轮误跑的一次模拟运行已在验收文档记录）；看护脚本每 2 分钟按 `/healthz` 的 `simulated`
判定并按 pidfile 精确重启。SSE 经中继早断时改用 `/v1/runs/{id}/events?after=cursor` 轮询补齐，
刷新页面不再丢过程。

## 10. 课堂展示前的最后一轮（2026-10-19 下午起，取代第 9 节的交付顺序）

主线仍是可操作课堂 demo；方差、多 seed、全量消融的自动接力保持关闭。

1. 真实输入与角色任务：证据候选覆盖整篇可见资料，按记录边界分段、换行只前进 1 字符，
   每份资料保底送入首段、末段与最新日期事件，其余按问题与关键字段在预算内挑选；
   原始来源／可见文档／实际送入片段三个概念分开记录，节点级 `evidence_ids` 与覆盖随事件落盘。
   任务分成预测型 MTB MCQ、给定证据 CIViC 核验与自定义多来源综合；
   五个专业角色用 scope／evidence_level／material_status 声明自己在讲哪一层，缺料写
   not_applicable 或 unknown，越层的结论由后端拒绝。
2. 真实协作：保留固定七角色 LangGraph 拓扑，新增 claim_id、author_role、used_claim_ids、
   逐主张核验结论与决策采用/排除清单；旧结果与旧接口保持可读，协议版本写在配置里。
3. 工程：demo 启动可要求真实 provider；用量与逐角色统计累加修复调用；回放索引按指纹缓存并
   收紧白名单；CI 与容器分别声明 native 与 graph 环境；中继区分连接与读超并加心跳。
4. 交付前只跑一轮固定 6 例真实质量检查（覆盖真实分子资料、长时间线、单文献核验、冲突与不足），
   选 3 个可直接回放的课堂案例；既有结果作为历史保留，输入或协议改变的新结果另目录存放。
   成绩按试运行表述，样本数与来源组数一并给出。

### 10.1 本轮实测结果（2026-10-19 晚，真实 API，seed 0，一轮）

- 六例全部完成（`results/v1/real_class6c_mtb`、`real_class6c_civic`）：每例 7 次调用、零 HTTP 重试、
  零结构修复。MTBBench 4 问（3 位患者）3/4 与标签一致；CIViC-Fact 2 条主张（2 篇文献）1/2 与标签一致。
  两臂在同一时间窗内跑完，只作试运行表述。
- 课堂三例：`mtb-P-0027883-q7`（候选 46 段送入 26 段，答对）、`civic-60a33dc8…`（来源不对题，
  9 条主张里 7 条写 unknown 且无引用，决策排除 7 条，答 NEI 与标签一致）、
  `mtb-P-0006191-q0`（8 段候选全部送入，答错：以“最新 CT 无癌”外推为不复发，标签是复发）。
- 输入截尾已量化：`scripts/fragment_truncation_audit.py` 重放 56492fd 的前缀走法，
  183 例里 126 例有文档截尾、1051 份文档里 181 份被截，看不见的原文 310,902 / 1,980,042 字符（15.7%）；
  本轮 4 个 MTB 课堂样例单独重放为 22.9%。这 15.7% 是**旧前缀走法的尾部丢失**；
  结果行里的 `tail_dropped` 不是同一口径——它现在的含义是「该节点的候选集里有片段没进提示」，
  未送入的片段可以在任何位置，不等于只截掉了前缀。
- 修掉两处本轮新发现的缺陷：实验计划手抄 overrides 导致上限停在 200,000（demo 服务的是 `v1_class` 的 260,000），
  两例 MTB 卡在 token 预检 → 计划改由 `scripts/make_class_plan.py` 从 profile 生成并断言相等，
  `tests/test_v1_contract.py` 检查计划上限与 profile 一致；`library.get_item` 的 trace 归一化丢了
  `evidence_ids`／`evidence_coverage`，回放页显示不出记录里的覆盖 → 补回字段并加回归。
- 语义核对为 AI 辅助（`results/SEMANTIC_CHECK_CLASS6_AI.md`）：6 例的引用偏移全部逐字命中。
  核对读取的是每条引用的**完整 span**（`document_id[start:end]`，与 quote 完全相等），不是从中间截取的前段；
  `MSI stable`、`tumor purity 40.0` 在完整 span 内可见，原先只能判“部分支持”的 4 条里有 3 条升为支持，
  `pathology-01` 的 “lower lobe” 在两段完整 span 内都找不到，仍记为部分支持。AI 辅助标记保持不变，没有第二位人工评审。
  一条核验意见把 genomics 主张写成了
  “pathologic layer”，属措辞问题，记在剩余事项。
- 同一主张可能同时留下专业角色的反馈 verdict 与 Verifier 的最终 verdict（例如 q7 的 `genomics-03`：
  pathology 反馈 `insufficient`，Verifier 最终 `confirmed`）。这**不是** Verifier 跑了多轮——该例 Verifier
  只有 1 次模型调用（原始 trace 里 verifier 只有一条 `model_usage`）；报告与页面按“反馈/最终”区分这两行。
- 同例对照（同一 case 在 `real_fast2_*` 的 v1_fast 与本轮 `real_class6c_*` 的 v1_class 各跑过一次）：
  MTB 可比 3 例里 `mtb-P-0022916-q2` 从 B 变 A（答对），`q6`、`q7` 保持 A；CIViC 可比 2 例里
  `civic-60a33dc8…` 保持 NEI，`civic-3e09dc9e…` 从 REVISIONS 变 NEI（答错）。**方向上算持平：一升一降，
  在这种样本量下就是噪声区**（2026-10-18 的同 21 例复跑本身就有 ±2 翻转）。
  成本方向明确：同例 token MTB 平均 119,014 → 138,187（+16.1%），CIViC 36,834 → 45,675（+24.0%），
  因为 claims-v1 每段提示要多带主张名单与逐主张核验；两臂不在同一时间窗，所以只报 token 不报秒数。
- 网页真实链路复验（同一课堂输入 `mtb-P-0006191-q0`，2026-10-20 00:03 起）：`run-3c840f440e8e496a8843e7111f25b61a`
  `succeeded`，11 次模型调用、72,628 in + 21,741 out、552.6s、答 B（标签 A，与记录行一致）。
  11 次由原始 trace 逐条解释：7 个角色各 1 次，加上 4 次结构修复（literature、timeline、genomics、verifier
  各一次修正后才通过校验），7 + 4 = 11；`usage.calls=11`、`http_attempts=11`、零 HTTP 重试。
  页面对 literature/timeline/genomics/verifier 显示“本角色实际调用 2 次（含 1 次结构修复）”，
  与 trace 一致。此前报告把 11 次写成“只有 1 次结构修复”，与这条 trace 不符，已按原文更正。
  角色卡的证据覆盖写“候选 8 段 / 送入 8 段…全部候选已送入”，主张表出现“证据不足”结论。
- 仍开放：合入 `main` 由项目所有者决定；PR 仍需 HTTPS 凭据才能由我创建；31 例单次验收与必要的
  单 Agent 对照只在功能定稿后再跑，本轮没有自动扩量。

## 11. 三组整改验收（2026-10-21，接第 10 节）

本节只做用户指定的三组整改，不再扩实验。验收记录见 `results/ACCEPTANCE_CLASS6D.md`；
分支 `codex/v1-fast-real-api-20261019`（PR #6），基线 `650e627`。

- **核验进入决策**：`engine.py` 的 `verification_ledger()` 逐条保留
  `target_claim_id / claim_author / reviewer / verdict / reason / final / citations`，
  作为 `payload.verification_ledger` 与 `verification_ledger` trace 事件喂给 Decision；
  `claim_roster[].verifier_verdict` 带最终判定。Decision 必须点名采用与排除的 ID，
  同一 ID 不得两边都出现；主张 ID 只在整条响应通过校验后原子提交，失败不留幽灵 ID。
  `reviewer_role` 区分专业角色反馈与 Verifier 最终判定，页面与报告不再把两者混为“Verifier 跑了多次”。
- **用药事实保底**：`evidence.py` 按角色必需的模态（治疗/分子/病理）记录语法选择保底 span，
  用原始记录 offset 标记；保底集超预算时写入 `guaranteed_unsent` 并停在预算内，不静默超限。
  `material_basis` 明确区分 `not_recorded` / `selection_not_covered` / `supplied`。
  `tail_dropped` 的口径是“有候选没送入”，不限于尾部前缀。
- **用量一次归约**：页面用 `applyUsageEvents` 按 trace `sequence` 去重，实时、`finish`、刷新重查、
  断线重连与回放共用同一条路径；总量读 `RunResult.usage`，秒数读 `duration_seconds`，
  逐角色累计每次调用。合成 100/10/2s + 200/20/3s 显示 300/30/5s / 2 次。
- **新真实运行（只补两条，放新目录）**：
  - `results/v1/real_class6d_mtb_r2/`：q6，8 次调用、144,220 in + 16,760 out、207.0 s、答案 A/标签 A。
    Drug 候选 47 / 送入 27 段、11,969 / 12,000 字符，`treatment` 保底 3/3、`guaranteed_unsent=[]`；
    `file-ab603d3661c049070b15:f07` 的原始 span `[3113, 3678]` 在 offset 3623 处含 `AGENT: FLOXURIDINE`。
    Drug 输出两条暴露（FOLFOX、FLOX）与一条关系未知，不再写“无用药”。
    限制：模型与 Verifier 的措辞仍未逐字写出 FLOXURIDINE，Literature/Genomics 本轮各 0 条结论；
    保底验收的是输入，不是抽取。
  - `results/v1/real_class6d_civic/`：civic-3e09dc9e，10 次调用、34,885 in + 18,383 out、206.2 s、
    答案 REVISIONS/标签 REVISIONS；6 条主张全部 confirmed，Decision 采用 6、排除 0；
    ledger 6 行，5 行各带 1 条引用。
- **保留失败**：第一次 q6 在 `results/v1/real_class6d_mtb/…q6.failed.json`，
  `model output failed schema or source-integrity validation`（genomics/drug/verifier 的 scope
  越界，修复后 verifier 仍重复同类输出）。原样保留，未因此改代码；成功记录在 `_r2`。
- **回归**：三组确定性测试 18 passed；`test_demo_app.py` 8 passed / 3 skipped（服务器无 node）；
  页面 node harness 与 `node --check` 返回 0。全量 pytest 749 passed / 3 skipped（23.51 s）；
  `run_checks` 749 passed / 3 skipped、覆盖率 95%；`http_smoke` passed（25 预设、162 次模型请求）；
  `stress_offline` 4048 次执行 0 失败。以上在本次提交前的工作树重跑，输出见 `results/checks/` 等。
- **仍开放**：课堂冻结由用户决定；不合入 `main`；不自动启动方差、多 seed、完整消融或 31 例验收。
