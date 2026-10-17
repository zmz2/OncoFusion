# 上游复用版验证 — 2026-10-17

实际运行代码提交：fd8b9d9aac8330a8e60667a8b4be88ba00fba9a9。验证由 checksum 固定补丁运行后提交普通源码完成。

- CPython 3.11、真实 LangGraph 1.2.16 与 ToolUniverse 1.5.7：650 项 pytest 通过，0失败/错误/跳过。
- 覆盖率：语句97.9677%，分支94.2359%，综合97.0113%。
- 独立 native/真实LangGraph 比较：104组，全部决策、角色报告与usage等价。
- ToolUniverse：五项真实SDK注册与参数schema验证通过；关闭hooks/workspace。
- 公开网络：真实SDK执行一次 MyGene BRAF 查询成功，返回结果的SHA256已记录。
- 实际loopback HTTP：25预设、162次模拟模型HTTP请求，11类检查通过。
- 本地Python3.13只安装核心依赖：546通过、104个可选LangGraph测试跳过。上述650通过来自安装了真实图运行库的独立环境。

商业大模型API调用为0。模型输出均为MockProvider。这些数字说明工程/协议/工具兼容，医学准确率与对照收益仍需按TASK在开发集测量。其余四个数据库工具完成注册与schema检查，尚未宣称全部在线服务验收。

原始CI：https://github.com/zmz2/OncoFusion/actions/runs/39019090175
机器可读摘要：upstream_checks.json。CI artifact保存JUnit、覆盖率、SDK验收和HTTP结果。旧FOLLOWUP属于上一个版本；当新CI完成，以新提交对应结果为准。
