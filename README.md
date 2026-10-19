# OncoFusion

**肿瘤异构证据整合与核验的多智能体研究后端。**

第一版采用 **LangGraph固定专家工作流＋可选ToolUniverse只读工具＋OncoFusion证据与评测契约**。固定七角色、同一模型、文献先行、零自动回查。当前交付覆盖算法与后端；网页通过版本化HTTP API接入。完整范围及风险处置见 [第一版审查](docs/V1_REVIEW.md)。

## 快速运行

Python 3.11–3.13，CPU 即可。模拟模式无需模型密钥，所有内置病例都是合成数据。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,graph]'
export ONCOFUSION_PROVIDER=mock
python scripts/run_checks.py
python scripts/http_smoke.py
python scripts/stress_offline.py
python scripts/check_v1.py --out results/v1/contracts.json
python -m oncofusion demo --profile v1 --out results/demo.json
python -m oncofusion serve --host 127.0.0.1 --port 8000
```

Windows PowerShell 激活：`.venv\Scripts\Activate.ps1`；环境变量用 `$env:ONCOFUSION_PROVIDER="mock"`。

本地 API 文档：`http://127.0.0.1:8000/docs`。`.env.example` 是变量清单，程序读取已导出的环境变量，配置文件不会自动加载。

## 演示网页 /app

七 Agent 真实运行演示页：单文件、无构建、只用现有 `/v1` 接口（页面内联脚本，不加载外部资源）。

```bash
# 服务器侧（server21）：真实 API 环境 + 回放索引目录 + 本地令牌；REQUIRE_REAL 让缺环境时直接启动失败
cd ~/BioOncoFusion
set -a; . ~/.config/oncofusion/real-api.env; set +a
export ONCOFUSION_API_TOKEN="$(cat /path/to/demo-token)" ONCOFUSION_RESULTS_DIR=results/v1 \
       ONCOFUSION_DB=runtime/demo.sqlite3 ONCOFUSION_DEMO_REQUIRE_REAL=1
.venv/bin/python -m oncofusion serve --host 127.0.0.1 --port 8180

# 使用机器侧：SSH 转发后直接打开
ssh -N -o ServerAliveInterval=20 -L 18180:127.0.0.1:8180 server21-direct
# 浏览器访问 http://127.0.0.1:18180/app ，粘贴本机保存的演示令牌；或在本机再跑一层回环中继 `python scripts/demo_relay.py`（每个请求自动带上令牌、上游仍开启鉴权），
# 然后直接打开 http://127.0.0.1:18181/app ，无需粘贴任何东西
```

停止：转发端 Ctrl-C；服务器端按启动时记录的 PID 精确结束（共享主机上不要按名字批量 kill）。

链路抖动或后端回落由看护脚本处理：每 2 分钟经本机转发读一次 `/healthz`，不可达或看到 `simulated":true` 就按 pidfile（`/tmp/of_demo_api.pid`）精确重启服务器实例并重建 `ssh -f -N -L 18180:127.0.0.1:8180 server21-direct`；脚本形如 `/tmp/of_demo_watch2.sh`，令牌从本机文件读取，不入仓库。重启必须带 `set -a; . ~/.config/oncofusion/real-api.env; set +a`：漏掉这步进程照常应答，但 provider 回落到 mock，只有 `/healthz` 的 `simulated` 字段会暴露。

PR 目前无法自动创建：本机可用凭据只有 zmz2 的 **SSH 身份**（keychain 无 HTTPS 令牌、`gh` 未登录），
分支可推送但 GitHub 的 PR 只能经 HTTPS API/CLI 建；需 `gh auth login` 或 fine-grained 令牌后代开。

