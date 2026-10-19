# 数据目录说明

这个目录是预处理后的评测数据，全部由上游公开构建物本地复现得到。每个数据集的原始下载记录、
准备后的输入与金标注、以及审计与指纹都在各自的目录里。

## 各数据集

| 目录 | 来源 | 例数 | 组数 | 划分 | 输入指纹 | 标签指纹 |
| --- | --- | --- | --- | --- | --- | --- |
| `mtbbench` | `data/raw/mtbbench/questions_msk_bench.json` | 183 | 40 个患者 | test 140 / dev 43 | `e093bd91da2a…` | `3dcce219f360…` |
| `civicfact` | `data/raw/civicfact/civicfact-2026.06.09.jsonl.gz` | 12476 | 1409 篇文章 | train 9693 / dev 1044 / test 1026 / 未分配 713 | `093e61dc6cda…` | `f3221fa1e39e…` |
| `civicfact-pmidids` | 同上，仅把来源 id 改为真实 `pmid-<n>` | 12476 | 1409 | 同上 | `165c8d3415eb…` | `f3221fa1e39e…` |
| `civic_retrieval` | CIViC-Fact 文章内跨段检索版本 | 1140 | 602 | train 931 / dev 125 / test 84 | `0641e38baf4c…` | `0939a586e510…` |

`_gold/labels.jsonl` 只放标签、组号和 `relevant_document_ids`，评测侧使用，不进入 Agent 可见输入。
`manifest.json` 记录来源与逐文件 sha256，`audit.json` 记录角色可见输入的覆盖统计。
两个指纹任何变化都会改变 study 身份，因此不能悄悄重新生成。

## 上游与取回方式

`data/raw/*/acquisition.json` 记录了精确的上游地址、固定 revision 或 commit、每个文件的字节数与 sha256：

- MTBBench：`EeshaanJain/MTBBench`，revision `5054ec8ebeb3998ec50fb63860dd4195f6c2a565`（经 `hf-mirror.com` 取回，服务器直连 huggingface.co 不通）。
- CIViC-Fact：`creisle/civicfact` commit `1a767d889b015a836f0f4331afcac5cef165ec7f` 的 `civicfact-2026.06.09` 构建物。

重新准备数据：先取回 `data/raw`，再跑 `scripts/prepare_sources.py` 与 `scripts/prepare_data.py`，
最后核对 `manifest.json` 的指纹是否与上面一致。

## 许可提醒（重要）

这里是第三方内容的再分发，许可状况并不干净，使用前请自行核对：

- `civicfact` 与 `civic_retrieval` 内嵌的文章正文分块，来源标注为
  `UNSPECIFIED 8021 / none 635 / CC BY 2643 / CC BY-NC 481 / CC BY-NC-SA 149 / CC BY-NC-ND 531 / CC0 16`
  （按文档计数：`civic_retrieval` 为 `CC BY 15304 / UNSPECIFIED 17048 / none 3665 / CC BY-NC-ND 2019 / CC BY-NC 1734 / CC BY-NC-SA 1045 / CC0 210`）。
  也就是说相当一部分片段的许可证未声明，还有 NC／ND 条款的片段。
- `mtbbench` 是 MSK 的去标识病例记录，上游数据集没有声明许可（`licenses: {}`）。
- 病例文本已去标识（`data_class: deidentified`），但仍属真实临床记录片段。

本目录整体入库是项目所有者 2026-10-19 的明确指示；第三方原文的再分发许可由所有者负责判断。
若要对外发布模型结论或引用原文，建议回到上游确认各自条款。
