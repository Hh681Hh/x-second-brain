# HTTP API

默认 `http://127.0.0.1:8787/api`。`/api/docs` 查看完整OpenAPI。配置APP_TOKEN后普通API请求需要Bearer令牌；插件专用的pair/capture/ping使用独立配对与仅提交内容的令牌，不能读取库内正文。不使用X浏览器Cookie。

| 方法 / 路径 | 用途 |
| --- | --- |
| GET /status | 模型配置状态、收藏与索引数，不返回秘密 |
| GET /summary | 真实分类计数、分析状态和X连接统计 |
| GET /browser | 插件配对状态、实际网页入库数、待补全文数，不返回令牌 |
| POST /articles | JSON url/title/author/content/source_kind，保存并排队 |
| POST /articles/batch | `{"articles":[{"url":"…"}]}`，最多50条 |
| GET /articles?limit=100&offset=0 | 分页，可用 category/tag/unread/sort |
| GET /articles/{id} | 原文、分析、偏移、所有真实 chunk_id、错误 |
| PATCH /articles/{id} | 补全文、编辑元数据、tags/category/is_read |
| POST /articles/{id}/process | 重新分析并建索引，可能计费 |
| GET /search?q=…&limit=8 | 混合检索，包含来源、逐字原文、匹配方式 |
| POST /chat | `{"question":"…","session_id":null,"limit":8}` |
| GET /articles/{id}/related | 相关候选，不代表观点矛盾 |
| GET /sessions，/sessions/{id} | 真实持久对话 |
| GET /export；POST /import | version 1 JSON 原文与元数据备份 |
| GET /integrations/x | 官方收藏同步状态、账号、读取上限、最近结果 |
| POST /integrations/x/sync | 已开启时检查一次，遵守间隔/退避，可能产生X费用 |
| POST /integrations/x/switch | enabled=false 暂停；开启需用户先完成官方授权及计费确认 |

默认首页用于免费浏览器插件安装配对。可选官方OAuth在 `/official-x`，不通过CLI传令牌；官方回调用PKCE/state/临时同浏览器Cookie校验，不要求APP_TOKEN。该Cookie只绑定本应用OAuth流程，不是X浏览器Cookie。

AI 回答的 `claims` / `disagreements` 包含 `evidence[]`：chunk_id、article_id、quote、start_offset、end_offset（Python Unicode 字符偏移，非 UTF-16）。`ai_suggestions` 是补充判断，不能说成作者观点。

`mode=ai` 表示模型确实生成并通过结构与逐字引用校验；这不是事实正确性的证明。`retrieval_only` 表示只返回片段；`no_evidence` 表示未找到匹配。`insufficient=true` 不应被包装成找到了历史解决方案。

文章 queued/processing 只代表任务未完成；ready 表示有通过校验的分析，saved 表示只有原文，needs_content 需要用户补充，error 表示模型处理出错。`embedding_error` 独立存在，全文保存和分析成功不等于语义索引成功。