`/v1/configs/demo` 返回课堂配置 `v1_class`（七角色、片段引用、供应商输出上限 5000、统一一次结构修复，
外加 claims-v1 协作协议），并附上本机实际使用的 `workflow_backend` 与 `graph_installed`，
所以核心安装（native）与装了 LangGraph 的安装都能自证。设置 `ONCOFUSION_DEMO_REQUIRE_REAL=1` 后，
provider 落成 mock 时进程直接拒绝启动；页面徽章取 `/healthz` 与每条结果自带的 `simulated`，
模拟任务不会再被写成"真实运行"。

页面完成一条闭环：选择输入（内置示例 / MTBBench 与 CIViC-Fact 真实开发集样例 / 上传 JSON 或 JSONL 并选其中一条）→ `/v1/cases/inspect` 输入检查（输入面板给出任务、题号、原题逐字以及每份可见资料的类别、长度和正文）→ 以 `/v1/configs/demo` 返回的 `v1_class` 配置发起真实运行（不会落入历史默认预设）→ 七角色卡片按固定顺序逐个亮起，每张写清该角色的职责、后端递给它的证据片段数、前序已完成角色交来的结论与未解决项、本步产出的结论数与原文引用数、移交下去的未解决项，以及逐角色 token 和秒→ 「执行顺序」与「主张与核验关系」分开展示：前者是固定七步流水线和每步实际送入的证据覆盖
（候选多少段、送入多少段、原文多少字符、送入多少字符），后者按后端记录的主张 ID 画出作者角色、
该主张声明依据的前序主张、核验方逐条给出的 confirmed／corrected／rejected／insufficient，
以及决策采用与排除了哪些主张；早于 claims-v1 的历史结果没有保存这些依赖，那里直接写"未记录"→ 最终答案与解释，引用可展开对照模型给出的片段与原文偏移→ 失败时给出原因并保留已完成步骤。课堂现场用三个置顶按钮（`mtb-P-0027883-q7` 长时间线+真实分子、`civic-60a33dc8…` 单文献且来源不对题、
`mtb-P-0006191-q0` 全覆盖但答错），默认显示中文要点，模型原始的英文结论与引用片段放在折叠区；
要点写在 `oncofusion/web/index.html` 的 CLASS_NOTES，数字与 `results/CLASS_DEMO_ACCEPTANCE.md` 同源。
另有已完成真实结果的回放列表（失败记录留在统计分母里、默认不在回放列表出现，
`/v1/library?include_failed=true` 可单独查看）、中文「数据集结果」小表和逐角色平均耗时（含综合决策）；刷新页面后可凭 run_id 重新查询任务与结果。

模型密钥只存在服务器环境变量与本机演示令牌中，页面不显示密钥；`simulated` 标记区分真实与模拟后端。

## 第一版评测与输入

MTBBench纵向文本问答为病例整合主任务；CIViC-Fact为主张核验与段落检索组件任务。三者分别报告。数据没有逐患者最佳治疗标签，因此性能结论落在证据整合而非治疗推荐。

从 `experiments/v1_*_smoke.json` 开始：3系统×1次×3来源组。接通API与预算核对后运行 `v1_*_ablations.json`：11配置×3次。准备数据的role_coverage与POST `/v1/cases/inspect`会显示实际输入覆盖；单文献任务不用于证明文献重排收益。

## 已实现的算法与实验（含后续研究预设）

| 部分 | 实现 |
|---|---|
| 七角色 | Timeline、Genomics、Pathology & Context、Drug、Literature、Verifier、Decision |
| 基础工具 | 阶段/日期可见性、蛋白替换变异归一化、病理字段提取、癌种/实体匹配、药物方向词法特征、BM25 + 实体覆盖重排 |
| 协作 | 结构化证据板、来源去重、原文引用及字符偏移校验、最多一轮补证、按输入模态选择角色 |
| 模型 | 确定性 MockProvider；OpenAI-compatible Chat Completions 适配器，供应商参数显式配置 |
| 对照 | 单模型、工具型单 Agent、七调用通用 Agent、固定五 Agent、完整七 Agent |
| 消融 | 9 个机制开关、7 个角色委派、全通用角色、弱结构方案、检索深度与预算对照 |
| 完整实验 | 25 个运行预设；完整计划每个任务含 41 个 treatment × 3 次重复 |
| 数据 | CIViC-Fact 主张核验、MTBBench 逐阶段文本适配、独立的文章内段落检索任务 |
| 统计 | Accuracy、Macro-F1、患者/文章组汇总、配对聚类 bootstrap、检索 Recall/AP、效率与不完整成本标记 |
| 分析 | 断点续跑、配置/代码/数据指纹、CSV 与 Markdown 结果报告、引用双人盲审表 |

