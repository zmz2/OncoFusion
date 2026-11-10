# OncoFusion 课堂网页 v2 交接

新版真实入口：http://127.0.0.1:18181/classroom （用户 Mac 已建立到 server21 的私密隧道）。
算法执行冻结在 7a307f0d024a86c7309314733472e9dbc68dd45c；展示/API引用修复在
62d2e4b。六次新执行均保留前一个执行身份，后续截图与注释没有重跑模型。
该目录保存公开材料；完整病例、逐字引文和完整轨迹保存在 server21。

## 课堂上讲清的方法

同一个病例问题、同一个阶段可见证据包，交给本例适用的专业角色独立作答。
程序按有效票等权计数；低共识时 Verifier 回到原文核验；最后程序组装标签与引用。
Decision 没有单独模型调用。三个固定病例均选入文献、时间线、基因、病理与语境；
Drug 没有选入。专业提示有不同职责，输入不是按专业分片阅读。

V3 的触发条件为最高票占比严格小于 0.75，或票差占比严格小于 0.25。
平票按原有 SHA256 固定规则和 seed=0 形成初始标签。
仲裁失败时保留初始标签并记录失败；有效票不足时整例失败。
模型自报置信度不参与等权多数票加权。

网页状态、参与人数、选票、仲裁前后标签和最终结果来自存储记录与真实事件。
实时事件按 sequence 去重；刷新和断线查询仍读取同一 run_id。
参考标签仅在执行终态后由展示/评测侧读取 labels.json；不进入 CaseInput 和模型请求。

## 与历史网页的差异

| 内容 | 旧 /app | 新 /classroom |
|---|---|---|
| 默认表达 | 七角色流水线与多种研究配置 | 输入—独立专业判断—投票—选择性仲裁—输出 |
| 角色数量 | 固定串行角色卡为主 | 读取本例 planned_roles，失败/弃权也按原记录显示 |
| 输入 | 英文来源与技术信息较多 | 中文释义优先，原文与转述分别标注，关键来源默认展开 |
| 选票 | 研究明细表为主 | 大字选项、等权票数、共识阈值和平票状态 |
| 仲裁 | 不易单独讲解 | 实际触发才显示；不预设仲裁会改对 |
| 成本与身份 | 经常占据默认页面 | 折叠审计区，逐条事件去重后统计 |
| 历史/新运行 | 多个版本混在结果库 | 三份历史回放与六次新运行明确标识 |
| 公开展示 | 旧源码含具体病例讲解笔记 | 公开源码移除旧私密讲解笔记，公开截图省略病史原文 |

原服务器 /app 服务保持运行。本分支从干净 main 导入实际 e4711bada390b32a28795e5128f2ebb00e4a2a9e
的源码快照，未携带包含数据的历史提交链。vote_runner.py、voting.py、evidence.py、
agent_design.py 保持该快照字节；没有为课堂更改算法或阈值。

## 三个案例的讲解顺序

1. 案例01：先看历史一致投票，说明四位角色回答同一个问题。切换本轮后，
   有一位角色结构修复后仍失败，剩下三张有效票触发仲裁；失败被保留。
   本例还用于讲解预测型问题和原协议字段被误读的局限。
2. 案例02：历史三比一展示不同角色对近期稳定与既往风险的侧重差异。
   切换本轮后是二比二，Verifier 核验后维持初始标签。单Agent本轮未产生有效答案。
3. 案例03：历史二比二，固定平票规则先选 B，Verifier 核对原文后改为 A，
   再由评测侧比较参考标签。这是实际的历史语义纠错。
   随后切换本轮同例：仍二比二，但仲裁维持 B，与参考标签不一致。
   用这组回放说明机制与结果波动，而不是声称仲裁总能纠错。

固定名单与共同证据指纹位于 experiments/classroom_web_v2_20261110.json。
三例分别对应用户指定的 q3、q4 与已核实发生语义纠错的历史 q1；
公开页面只显示案例别名，不展开可识别病史。

## 截图放置建议

所有 originals/ PNG 均由真实浏览器以 1920×1080 捕获；crops/ 是同一网页的浏览器元素截图，
不是生成图片或重写结果。完整原图始终保留。

| PPT页 | 图片 | 讲解重点 |
|---|---|---|
| 1 方法总览 | screenshots/originals/01_overview_history.png | 并列专业角色、等权计数、条件仲裁、组装答案 |
| 2 输入与范围 | screenshots/originals/02_input_public_redacted.png | 相同问题/选项、来源分类、截止点；公开省略原文的标记 |
| 3 专业判断 | screenshots/originals/03_specialist_votes_history.png 或 crops/03_specialist_votes_crop.png | 三比一不是所有专家都认同；自报置信度不加权 |
| 4 选择性仲裁 | screenshots/originals/04_arbitration_history.png 或 crops/04_arbitration_crop.png | 二比二、B→A、实际核对来源、最后才与参考标签比较 |
| 5 答案与引用 | screenshots/originals/05_answer_citations_history.png 或 crops/05_answer_crop.png | 标签与两条以内依据；引用位置可追溯，全文在服务器 |
| 6 新旧结果差异 | screenshots/originals/06_new_run_disagrees_with_reference.png | 同例新运行 B，与参考标签不一致；历史 A 不被覆盖 |
| 7 可靠性与失败 | screenshots/originals/07_new_run_failure_retained.png | B0有限修复后失败，失败计入固定六次清单 |
| 备份页 | screenshots/originals/08_expert_reference_dialog.png | 每位专家的引用入口指向自己的实际来源 |

公开截图中的原文省略块是真实网页的脱敏状态。它们不是原文截图，
也不能在PPT中标为“公开临床原文”。私密现场演示可以勾选“查看服务器原始资料”；
该视图含原始问题、英文模型输出和完整可见来源，不应公开截图。

