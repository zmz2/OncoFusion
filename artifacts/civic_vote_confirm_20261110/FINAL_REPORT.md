# CIViC-Fact vote-v1 补充评测

本报告展示一项同一方法设计下的CIViC来源隔离补充评测。它不声称逐字复现MTB历史运行的提示，也不是官方完整测试集。

- 代码提交：`a6351d3d8e5748d7894ab071aadeaf1edee06229`；模型：千问 3.6 35B-A3B（接口标识 `hc-qwen38-27b-fp8`）。
- 固定名单：117条、117个来源组；标签 SUPPORTS 42、REVISIONS 15、NEI 60。
- 已登记此前进入调试/开发的来源组3个；整批结果同时给出117条全名单、114条未用组和3条已用组。各配置沿用完全相同的名单。
- 单Agent只调用一次通用角色；完整OncoFusion和去除仲裁共享同一批专业选票，只有仲裁步骤不同。

## 主比较：单Agent与完整OncoFusion

见`main_table.csv`。主解释口径为此前未用来源组114条；全117条和已用3条也保留。技术失败保留在Accuracy分母，不映射为NEI。

| 队列 | 系统 | 正确/样本 | Accuracy | Macro-F1 | 有效答案完成率 |
|---|---|---:|---:|---:|---:|
| previously_unused_114 | single_agent_b0_common_single | 97/114 | 0.8509 | 0.8168 | 113/114 (0.9912) |
| previously_unused_114 | oncofusion_v3_arbitrated | 99/114 | 0.8684 | 0.8386 | 114/114 (1.0000) |
| all_117_fixed | single_agent_b0_common_single | 100/117 | 0.8547 | 0.8235 | 116/117 (0.9915) |
| all_117_fixed | oncofusion_v3_arbitrated | 102/117 | 0.8718 | 0.8441 | 117/117 (1.0000) |
| previously_used_3 | single_agent_b0_common_single | 3/3 | 1.0000 | 0.6667 | 3/3 (1.0000) |
| previously_used_3 | oncofusion_v3_arbitrated | 3/3 | 1.0000 | 0.6667 | 3/3 (1.0000) |

## 仲裁消融

完整方法与去除仲裁使用相同专业选票；去除仲裁只输出初始等权标签。见`ablation_table.csv`。

- 实际仲裁触发：8；完成：8；失败：0；未触发：109。
- 错误改对：1；正确改错：1；原本正确且保持：2；原本错误且保持：4。

- 114条此前未用来源上，仲裁前后Accuracy均为99/114；Macro-F1从0.8346变为0.8386。

## 配对结果

来源组配对bootstrap 2000次，统计seed=0。点估计和95%区间见`metrics.json`。

- 114条未用来源组上，OncoFusion相对B0准确率差：+0.0175，95% CI [-0.02631578947368421, 0.06140350877192982]。
- 双方均有有效答案：113；改错为对：3；改对为错：2；B0失败而OncoFusion答对：1。

## 运行成本与审计

逐例调用、token、耗时、引用来源和服务器原始轨迹路径见`paired_cases.csv`。`metrics.json`列出汇总用量；模型价格未提供，未估算USD。

病例级原始JSON、失败轨迹、API请求哈希和私有证据仍保存在server21结果目录。
