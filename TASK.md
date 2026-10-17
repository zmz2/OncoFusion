# 本轮增补：成熟组件复用 v0.2

先阅读 `docs/AGENT_DESIGN.md`、`THIRD_PARTY_NOTICES.md` 和 `verification/UPSTREAM.md`。精确来源在 `third_party/upstream-lock.json`。

本轮新增实际 LangGraph 执行、证据先行流程、逐主张核验、PaperQA 两个原版 RCS 提示模板、ToolUniverse 真实 SDK 适配和 GeneAgent 富集函数改编。完整 TxAgent/PaperQA/Biomni 模型平台未移植，各层来源见设计表。

## 推荐接手顺序

```bash
python -m pip install -e '.[dev]'
python scripts/run_checks.py
python scripts/http_smoke.py
python -m oncofusion demo --preset grounded_v2 --out results/v2_mock.json
python -m oncofusion demo --preset grounded_v2_contexts --out results/v2_contexts_mock.json
```

接通下面既有真实 API 配置后，对这两个 preset 分别加 `--allow-remote`。先检查结构化逐主张判定、未核验事项和原文引用；PaperQA RCS 的模型调用也要计入费用。真实不足按原流程记录，模拟器的逐条判定均标为 insufficient。

使用新计划 `experiments/civic_dev_upstream.json` 与 `experiments/mtb_dev_upstream.json`，仍先 dry-run 和预算估算。比较旧版/单 Agent/新版、角色委派、九机制与新增流程/RCS/主张核验消融。旧版 `full` 和历史 41-treatment 计划继续保留。API 通过 `/v1/configs` 获取 `grounded_v2` 的完整 config 后提交，默认 config 继续保持历史行为。

## 可选的真实知识工具准备（CPU 即可）

```bash
python -m pip install -e '.[dev,biomedical]'
python -m pytest integration_tests -q
python scripts/check_biomedical.py --live --out results/upstream_live.json
python scripts/freeze_biomedical.py --queries docs/public_queries.example.json \
  --out data/public_snapshots/v1 --allow-remote
```

最后一个命令使用文件中已审核的公共基因/疾病/药物检索标识。可以同时传 `--case <synthesis_case.json> --case-out <new_enriched_case.json>`，把真实知识响应加入明确的 synthesis 任务。CIViC-Fact 给定证据与 MTBBench MCQ 的封闭基准继续使用既定语料；知识库快照与其另建评测条件。使用 GeneAgent 派生富集函数见设计文档；富集结果与患者通路活动分别解释。

网页后续消费现有 `/v1` 上传、示例、任务、事件、SSE 与证据图。逐条审查记录在 `reports[].claim_reviews`，RCS 信息在 trace 的 `context_completed`。本轮依然单进程任务池，不宣称运行中 checkpoint 续跑。

---

# OncoFusion：真实环境接手任务

## 目标与当前范围

算法、后端、七角色、数据适配、基线、消融、统计、报告与大量模拟测试已经搭建。你的主要工作是**执行既有流程、核实真实供应商与正式数据、修复实际发现的问题、生成真实实验结果**。网页开发后置，保持 `/v1` 契约。

阅读顺序：README → verification/README → docs/DATA → docs/EVALUATION → 本任务执行清单。架构说明在 docs/ARCHITECTURE，网页接口在 docs/API。

科学任务：MTBBench 逐阶段文本选择题；CIViC-Fact 给定证据三分类核验；CIViC-Fact 独立同文章段落检索。三个任务分别报告。角色包括 Timeline、Genomics、Pathology & Context、Drug、Literature、Verifier、Decision。

## 本轮接手前必读

此次接手以已验证的现有代码为起点。新增的独立回归集中在 `test_hardening.py`、`test_usage_accounting.py` 和 `test_frontend_contract.py`。验证结果和真实数据联调记录见 `verification/FOLLOWUP.md`。

固定的 CIViC-Fact 2026.06.09 使用 SUPPORTS/REVISIONS/NEI。保留原标签体系：REVISIONS 是需要修订的部分支持，禁止将其改写成 REFUTES。原主张、证据输入模型；gold revised_claim、人工解释和标签留给评测器。默认准备命令已使用 revisions scheme；旧版或用户数据可以显式选择 refutes scheme，各体系分别评测。

真实 MTBBench 的空白源文件已适配并审计。CIViC 空标题、空许可证保留未知状态；检查 audit 的 missing_* 计数。独立检索中同文章同主张存在冲突标签的整组查询排除，先核对审计再明确允许 exclusions，报告保留实际分母。

新增网页契约：POST /v1/runs 使用 Idempotency-Key 避免网络重试重复计费；相同 key 与内容返回原任务，修改内容返回 409。失败或中断后的明确重跑换新 key。SSE 支持 Last-Event-ID 和 after，按较大序号续传。数据上传、示例调用、进度与证据图接口保持 /v1。

