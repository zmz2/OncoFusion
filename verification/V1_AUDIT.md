# 第一版风险审查验证

基线：c33a7898864ec896df4d95f75ce88776b35b065b。源码风险与处置见../docs/V1_REVIEW.md；下一步按根目录TASK.md执行。

本地实际回归：Python3.13.5，579 passed、0 failed、104 optional graph skipped。新增33项针对风险和首版接口的测试。原始基线为546 passed、104 skipped。最初七个独立回归用例先重现失败，再修改实现；新功能另有契约测试。

本地4,048次组合与扰动、25预设/162次实际loopback HTTP模拟模型请求、wheel构建均通过。新v1契约验证了5个合成输入×3系统=15次流程、75次模拟模型调用，以及鉴权/输入检查。摘要在v1_local.json。

本地没有安装实际LangGraph/ToolUniverse，本地测试明确跳过104个图测试；真实上游依赖由GitHub Actions dedicated upstream job安装执行，实际结果以该job为准。新增Reactome两工具由该job使用真实SDK校验参数定义，实际联网数据返回需要在接手环境另行查询；不要将schema验证解释为所有数据库服务可用。

软件回归、真实依赖、真实数据导入与真实模型医学质量分开记录。商业LLM调用为0。本轮不提供患者治疗效果或Agent质量提升的宣称。
