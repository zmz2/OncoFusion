最新组件复用验证见 [UPSTREAM.md](UPSTREAM.md)；下列记录保留各历史交付版本。

# 验证记录索引

**当前交付状态见 [FOLLOWUP.md](FOLLOWUP.md) 与 [followup_summary.json](followup_summary.json)。**

2026-10-17 独立验证：510 项 pytest 全通过；Python 3.11/3.12/3.13 CI 全通过；综合覆盖率 97.2731%；4,048 次离线组合/扰动通过；25 预设、162 次实际 HTTP 请求通过；wheel 与非 root Docker 构建/接口验收通过。

完整公开数据准备通过：MTBBench 183 题/40 患者；CIViC-Fact 12,476 条/1,409 来源组；本项目独立检索适配 1,140 查询。抽样执行规模、排除策略、具体 CI 链接和缺陷修复见 FOLLOWUP。

所有模型结果为模拟器输出。真实数据导入、软件工程成功、真实医学答案质量分别评价。真实 API 与科学实验按根目录 TASK.md 接手。

## 历史文件

以下 JSON 保留起始工程 `5e26a3197c4e88cde7205eb62d3547b6756119f9` 的历史记录：

- local_checks.json：446 项测试与当时的依赖/覆盖率。
- stress.json、http_smoke.json：当时的组合与 HTTP 验证。
- study_smoke.json、upstream_smoke.json：当时的完整模拟计划与少量上游片段验证。
- source_manifest.json：起始源码的校验和清单，供复核历史快照。

这些历史文件不充当最新工作树的校验清单。当前 CI 每次归档实际 checkout 的源码、Git SHA、SHA256、JUnit、覆盖率与实验摘要；新修改以对应 CI 记录为准。附件保留 14 天，长期结果摘要在本目录。

原始病例、论文全文、密钥与私有评审资料保存在本地，不进入本目录。完整测试命令见 docs/TESTING.md。
