# OncoFusion：稳妥第一版接手任务

## 先锁定目标

课题是**肿瘤异构生物医学证据的多智能体整合与核验**。主任务采用MTBBench逐阶段文本病例问答；CIViC-Fact原生主张核验与段落检索作为组件评测。答案必须保留来源和证据适用条件。药物关系可以作为研究解释，但这两套数据的标准答案不验证最佳治疗方案。

阅读顺序：本文件 → docs/V1_REVIEW.md → docs/DATA.md → docs/EVALUATION.md → verification/README.md。实际复用层级见upstream_manifest.json与docs/AGENT_REUSE_AUDIT.md。

当前第一版配置在`oncofusion/profiles.py:v1_config`：**LangGraph固定七角色、同一模型API、结构化证据、文献先行、最新角色工作板、零自动补证**。角色顺序为 Literature → Timeline → Genomics → Pathology & Context → Drug → Verifier → Decision。固定流程优先；保留原生执行器用于等价测试，原25预设和大型计划作为后续实验。

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

重点读audit中的版本、标签、样本数、缺失字段、分区、排除项和新增role_coverage。检查各角色实际拥有的输入，尤其CIViC给定证据任务的单文献条件。检索排除项先人工确认，再用已有资料加--allow-exclusions重跑；结果保留真实分母。

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

交付results/REAL_API_ACCEPTANCE.md、DATA_ACCEPTANCE.md、FROZEN_PROTOCOL.md、FINAL_REPORT.md及脚本结果。仅提交脱敏汇总，原病例、论文全文、日志中的患者信息和密钥留本地。下一步的主要工作是实际API与科学验收，不再扩张Agent数量。
