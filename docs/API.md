# API 契约 v1

启动：`python -m oncofusion serve --host 127.0.0.1 --port 8000`。交互文档 `/docs`，规范 `/openapi.json`；静态导出：`python -m oncofusion openapi --out docs/openapi.json`。

设置 `ONCOFUSION_API_TOKEN` 后，每个 `/v1` 请求带 `Authorization: Bearer <token>`。`/healthz` 提供公开健康检查。前端跨域来源用 `ONCOFUSION_CORS_ORIGINS=http://localhost:5173` 显式配置。

| 方法 | 路径 | 返回/用途 |
|---|---|---|
| GET | /healthz | 存活、版本、模拟标志 |
| GET | /v1/capabilities | 模型、上传格式、鉴权和容量 |
| GET | /v1/schemas/case | CaseInput JSON Schema |
| GET | /v1/configs | 25 个完整 RunConfig 预设 |
| GET | /v1/examples | 示例概要 |
| GET | /v1/examples/{id} | 完整合成 CaseInput |
| POST | /v1/cases | JSON CaseInput，201，返回持久化 case_id |
| POST | /v1/cases/upload | multipart 的 file，JSON 或 JSONL，201 |
| GET | /v1/cases | limit/offset 分页 |
| GET | /v1/cases/{id} | 完整病例快照 |
| DELETE | /v1/cases/{id} | 删除病例及关联记录，活动任务存在时 409 |
| POST | /v1/runs | 提交任务，202 |
| GET | /v1/runs | limit/offset 分页 |
| GET | /v1/runs/{id} | 状态、结果、错误 |
| POST | /v1/runs/{id}/cancel | 取消尚未开始的任务 |
| GET | /v1/runs/{id}/events | after/limit 增量事件 |
| GET | /v1/runs/{id}/stream | SSE 事件；结束发 done |
| GET | /v1/runs/{id}/graph | 来源与各 Agent 主张节点、引用边 |

## 提交格式

`case_id`、`example_id`、`case` 三者恰好一个。`config` 为完整或部分 RunConfig，后端补默认字段；网页从 `/configs` 取得预设后传回对象，不传预设名称字符串。

```json
{"example_id":"synthetic-support","config":{"max_calls":12,"top_k":6},"allow_remote_processing":false}
```

真实模型需要 `allow_remote_processing=true`，数据所有者先确认来源、脱敏与远程处理范围。模型 URL、密钥、名称由服务端配置，前端请求没有覆盖这些字段的能力。

## 上传

JSON 一个 CaseInput；JSONL 每行一个 CaseInput，最多 100 条。所有记录验证通过后整批事务入库；ID 重复或一条格式错误会整体失败。POST 请求上限 2 MB（含 multipart 包装）；单病例来源文本 UTF-8 总量上限 1 MB；每份文档最多 100,000 字符、最多 500 份。

```bash
curl -X POST http://127.0.0.1:8000/v1/cases/upload -F 'file=@case.json'
```

```json
{
  "schema_version":"1.0","id":"custom-001","patient_id":"research-p001",
  "task":"verification","question":"Example claim requiring evidence verification",
  "entities":{"gene":"GENE1","variant":"p.Val600Glu","disease":"Tumor-A","drug":"Compound-A"},
  "stage":0,"data_class":"synthetic",
  "documents":[{"id":"source-1","origin_id":"synthetic-paper-1","kind":"literature","text":"Synthetic evidence text.","available_stage":0,"license":"Synthetic fixture"}]
}
```

任务：verification 按 `verification_scheme` 返回标签：`refutes`（默认）为 SUPPORTS/REFUTES/NEI，`revisions` 为 SUPPORTS/REVISIONS/NEI；mcq 额外提供 options 对象并返回选项键；synthesis 返回研究摘要。结果包含 `decision`、各角色 `reports`、`trace`、`usage`、`simulated`；未解决项位于 decision 或相应角色报告的 `unresolved`。病例对象排除 answer、gold_label、任意文件路径和额外字段。

## 状态与错误

状态：queued → running → succeeded / failed / budget_exhausted；queued 可转 cancelled；服务重启时未结束任务转 interrupted。`succeeded` 下 result.status 为 completed。budget_exhausted 保留部分报告，最终 decision 可以为空，网页应单独展示原因。

400/422：请求或数据错误；401：鉴权；404：记录不存在；409：状态冲突；413：大小限制；415：文件格式；429：队列满。客户端仅对明确可重试的错误有限重试；已返回 run_id 后通过查询恢复，避免重复提交计费任务。

事件序号从 0 开始。`after=-1` 表示全部；断线重连传已处理的最大序号。原生 EventSource 无自定义 Authorization header，启用 Bearer 时用 fetch 流式读取或带鉴权的 SSE 客户端。事件内容包含研究资料，按病例权限处理。

## 重复提交保护

`POST /v1/runs` 支持可选 `Idempotency-Key` 请求头（1–128 位英文字母、数字、点、下划线、冒号或连字符）。相同 key、相同请求及供应商配置返回同一 run_id，且不再次执行模型。相同 key 携带不同请求返回 409。响应头 `Idempotency-Replayed: true/false` 标明是否重放，状态字段反映保存的当前状态。

key 随 SQLite 持久化；重启后仍有效。已取消、失败和 interrupted 的任务重放原终态，明确重试使用新 key。删除病例及关联运行时对应 key 也删除。队列满时已有 key 的重放仍可返回。当前约束为单进程、单用户或共享 Bearer 域；未来多用户部署需要将 key 与用户身份一起限定作用域。

```bash
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: web-demo-001' \
  -d '{"example_id":"synthetic-support"}'
```

## SSE 恢复

`GET /v1/runs/{id}/stream` 接受 `Last-Event-ID` 请求头。若同时传 `after`，从二者较大值之后回放，结束仍发 `event: done`。序号范围为 -1 至 2^63-1。响应设置 `X-Accel-Buffering: no`；反向代理也应允许长连接。

CORS 允许 Authorization、Content-Type、Idempotency-Key、Last-Event-ID，并暴露 Idempotency-Replayed。Bearer 场景使用支持自定义请求头的 fetch/SSE 客户端。


## v0.2 additions

`GET /v1/capabilities` advertises `recommended_preset=grounded_v2`; defaults retain legacy behavior. `GET /v1/configs` returns selectable configurations. `GET /v1/schemas/result` describes typed results, including `reports[].claim_reviews`. The evidence graph adds `review` nodes, stable claim IDs and `reviews` edges. RCS events are `context_completed`; summaries remain model-generated. External SDK tools are preparation-only and are never implicitly invoked on uploaded patient text.
