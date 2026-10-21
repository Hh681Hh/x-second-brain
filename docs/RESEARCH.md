# 竞品调研与原创边界

调研日期：2026-10-17。阅读各仓库当前 README、可取得的许可证和架构文件。GitHub 元数据 API 在此环境返回限流，改读仓库原始文件；没有宣称取得固定 commit 的完整审计。

| 项目 | 值得参考的能力 | 对本需求的取舍 | 许可核实 |
| --- | --- | --- | --- |
| [Karakeep](https://github.com/karakeep-app/karakeep) | 通用收藏、归档、自动标签、全文及语义检索；Next.js、Drizzle/SQLite、Meilisearch、抓取 worker | 成熟但组件较多；本项目只服务个人“遇到问题找回方法”，采用单进程和单数据库 | 根 LICENSE 为 AGPL-3.0；未复制或依赖其业务代码 |
| [Bookmark Is Learned](https://github.com/iamzifei/bookmark-is-learned) | 收藏当下摘要、展开长文、原文与摘要存 Markdown、可关闭 AI | 值得参考即时消化思路；本项目增加持久知识结构和跨文章证据检索 | README 声明 MIT，调研时根 LICENSE 未取得；不复用实现或素材 |
| [X Bookmark Digest Skill](https://github.com/loong-solvable/x-bookmark-digest-skill) | 分类 digest、索引、阅读优先队列 | 当前 README 明确 macOS，读取浏览器认证 Cookie 并使用内部 GraphQL；不采用该采集路径 | 未取得独立许可证，不将其作为可复用依赖 |
| [X Bookmarks](https://github.com/sharbelxyz/x-bookmarks) | OpenClaw Skill 将收藏转成行动建议；提供官方 OAuth 路径 | 借鉴“方法可执行”；本项目以可查证的知识引用为先，正文不能指挥 Agent 执行动作 | README 声明 MIT，根 LICENSE 未取得；不复用代码 |
| [Summarize](https://github.com/steipete/summarize) | 提取与总结分离、多来源及模型路由、无密钥提取、JSON 自动化接口 | 适配层与独立提取很合适；MVP 不引入视频、OCR、转录等额外负担 | 根 LICENSE 为 MIT；不直接依赖或复制其实现 |

独立实现：数据表、分块与证据校验、任务队列、混合检索、问答约束、页面布局、文案和 SVG 标记均重新编写。无竞品 Logo、截图、CSS 或业务代码进入运行包。引用文章的权利仍属于原作者，用户应保存自己有权使用的内容。

## X 官方 API 核实

- [Bookmarks introduction](https://docs.x.com/x-api/posts/bookmarks/introduction)：GET `/2/users/:id/bookmarks` 读取当前授权用户的私有收藏，需要开发者账号、应用与用户访问令牌。
- [官方 OAuth SDK 类型](https://github.com/xdevplatform/twitter-api-typescript-sdk/blob/main/src/OAuth2User.ts) 和 [OAuth 2.0 文档](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)：v0.2 同步采用用户 OAuth 2.0 PKCE，请求 `tweet.read users.read bookmark.read offline.access`，支持后台续期。应用级 Bearer Token 不是私有收藏访问授权。
- [当前价格](https://docs.x.com/x-api/getting-started/pricing)：按用量、预付 credits。页面列出 Post reads $0.005/资源；满足开发者应用所有者本人条件的 owned reads 包含自己的 bookmarks，$0.001/资源。扩展作者等资源也可能计费。价格可能变化，开发者控制台才是实际额度和可用权限依据。旧的固定月费套餐不能当作现行事实。
- [速率限制](https://docs.x.com/x-api/fundamentals/rate-limits)：当前表列 GET bookmarks 每用户 180 次/15 分钟；应读取响应限流头、分页和退避，不能据此承诺账号一定可访问。
- [Post lookup](https://docs.x.com/x-api/posts/lookup/introduction)：MVP 通过官方 v2 取已授权访问的帖子；长帖读取 `note_tweet.text`，Article 尝试 `article.plain_text`。字段或全文缺失时不能把短预览冒充完整文章。

首版曾保留禁用状态；v0.2 已实现 OAuth、定时轮询和状态入口。没有开发者应用及账号授权，尚未在线验收私有收藏同步，也未开启读取。同步方案、文档字段差异与凭证保护见 [X_SYNC.md](X_SYNC.md)。MVP 不读取 Cookie、不调用内部 GraphQL、不绕过登录。公开普通网页可直接提取；X 无官方令牌时保存链接并提示粘贴全文。Thread 可以手工按顺序粘贴完整串；官方 recent search 作为显式开启的有界补全，标记覆盖范围，无法承诺全历史串。

## 采用的基础技术

[FastAPI](https://github.com/fastapi/fastapi) + Python 3.11+，SQLite WAL + FTS5，原生 HTML/CSS/JavaScript。一个服务即可安装运行，不要求 Node、Docker 或外部向量数据库。FastEmbed 的 [受支持模型表](https://qdrant.github.io/fastembed/examples/Supported_Models/) 列出中文 BGE small（MIT）；CPU 本地向量无需模型 API 费。替代方案为 OpenAI 兼容 embedding HTTP 接口。全文与向量融合，不把关键词扩展或随机向量称为语义检索。

Codex Skill 使用官方 [SKILL.md + scripts 规范](https://learn.chatgpt.com/docs/build-skills)，以标准库 Python CLI 访问同一 HTTP API。具体依赖及完整安装许可清单在 THIRD_PARTY_NOTICES.md 和 docs/dependency-licenses.json。

## 2026-10-20：免费桌面插件的产品收敛

用户明确只考虑长期免费，且在电脑Chrome/Edge网页点书签。对[Readwise官方X导入说明](https://docs.readwise.io/readwise/docs/importing-highlights/twitter)及[价格](https://readwise.io/pricing)核实后，没有选择其订阅同步服务。免费本地插件不需要开发者应用，但只能响应这台浏览器中用户亲手触发的剪藏，不能承诺全账号历史/移动端收藏同步。

根据[Chrome内容脚本文档](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)，隔离世界脚本可读取当前页DOM并向扩展后台发消息；[跨域请求文档](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)说明后台使用host_permissions访问本地接收器。v0.3独立编写Manifest V3、DOM提取、真实点击监听、离线队列和本地配对，无运行时外部JS或付费SDK。

[X自动化规则](https://help.x.com/en/rules-and-policies/x-automation)对非API自动化有限制，因此没有用脚本登录、翻阅或滚动收藏页、调用内部GraphQL或取Cookie。当前实现是用户在已打开页面中亲手收藏/保存时读取已加载文字；此设计范围不代表X官方对插件的认可或政策合规认证，页面兼容和允许用途仍需后续核对。不把用户触发的页面保存描述成已获授权的全账号同步。

后台阅读使用本机现有Codex CLI登录及额度，依据[官方非交互执行文档](https://learn.chatgpt.com/docs/non-interactive-mode)调用结构化临时会话；并不意味着模型无限免费。已验证真实CLI分析与出处问答，但没有在用户的Chrome/Edge安装插件后对真实X账号验收。此差异在README和测试记录中明确列出。