MockProvider 是流程模拟器。模拟正确率只用于软件回归；多 Agent 的真实收益由冻结协议下的真实模型实验决定。路径、标签和未来信息的隔离在所有消融中持续生效。

## 网页接入

```bash
# 获取v1配置与多来源合成示例
curl http://127.0.0.1:8000/v1/profiles
curl http://127.0.0.1:8000/v1/profiles/v1/example
# 获取历史示例与预设
curl http://127.0.0.1:8000/v1/examples
curl http://127.0.0.1:8000/v1/configs
# 提交后台任务，取得 run_id
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"example_id":"synthetic-support"}'
# 将上一步返回的 ID 填入路径
curl http://127.0.0.1:8000/v1/runs/RUN_ID
```

上面的简短提交示例使用历史默认配置；第一版网页将 `/v1/profiles` 返回的 `v1.config` 放入请求的 `config` 字段。新增检查接口不持久化输入，未安装图依赖在提交前返回503。

支持 JSON/JSONL 病例上传、不可变病例快照、异步运行、状态查询、带 Last-Event-ID 的事件回放/SSE、来源关系图和删除；Idempotency-Key 防止重复提交同一任务。单进程线程池 + SQLite WAL；默认本地单用户。公开监听需要设置 `ONCOFUSION_API_TOKEN`。原始 PDF、WSI、VCF 的解析和多用户隔离属于独立扩展，当前输入为统一 `CaseInput`。

## 真实模型接入

```bash
export ONCOFUSION_PROVIDER=openai_compatible
export ONCOFUSION_BASE_URL='https://YOUR_PROVIDER/v1'
export ONCOFUSION_MODEL='YOUR_MODEL_ID'
export ONCOFUSION_API_KEY='YOUR_LOCAL_KEY'
export ONCOFUSION_JSON_MODE=true
export ONCOFUSION_TOKEN_PARAMETER=max_tokens
python -m oncofusion demo --profile v1 --out results/real_demo.json --allow-remote
```

支持 `max_completion_tokens`、关闭供应商不支持的 `seed` / `temperature`、超时、429/5xx 有限重试、JSON 校验与有界结构修复。真实模式报错会显式失败，模型类型保持原样。价格从环境变量配置；未提供价格时成本字段保留不完整标识。

## 课堂展示验收

`results/CLASS_DEMO_ACCEPTANCE.md` 由 `scripts/class_demo_report.py` 从磁盘上的结果行生成，
记录当前提交、唯一启动方式、真实与回放入口、三个课堂案例、逐角色证据覆盖、关键修复证据、实际结果与剩余事项。
引用偏移的机械定位表在 `results/SEMANTIC_REVIEW_CLASS6.md`，逐条语义判断（AI 辅助，非人工评审）在
`results/SEMANTIC_CHECK_CLASS6_AI.md`。

本轮固定 6 例真实结果（claims-v1 / `v1_class`，同一时间窗，一轮，seed 0）：
MTBBench dev 4 问（3 位患者）4/4 完成、3/4 与标签一致、7 次调用无结构修复；
CIViC-Fact dev 2 条主张（2 篇文献）2/2 完成、1/2 与标签一致。样本量只够当试运行读数。
被旧实现截掉的输入用 `scripts/fragment_truncation_audit.py` 重放：183 例 MTB 输入里 126 例有文档截尾，
看不见的原文 310,902 / 1,980,042 字符（15.7%）。