费用报告区分 reported usage 和估算 usage；失败前已观测的 token/费用继续计入。真实模式有估算、HTTP 重试、缺失 usage 时 cost_complete=false；estimated_cost_usd 与 known_cost_usd 分开。恢复实验时保留代码、模型、超时和重试策略指纹。

## 0. 工作原则

使用现成代码与计划开始，不重做研究方向。真实失败由实际输入、HTTP 响应或日志定位，最小修改并增加回归测试。原始公开数据保存在 data/，结果在 results/，密钥保存在本地环境。所有模拟结果保留 simulated 标记。

当上游真实格式与已核查格式不同，保存版本、字段样例和错误，再编写明确适配；保持标签和未来资料隔离。模型质量不足则如实报告，使用开发集改善提示；测试集用于冻结后的比较。

## 1. 安装与完整工程回归

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export ONCOFUSION_PROVIDER=mock
python scripts/run_checks.py
python scripts/http_smoke.py
python scripts/stress_offline.py
python -m oncofusion examples --out data/examples
python -m oncofusion demo --out results/demo.json
```

Windows 使用 `.venv\Scripts\Activate.ps1` 和 `$env:NAME="value"`。具体已测试版本在 constraints-tested.txt；项目范围依赖在 pyproject.toml。无需 GPU。

验收：pytest 全通过；HTTP smoke 所有 checks 通过；stress 4,048 次全部通过。单元测试数量以本次 pytest 输出和 FOLLOWUP 记录为准。保存当前运行版本与测试日志。新变更完成后重跑，而不是仅复用交付报告。

## 2. 获取正式数据并审计

先阅读 docs/DATA 的来源许可，再运行：

```bash
python scripts/prepare_data.py civicfact --raw data/raw/civicfact --out data/civicfact \
  --download --accept-source-terms
python scripts/prepare_data.py mtbbench --raw data/raw/mtbbench --out data/mtbbench \
  --download --accept-source-terms
python scripts/retrieval_study.py prepare --download --accept-source-terms \
  --raw data/raw/civic_retrieval --out data/civic_retrieval
```

CIViC-Fact 已固定 commit/build 与二进制文件 blob 校验，MTBBench 先解析并保存 HF revision 后下载。脚本自动做字段白名单、路径映射、分组检查和审计。无需重新搜索默认数据源。

重点检查各 audit：实际样本数、组数、标签、分区、长度、模态与许可证。MTBBench 的输入来源仅包含事件已宣布文件，答案在 `_gold`；同患者全部阶段保持同划分。CIViC 保留官方文章分组。当前版本标签为 SUPPORTS/REVISIONS/NEI，使用该词表与对应定义评测。

检索准备出现 excluded 时先读 `retrieval_audit.json`。确认原因后用已下载文件重跑并加 `--allow-exclusions`，保留排除统计；正例按人工跨度覆盖率至少 75% 定义。文档中有完整命令。

**只有实际失败时才需要自由开发：**HF 仓库访问/文件布局变化、供应商协议变化、真实文件中的未覆盖格式。保留原资料，补明确适配和测试，不放宽为任意字段自动猜测。

## 3. 在正式内容上先跑模拟 smoke

```bash
python scripts/run_study.py --plan experiments/civic_dev_smoke.json \
  --dataset data/civicfact --out results/mock_civic_smoke
python scripts/run_study.py --plan experiments/mtb_dev_smoke.json \
  --dataset data/mtbbench --out results/mock_mtb_smoke
python scripts/retrieval_study.py evaluate --dataset data/civic_retrieval --split dev \
  --out results/retrieval/dev.json
```

验收的是导入、协议、轨迹、预算与引用边界，模拟标签成绩单独归档。正式真实模型结果使用新的 results 目录。

## 4. 接通真实 API

模型供应商与 key 由用户本地已有配置获得；服务端读取以下环境变量：

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
# 按供应商实际 USD / 1M token 设置价格后再报告费用
# export ONCOFUSION_INPUT_PRICE=...
# export ONCOFUSION_OUTPUT_PRICE=...
python -m oncofusion demo --out results/real_demo.json --allow-remote
```

这是 Chat Completions 兼容接口。`BASE_URL` 是 `/v1` 前缀，程序追加 `/chat/completions`。供应商使用 `max_completion_tokens` 时显式改 `TOKEN_PARAMETER`；不支持 JSON mode 则显式设 false。拒绝采样参数时保持 SEND_* false。只有支持时启用，保存配置用于全部对照。

先看 real_demo：`simulated=false`、状态 completed、task 标签有效、引用原文匹配、usage 可解释；再分别跑四个示例。若模型因输出结构失败，用单独 `--preset schema_repair` 检验有界修复。正式所有对照采用一致的修复设置，写入冻结计划，而不是只给 Full 增加重试优势。

模型返回不合法 JSON、截断、不可引用结论时，定位真实返回格式/长度并修复；始终保持真实模式显式失败策略。修改 max_output_tokens / 全局预算会改变实验，应统一并另存输出。

