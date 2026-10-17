# OncoFusion 第一版接手任务

先读 `docs/V1_PROJECT_REVIEW.md`。首版目标是肿瘤异构证据整合与核验；当前只开发算法与后端，网页沿用 `/v1`。

## 当前路线

使用 LangGraph 的有界协调器—专业模块流程、ToolUniverse 受限读工具、medspaCy 英语临床语境组件。主评测为 MTBBench 患者级纵向问答；CIViC-Fact 核验与文章内检索是组件评测，分别报告。自定义 synthesis 返回突变/病理语境/通路/药物/文献五项带来源的证据整合，缺证环节明确记录。

`experiments/research_v1.json` 是首版运行配置。旧25预设保持兼容对照；API 省略 config 时仍为 legacy。网页读取 `/v1/workflows.recommended_config` 并作为 config 提交。能力来源详见 `upstream_manifest.json`；GeneAgent、TxAgent、PaperQA2 的完整 Agent/权重尚未加载。

## 1. 安装并复跑

推荐 Python 3.11；核心轻量后端也测试3.12/3.13。CPU＋现有API即可。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,graph,clinical,biomedical]'
export ONCOFUSION_PROVIDER=mock
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
export LOGURU_LEVEL=WARNING
python scripts/run_checks.py
python scripts/check_upstream.py --out results/upstream/checks.json
python scripts/http_smoke.py
python scripts/stress_offline.py
python -m oncofusion demo --config experiments/research_v1.json --out results/v1_mock_demo.json
```

真实依赖环境的 medspaCy 和 LangGraph 测试应实际执行；仅核心安装会明确跳过可选依赖测试。记录当前commit、依赖和输出，不复用历史测试数字。Docker默认包含graph/clinical，来源快照准备可在独立环境安装biomedical。

## 2. 准备并审计正式数据

先阅读 `docs/DATA.md` 的来源许可。

```bash
python scripts/prepare_data.py mtbbench --raw data/raw/mtbbench --out data/mtbbench --download --accept-source-terms
python scripts/prepare_data.py civicfact --raw data/raw/civicfact --out data/civicfact --download --accept-source-terms
python scripts/audit_dataset_scope.py --dataset data/mtbbench --out results/mtb_scope.json --require-heterogeneous
python scripts/audit_dataset_scope.py --dataset data/civicfact --out results/civic_scope.json
```

固定CIViC版使用 SUPPORTS/REVISIONS/NEI；REVISIONS保留原定义。新 claim_fields 只含原 claim.content 白名单。labels、revised_claim、reviews、civic.description 保持评测侧隔离。患者全部阶段保持同组和同划分。新导入格式确有差异时保留字段样例，明确适配并增加回归，不自动猜测标签/路径。

审查 scope 中的异构资料、角色适用数以及原数据审计的缺失/排除项。CIViC单文献核验不能证明患者级异构整合；无时间线或无可重排候选的子集不用于该机制的有效性结论。

## 3. 接入本地已有真实API，先小样本

密钥从本地环境读取，不写入代码、日志、GitHub或网页请求。

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
python -m oncofusion demo --config experiments/research_v1.json --out results/v1_real_demo.json --allow-remote
```

使用供应商实际 token 参数；需要时改 max_completion_tokens。价格按实际每百万token设置 ONCOFUSION_INPUT_PRICE/OUTPUT_PRICE，缺价格时保留不完整标记。截断/空内容的已报告usage会计入失败成本。真实病例必须先审核并标为deidentified；data_class是操作者声明，系统不自动完成脱敏。

然后运行两组×四系统×一次的开发集pilot，各组保留全部题目：

```bash
python scripts/run_study.py --plan experiments/v1_mtb_pilot.json --dataset data/mtbbench --out results/v1_mtb_pilot --dry-run
python scripts/run_study.py --plan experiments/v1_civic_pilot.json --dataset data/civicfact --out results/v1_civic_pilot --dry-run
# 审核执行数量和预算后，去掉 --dry-run 并加 --allow-remote
```

验收：真实模式simulated=false；失败保留分母；每个角色读取相应资料；答案标签与引用原文匹配；随机复查至少20条引用的语义支持。记录成功率、失败原因、平均token、费用和延迟。测试通过不等于模型效果通过。预算不足时所有对照统一调整并使用新结果目录。

## 4. 逐角色实验与科学结果

pilot完成后使用 v1_mtb_ablations.json、v1_civic_ablations.json；每项三次重复。包含四个基线、七角色内部机制开关、七角色通用委派；MTB另含medspaCy关闭对照。先dry-run并明确 execution-cap，再进行付费运行。每个Agent的适用子集与实际输入范围一起报告，零适用项标记N/A。

独立检索按 docs/DATA 与 docs/EVALUATION 使用 retrieval_study.py，保留排除统计。完整旧41配置计划属于扩展研究，第一轮不必全部执行。所有真实对照同模型、同工具可访问范围、同预算上限，额外报告实际token。

开发集选择最终配置，冻结模型、提示、数据revision、代码SHA与协议，再复制计划切换test分区。保存 FROZEN_PROTOCOL.md；测试集性能按既定协议报告。公开基准的预训练污染风险与有限患者数在结果解释中说明。

用 build_report.py 和 review_citations.py 生成表格与双人引用审核，具体命令在 docs/EVALUATION。最终交付 REAL_API_ACCEPTANCE.md、DATA_ACCEPTANCE.md、FINAL_REPORT.md，至少包含患者问答、主张核验、独立检索、角色消融、成本、引用质量和成功/失败案例。

## 5. 网页接口与范围

```bash
export ONCOFUSION_API_TOKEN='GENERATE_A_LONG_RANDOM_SECRET'
export ONCOFUSION_CORS_ORIGINS='http://localhost:5173'
python -m oncofusion serve --host 127.0.0.1 --port 8000
```

测试示例、审核后的JSON/JSONL上传、recommended_config运行、状态/事件/SSE/graph、Idempotency-Key重放、缺依赖503和未审核远程请求422。检查synthesis的五项integration在API持久化后仍保留。

当前单进程、单团队共享Bearer；面向独立用户上线前增加用户身份与数据所有权隔离。保持API版本和既有字段兼容。原始PDF/WSI/VCF、中文临床NLP、影像模型、完整PaperQA2规划器、自动试验匹配与多轮自主规划另行立项，以真实需求和评测为依据。
