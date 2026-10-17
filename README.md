# OncoFusion

**肿瘤异构证据整合与核验的多智能体研究后端。**

从头实现七个专业角色、结构化证据共享、一次定向回查，以及可复现的基线和消融评测。当前交付覆盖算法与后端；网页通过版本化 HTTP API 接入。

## 第一版入口

当前首版使用 `experiments/research_v1.json`：LangGraph协调器＋专业模块＋一次受限补证，按任务分配资料；medspaCy执行英语临床语境提取，ToolUniverse准备经审核的数据库快照。患者级主数据为MTBBench，CIViC-Fact用于证据核验与检索组件评测。先读 [TASK.md](TASK.md) 和 [完整审查](docs/V1_PROJECT_REVIEW.md)。

```bash
# 推荐Python3.11，运行完整首版
python -m pip install -e '.[dev,graph,clinical]'
python -m oncofusion demo --config experiments/research_v1.json --out results/v1_demo.json
```

下面轻量入口保留旧配置的兼容行为；网页使用 `/v1/workflows` 返回的 recommended_config。

## 快速运行

Python 3.11–3.13，CPU 即可。模拟模式无需模型密钥，所有内置病例都是合成数据。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export ONCOFUSION_PROVIDER=mock
python scripts/run_checks.py
python scripts/http_smoke.py
python scripts/stress_offline.py
python -m oncofusion demo --out results/demo.json
python -m oncofusion serve --host 127.0.0.1 --port 8000
```

Windows PowerShell 激活：`.venv\Scripts\Activate.ps1`；环境变量用 `$env:ONCOFUSION_PROVIDER="mock"`。

本地 API 文档：`http://127.0.0.1:8000/docs`。`.env.example` 是变量清单，程序读取已导出的环境变量，配置文件不会自动加载。

## 已实现的算法与实验

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
# 获取示例与预设
curl http://127.0.0.1:8000/v1/examples
curl http://127.0.0.1:8000/v1/configs
# 提交后台任务，取得 run_id
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"example_id":"synthetic-support"}'
# 将上一步返回的 ID 填入路径
curl http://127.0.0.1:8000/v1/runs/RUN_ID
```

支持 JSON/JSONL 病例上传、不可变病例快照、异步运行、状态查询、带 Last-Event-ID 的事件回放/SSE、来源关系图和删除；Idempotency-Key 防止重复提交同一任务。单进程线程池 + SQLite WAL；默认本地单用户。公开监听需要设置 `ONCOFUSION_API_TOKEN`。原始 PDF、WSI、VCF 的解析和多用户隔离属于独立扩展，当前输入为统一 `CaseInput`。

## 真实模型接入

```bash
export ONCOFUSION_PROVIDER=openai_compatible
export ONCOFUSION_BASE_URL='https://YOUR_PROVIDER/v1'
export ONCOFUSION_MODEL='YOUR_MODEL_ID'
export ONCOFUSION_API_KEY='YOUR_LOCAL_KEY'
export ONCOFUSION_JSON_MODE=true
export ONCOFUSION_TOKEN_PARAMETER=max_tokens
python -m oncofusion demo --out results/real_demo.json --allow-remote
```

支持 `max_completion_tokens`、关闭供应商不支持的 `seed` / `temperature`、超时、429/5xx 有限重试、JSON 校验与有界结构修复。真实模式报错会显式失败，模型类型保持原样。价格从环境变量配置；未提供价格时成本字段保留不完整标识。

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

临床推理安装 `.[graph,clinical]`；ToolUniverse 来源准备在独立 `.venv-tools` 中安装 `.[graph,biomedical]`。两个模块通过固定 JSON 快照衔接，避免 NumPy 1/2 二进制冲突。完整命令见 TASK.md。