## 5. 真实开发集 smoke 与成本估算

```bash
python scripts/run_study.py --plan experiments/civic_dev_smoke.json \
  --dataset data/civicfact --out results/real_civic_smoke --dry-run
python scripts/run_study.py --plan experiments/civic_dev_smoke.json \
  --dataset data/civicfact --out results/real_civic_smoke --allow-remote
python scripts/run_study.py --plan experiments/mtb_dev_smoke.json \
  --dataset data/mtbbench --out results/real_mtb_smoke --allow-remote
```

smoke 选 5 个患者/文章组，各组全部样本，并跑 5 个基线系统。若执行数超过默认 1000，先看 dry-run 与费用，明确提升 `--execution-cap`。记录平均 tokens、费用、失败率、p95 时间、上下文上限和回查次数；按 workload 外推完整实验预算。

验收：所有样本获得可解释终态；真实失败被记录，错误率/引用质量据实报告。工程成功与回答正确率分别呈现。长病例达到保守预检预算时统一调整预算或设计有依据的文档选择，保留原协议版本。

## 6. 开发集完整实验

```bash
python scripts/run_study.py --plan experiments/civic_dev_complete.json \
  --dataset data/civicfact --out results/real_civic_dev --dry-run
python scripts/run_study.py --plan experiments/mtb_dev_complete.json \
  --dataset data/mtbbench --out results/real_mtb_dev --dry-run
```

完整计划有 41 treatments × 3 次重复；主基线、9 机制、7 角色、信息消融、扰动、检索深度、两种预算均已准备。预算确认后给命令增加 `--allow-remote --execution-cap <明确上限>` 执行。长实验可以中断后 `--resume`；需要重试已失败样本时加 `--retry-failed`。

代码/输入/供应商/计划改变后使用新输出目录，保持旧轨迹。无需手动编辑结果来恢复。重点分析每个 Agent 的适用任务、机制变化及成本，零收益模块如实归纳。

## 7. 冻结后运行测试集

将最终模型、提示、参数、数据 revision、split、计划与代码 SHA 记入 `results/FROZEN_PROTOCOL.md`。提示已在 engine.DUTIES 与系统提示中，主要比较与脚本均准备好。

采用 experiments/civic_test_complete.json 与 mtb_test_complete.json，仍先 dry-run，再按预算显式运行。独立段落检索切换 `--split test`。测试期间继续保存运行错误，但调参回到开发集并形成新协议。

## 8. 生成报告与双人引用审查

```bash
python scripts/build_report.py --study results/real_civic_dev/study.json --out results/reports/civic_dev
python scripts/build_report.py --study results/real_mtb_dev/study.json --out results/reports/mtb_dev
python scripts/review_citations.py export --study results/real_civic_dev \
  --inputs data/civicfact/inputs.jsonl --out results/citation_review --limit 200
```

评审各自填写 reviewer_A/B.csv 的 supports=yes/no/unclear，私有 mapping 不交给评审。用 review_citations.py score 输出一致率、kappa 与待仲裁项。语义支持需要实际审查，原文偏移通过仅证明引用完整性。

最终报告至少包含：主比较、各 Agent 委派与机制消融、信息扰动、预算/成本、独立检索、真实引用质量、六个典型案例（成功/失败/纠错各有代表）。每项标明样本数、真实/模拟、失败分母、置信区间与来源版本。

## 9. 后端真实任务验收

```bash
export ONCOFUSION_API_TOKEN='GENERATE_A_LONG_RANDOM_SECRET'
export ONCOFUSION_CORS_ORIGINS='http://localhost:5173'
python -m oncofusion serve --host 127.0.0.1 --port 8000
```

经 API 测试：带鉴权获取例子；真实处理同意后运行示例；上传一份已脱敏自定义 CaseInput；查询状态/事件/SSE/graph；验证无效文件和超限处理；重启后检查 interrupted；重复查询既有 run_id。代码只在 queued 状态取消，避免虚报运行中请求已停止。默认单 ASGI 进程，生产多用户队列另行规划。

有 Docker 时额外执行 `docker build -t oncofusion .`，运行时传 API_TOKEN 和明确模型环境。当前环境的 Docker 构建状态见验证记录。图像/PDF/VCF 解析后续单独设计，当前网页上传统一 JSON/JSONL。

## 10. 交付结果文件

新增 `results/REAL_API_ACCEPTANCE.md`（供应商/模型/参数、成功失败、费用）、`results/DATA_ACCEPTANCE.md`（版本/数量/排除原因）、`results/FROZEN_PROTOCOL.md`、`results/FINAL_REPORT.md`，附脚本生成的表格与轨迹路径。报告可以提交脱敏摘要，原始数据、密钥、患者记录与全文继续保留本地。

可以继续自由开发的工作以真实失败与明确质量瓶颈为依据，例如更稳的供应商结构化输出、经标注验证的检索改进、数据对齐扩展。现有完整工程和实验套件是起点，保留可复现基线。