实验计划必须由 `scripts/make_class_plan.py` 从 `profiles.v1_class_config()` 生成，不要手抄 overrides：
手抄的计划曾把上限停在 200,000，而 demo 服务的是 260,000 的 `v1_class`，两例 MTB 因此卡在 token 预检上。
`tests/test_v1_contract.py` 现在检查每个计划的 `max_total_tokens` 等于它 `reference` 那份 profile 的值
（已记录在案的历史计划列在 frozen 名单里，不去改写）。

## 数据与结果

`data/` 存四个预处理数据集（mtbbench、civicfact、civicfact-pmidids、civic_retrieval），
每个目录都有 `manifest.json`（来源与逐文件 sha256）、`audit.json`（覆盖统计、划分、许可计数）和
`_gold/labels.jsonl`（标签与组号，评测侧使用）。上游取回配方在 `data/raw/*/acquisition.json`，
记录了精确 URL、固定 revision 或 commit、字节数与 sha256，重新取回后指纹应逐字一致。

`results/` 存每个 study 的逐例结果与 `summary.json`、`scripts/real_metrics.py` 的指标表、
`scripts/review_citations.py` 的引用核对表，以及 `results/v1/demo_runs/` 里从服务存储导出的 8 次网页真实运行。

这两个目录连同 206 MB 的第三方原文已按项目所有者 2026-10-19 的指示整体提交进这个公开仓库；
其中文章正文分块相当一部分许可标注为 UNSPECIFIED，MTBBench 的 MSK 去标识病例没有声明许可，
具体计数与提醒见 `data/README.md`。密钥、演示令牌、`runtime/` 与日志不入库。

## 数据标签

固定 CIViC-Fact 2026.06.09 使用 SUPPORTS / REVISIONS / NEI；REVISIONS 保留“主张需要修订”的含义。自定义或旧版数据可以使用 refutes 标签体系。两类任务按显式 verification_scheme 分别评测，gold 修订文本保持评测侧隔离。

## 阅读入口

- **[TASK.md](TASK.md)**：Codex 接手的执行清单与验收标准。
- [架构](docs/ARCHITECTURE.md)、[API 契约](docs/API.md)、[数据准备](docs/DATA.md)。
- [评测与消融](docs/EVALUATION.md)、[测试与鲁棒性](docs/TESTING.md)、[交付验证记录](verification/README.md)。
- `experiments/`：已经生成的两套任务、开发/测试、smoke/complete 计划。

## 目录

```text
oncofusion/    算法、模型适配、数据/评测、后端
scripts/       测试、下载、实验执行、报告和盲审入口
experiments/   固定实验计划
tests/        单元、集成、故障与协议测试
docs/         架构、API、数据、实验与验收说明
verification/ 实测摘要（无原始患者/论文数据）
TASK.md       后续真实环境执行任务
```

外部数据保存在已忽略的 `data/`，模型结果与审查表保存在 `results/`；本地密钥、患者上传和运行数据库保持在仓库之外。CIViC-Fact 的论文片段继承各自来源许可，原始材料由使用者按许可获取。

## 上游复用与角色审查

逐角色设计见 [AGENT_REUSE_AUDIT](docs/AGENT_REUSE_AUDIT.md)。可选安装 `python -m pip install -e '.[graph,biomedical]'`：实际复用 LangGraph StateGraph 和 ToolUniverse SDK，原25预设继续保留。`/v1/agents` 与 `/v1/workflows` 提供网页所需的职责、来源和配置。真实模型比较使用 `experiments/upstream_*_dev.json`，工程结果与医学质量分开报告。

第一版来源工具共7项，新增Reactome蛋白→通路与通路详情。SDK快照是可选自定义研究扩展，标准基准保持封闭。原25预设继续兼容；新推荐配置通过profile显式选择。
