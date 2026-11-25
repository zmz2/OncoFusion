# OncoFusion vote-v1 课堂讲解交接

## 建议讲解顺序

1. **方法页：从分工到选择性仲裁。** 展示冻结方法的实际链路：同一问题和同一允许证据包 → 适用专业角色独立回答 → 程序等权计票 → 低共识时核对证据并仲裁 → 输出答案和引用。不要画成角色分片读不同资料，也不要把模型自报置信度画成加权票。
2. **主结果页：MTB 独立确认。** 使用 `figures/mtb_holdout.svg` 与 `tables/mtb_holdout_main_table.csv`。说明 85 题、19 位患者；V3 64.71%，B0 56.47%，差值 +8.24pp；患者组 bootstrap 95% CI +1.12 到 +16.09pp；完成率 98.82% 对 91.76%。同时指出测试来源组排除了 13 个曾用于调试或方法选择的组。
3. **投票过程案例。** 使用 `cases_redacted.md` 的案例一。Literature、Genomics、Drug 三票为 REVISIONS，Pathology 为 SUPPORTS；3/4 的最高占比正好是 0.75，所以按严格“小于 0.75”规则没有触发仲裁。B0 为 NEI，参考标签 REVISIONS。该例适合说明专业检查角度互补，不代表总体提升。
4. **仲裁案例。** 使用 `cases_redacted.md` 的案例二。初始 NEI 触发仲裁，仲裁完成后仍为 NEI，参考为 REVISIONS。用它说明“仲裁完成”不等于“纠错成功”，失败案例仍在分母。
5. **机制诊断页。** 依次使用 `figures/role_contribution.svg`、`figures/member_count.svg`、`figures/length_groups.svg`、`figures/evidence_position.svg`、`figures/robustness.svg`、`figures/thresholds.svg`。强调每项样本量和限制：开发集小样本、阈值未带来准确率变化、E04 每条件仅 20 题。
6. **引用与结论边界页。** 使用 `figures/citation_quality.svg` 和最终报告。区分位置偏移准确与语义支持；AI 辅助审阅未经临床专家裁定。主结论仅是这批预定来源隔离 MTB 病例上的测量结果。

## 页面必保留的信息

- 展示名为“千问 3.6 35B-A3B”；原始接口模型标识和请求身份见 `FROZEN_PROTOCOL.json`。
- V3 等权投票；仲裁条件为 top share `<0.75` 或票差 `<0.25`；失败时保留初始有效票。
- B0、P-K、V3 的分母均包含失败；失败不自动记作 NEI。
- 同一案例在 B0 与多角色方法之间共享同一允许证据。角色之间提示重点不同，不能称作分片阅读。
- CIViC 是补充任务；117 条来源隔离既有 cohort 不冒称官方完整测试集。E05a CIViC30 是开发样本。
- E04 属于 20 题/条件的小样本证据干预；方向不一致，不作删除证据的因果推断。
- 引用位置偏移检查和引用语义核对是不同指标。

## 文件定位

主表、消融、逐类、长度、阈值、引用和稳健性 CSV 均位于 `tables/`；可直接插入演示的 SVG 位于 `figures/`。`cases_redacted.md` 仅保留脱敏转述，不含患者编号或完整原文。完整模型提示与病例轨迹保留/清理规则见 `PROTOCOL.md` 与 `cleanup_manifest.json`。