## 六次新执行（全部保留）

共同模型展示名：千问 3.6 35B-A3B；API标识：hc-qwen38-27b-fp8。
真实标记均为 simulated=false，HTTP重试为0。结构修复最多2次。
B0 max_calls=3、temperature=0；OncoFusion max_calls=15、temperature=0.4。
两系统每例总token上限260000、单调用输出上限5000，发送温度和seed。
所有内部请求共用一个进程级20槽调度器，固定最大节点调用预算54。

| 案例 | 系统 | 状态 | 最终/参考 | 仲裁初始→最终 | calls | 输入token | 输出token | 秒 |
|---|---|---|---|---|---:|---:|---:|---:|
| 01 | B0 | completed | A / B | 不适用 | 1 | 10,151 | 1,738 | 117.4 |
| 01 | OncoFusion | completed，3/4有效票 | B / B | B→B | 9 | 95,882 | 16,357 | 580.7 |
| 02 | B0 | failed，无有效答案 | — / A | 不适用 | 3 | 38,382 | 5,737 | 395.6 |
| 02 | OncoFusion | completed | A / A | A→A | 5 | 55,382 | 9,209 | 271.1 |
| 03 | B0 | completed | B / A | 不适用 | 1 | 11,074 | 1,840 | 137.8 |
| 03 | OncoFusion | completed | B / A | B→B | 7 | 78,426 | 13,168 | 560.3 |

合计26次模型调用、289297输入token、48049输出token，共337346 token。
B0完成2/3，包含失败的正确数0/3；OncoFusion完成3/3，正确数2/3，
有效专业票为11/12。本轮三个OncoFusion均触发仲裁且均未改变初始标签。
这只是三个固定案例的网页链路检查，不是新主实验，也不能用于替换MTB43表格。
USD价格未保存，货币成本未知。

案例02 B0失败原因为结构/来源完整性校验在两次修复后仍未通过。
案例01 OncoFusion的文献票也在有限修复后失败；其余有效票满足原有法定人数，
整例按原协议继续。没有选择成功样本重跑。
完整run_id、UTC时间戳、指纹、状态和服务器轨迹路径均在 runs_summary.csv。

## 文件与身份

- cases_public.json：三份历史加六次新记录的脱敏投影，包含选票、仲裁、最终答案与引用位置。
- presentation_annotations.json：人工整理的中文转述；每条专家转述绑定原 brief_reason 的SHA256。
- runs_summary.csv：全部九份身份与结果，source字段区分 historical/new。
- manifest.json 与 SHA256SUMS：配置、模型原标识、执行commit、来源与结果指纹、文件来源。
- browser_checks.json：真实选择、上传检查、发起、刷新去重、引用和回放的观察记录。
- validation.json：工程检查范围与结果；模拟测试不充当真实案例结果。

历史运行的Git提交是 f6f3aa9311c2614c01cc597a1419e25b4a9e48d5，
实现指纹9e193cdcf2c18aae7a0c33fb701d8d1371d77114cc72ee834285475300dfa8cc。
当时工作树有未提交修改、没有逐条提示全文；公开交接包的main代码不能替代那次实现。
新执行使用已提交7a307f0；所有源输入、配置和原始trace保存在服务器，后续UI修复没有改写它们。

## 启动与恢复

server21工作区：/home/zhangmingzhou/BioOncoFusion-classroom-web-v2。
私密运行目录：/home/zhangmingzhou/BioOncoFusion/runtime/classroom_web_v2_20261110。
原始历史目录保持不动。

服务当前由nohup保持运行，PID写在私密运行目录的service.pid。
服务器没有可用的用户systemd总线，因此未安装后台定时器。
需要正常重启时先确认原PID与命令身份，再运行：

~~~bash
cd /home/zhangmingzhou/BioOncoFusion-classroom-web-v2
bash scripts/start_classroom_v2.sh
~~~

脚本只从服务器 ~/.config/oncofusion/real-api.env 读凭据，绑定127.0.0.1:8181。
不要在既有六次记录后重新运行prepare；它用于运行前建立协议。
已经完成的固定槽位再次点击仅查询同一个任务，不会自动重试失败。
上传JSON/JSONL使用既有协议完成导入和检查，不向固定六次批次追加执行。

Mac入口：

~~~bash
ssh -N -L 18181:127.0.0.1:8181 server21-direct
open http://127.0.0.1:18181/classroom
~~~

## 公开范围和仍需说明的局限

上游MIT许可证适用于软件；prepared病例的license字段为空，不能据此确认患者原文可再发布。
公开材料省略年龄、患者识别信息、完整病史和逐字引文，保留中文脱敏概述及来源位置。
上游说明：[软件许可证](https://github.com/bunnelab/mtbbench/blob/main/LICENSE)、
[数据来源说明](https://github.com/bunnelab/mtbbench#datasets)。

原MCQ协议继承固定verification_scheme=refutes字段，它不是gold。
部分历史输出曾把它误读为结论依据；这轮按要求保持算法，并在回放中忠实保留这一局限。
有些专业角色的理由主要来自临床资料，不能仅凭角色名声称完成了分子机制推理。
预测任务、单次模型波动与有限修复失败仍存在；本轮保留了反例。

## 工程检查

提交前全量回归：812 passed / 3 skipped（服务器无Node的旧网页测试）。
引用投影修复后的定向回归：32 passed / 3 skipped。
本机Node语法检查通过；真实浏览器最终页无控制台错误。
浏览器验证了选择案例、私密原文、JSON上传检查、发起真实任务、独立选票、
仲裁与专家引用入口、刷新恢复、历史回放。
重复查看已完成任务前后run_id相同、calls=1、事件数=8，未重复计数。
