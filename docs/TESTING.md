# 测试与鲁棒性

## 一键检查

```bash
python scripts/run_checks.py
python scripts/http_smoke.py
python scripts/stress_offline.py
```

`run_checks.py` 编译代码、执行 pytest、统计分支覆盖，保存 JSON/JUnit/完整输出到 `results/checks/`。测试通过 socket 边界阻止意外外网访问，并将模型环境固定为 mock。

`http_smoke.py` 启动独立 Uvicorn 与本地兼容模型 HTTP 服务，经实际 TCP 完成多配置任务，覆盖鉴权、上传、并发、任务查询、SSE、证据图、大小限制、远程处理同意和中断恢复。模型服务仍是确定性模拟器。

`stress_offline.py` 运行九个机制全部 512 种组合 × 4 病例，加上 25 预设 × 10 扰动 × 2 次重复 × 4 病例，共 4,048 次完整流程。校验终态、可见性、引用完整性和预算。

## 覆盖的实际故障边界

- 输入：未知字段、标签混入、重复 ID、路径穿越、非法选项、NaN、Unicode、无效 UTF-8、深嵌套 JSON、超限请求、批次部分错误。
- 模型：超时、连接失败、401/429/5xx、空响应、畸形 envelope、截断、无效 JSON、无效标签、伪造 PMID/引用、错误偏移、缺失/异常 usage、供应商参数不兼容。
- 流程：九个开关独立执行差异、七角色委派、一次回查、预算预检与用量超支、无模态调度、重复来源与未来信息。
- 后端：队列溢出、并发写入、原子批次、取消状态、中断标记、提交失败释放名额、删除关联记录和事件分页。
- 数据：官方格式白名单、患者/文章划分、文件映射歧义、校验和、gzip/JSONL、原生阶段事件、检索跨度对齐与重复主张并集。
- 实验：相同输入配对、可重复分组、bootstrap、检索指标、失败计入分母、配置/代码变化拒绝旧结果、显式重试、盲审一致性。

## 真实内容补充测试

上游 CIViC 手工复核片段来自公开库，经过本地提取 claim/evidence 后在模拟模型上测试。来源、样本数和配置数记入 `verification/`。真实内容用于检查数据和执行链，模拟器的医学质量保持独立评价。

## 交付验证与继续验证

当前测试数、覆盖率、HTTP/stress 与三版本 CI 实测状态见 `verification/FOLLOWUP.md` 和 `verification/followup_summary.json`。起始工程的历史 JSON 已在索引中单独标明。

已通过完整公开数据准备/抽样联调及 Docker 构建/容器接口验收。待真实模型环境核验：供应商协议、长上下文与速率限制、真实答案和引用质量。具体结果写入 TASK 中约定的报告。新增供应商或新版本数据继续通过相同边界测试。

本轮增加的回归覆盖 native REVISIONS 标签、未解决问题传递、消融参数贯穿检索、空字段与会议摘要来源标识、失败用量计费、24 个并发幂等请求、重启后请求重放、SSE 游标和跨域请求头。CI 中 `.github/workflows/container.yml` 通过实际 TCP 复核幂等和续传；`.github/workflows/public-data.yml` 下载并审计真实来源，仅保留统计与书目元数据，不导出论文或病例正文。
