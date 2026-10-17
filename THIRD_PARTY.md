## 首版审查更新

实际新增依赖 medspaCy 1.3.1（MIT），使用官方 ConText/TargetMatcher/PyRuSH 组件；源文件 `oncofusion/clinical_context.py`。精确版本由 `upstream_manifest.json` 和 CI 环境记录。其余 Agent 的方法借鉴与工具复用按下文逐项区分。

# Upstream attribution

OncoFusion uses LangGraph 1.2.16 (MIT) as an optional execution dependency and ToolUniverse 1.5.7 (Apache-2.0) as an optional read-only source SDK. Their licenses remain in the installed distributions. Source/database licenses are separate from software licenses.

GeneAgent (NCBI/NLM), TxAgent and ToolUniverse (Zitnik Lab), PaperQA2 (FutureHouse), MDAgents (MIT Media Lab) and medspaCy informed the independently written role contracts. Those projects' model weights, runners, full skills and source files are not vendored here. No license to reuse their data or model weights is implied.

See `upstream_manifest.json` for exact adoption levels and `docs/AGENT_REUSE_AUDIT.md` for the task-fit review, source links and excluded mechanisms. Attribution does not imply that OncoFusion has reproduced the original systems or their benchmark performance.
