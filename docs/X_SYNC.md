# X 收藏自动入库

2026-10-18 更新：已实现官方 OAuth 2.0 PKCE、后台续期和收藏轮询；本机尚无 X 开发者应用及用户授权，因此真实账号连接和计费请求尚未验收，也没有开启后台读取。协议测试使用明确标注的 HTTP 夹具，不是对 X 的真实请求，更没有伪造成功 AI 输出。

## 在网页完成一次配置

1. 打开 [可选的官方 API 同步](http://127.0.0.1:8787/official-x)。本地服务需运行。仅使用免费浏览器插件时无需本篇的应用、授权和费用步骤。
2. 到 [X 开发者控制台](https://developer.x.com/) 申请/创建开发者应用，启用 OAuth 2.0。个人本地可选择 Native App（public client）；Web App 等 confidential client 还需在服务端 `.env` 填 `X_CLIENT_SECRET`，重启生效。不要在聊天里发送凭证。
3. 在 X 应用登记网页显示的**完整回调地址**，默认 `http://127.0.0.1:8787/api/integrations/x/callback`。如 X 控制台不接受该本机回调，应根据实际应用设置使用允许的 HTTPS 回调，并同时配置 `X_REDIRECT_URI`、服务反向代理与 APP_TOKEN；本次未验收公网部署。不要仅把回调改成一个未运行的公网地址。
4. 将 OAuth 2.0 **Client ID** 填到网页并保存。API Key / app-only Bearer Token 不能代替用户收藏授权。
5. 点击“连接 X 账号”，在 X 官方网页确认。只请求 `tweet.read users.read bookmark.read offline.access`；不申请发帖或修改收藏的权限。授权回调读取当前账号资料可能产生 API 资源读取费用。
6. 在 [官方计费控制台](https://console.x.com/) 设置 API 额度和支出上限。阅读页面费用说明并勾选后，点击“开启自动同步”。连接账号本身不会自动启动收藏轮询。

不代开账号、不购买额度、不自动充值。实际权限和价格以用户控制台为准。当前 [官方定价页](https://docs.x.com/x-api/getting-started/pricing) 按资源收费；符合 owned reads 的开发者应用所有者本人收藏可使用对应费率，不能保证任意账号都符合。每页包括短帖和已有收藏，也可能计费；重复读取的计费去重是平台规则，不是本软件的零成本保证。

## 运行行为

- 默认每10分钟检查，最低5分钟；不是实时 webhook。关掉网页仍可继续，但电脑、本地服务及网络必须保持运行；休眠/关机期间不检查，恢复运行后继续。
- 默认只导入 Article、带 note_tweet/note_post 的长帖或正文至少300字符的帖子。短 Thread 根帖可能被这个启发式过滤；需要包含它时选择“全部收藏帖子”。本版不承诺完整 Thread、图片 OCR 或站外文章全文。
- 默认每页20条、每次最多3页。首次也会导入接口可返回的现有收藏；首次不等于把全部历史收藏读完。每轮先看第一页的新收藏，再续取上轮未完成的历史页。接口本身的可见范围、分页失效或账号限制仍可能影响覆盖。
- 用**收藏中出现的帖子 ID** 去重，不用帖子发布时间作为新增判断；因此今天收藏一年前的长文也会导入。正文和规范化 URL 继续使用知识库自身的去重检查。
- 有全文：直接保存官方返回正文、标题、作者、发布时间及来源，进入现有 AI/向量处理队列。收藏时间为本系统发现时间，官方接口未返回原始点击收藏时间。
- 只有 Article 元数据/短预览：保存链接并标记“待补充全文”，不把预览冒充全文给 AI。补充正文后沿用已有分析流程。没有配置语言模型也能保存和检索。
- 断网/服务错误：保留已入库文章和分页位置，逐步退避。429 参考限流头退避；401 要求重新授权；402/403 自动暂停并提示检查额度/权限。手动“检查新收藏”同样遵守间隔和退避，避免连续重复请求。
- 暂停不删除连接和知识；断开会尝试官方撤销 refresh token 并删除本地令牌。撤销失败也删除本地连接，并明确提示到 X「已连接的应用」检查。修改 Client ID 会暂停并清除旧本地连接，原应用若需撤销请先断开或到 X 操作。
- 已发现条目不因下次轮询缺失就删除本地知识；取消收藏不等于删除已归档原文。删除本地文章后也不会在同一账号下立即自动重新导入它。

## 凭证与备份

Windows 用当前用户的 DPAPI 加密 `data/x-credentials.bin` 和临时 OAuth verifier。macOS/Linux 用 cryptography Fernet，密钥文件 `data/x-secret.key` 为0600权限；同账户下同时拥有密钥和密文的人仍可访问，因此它不是独立密钥管理服务。不要共享整个 data 目录。

OAuth 用随机 state、S256 PKCE、同浏览器 HttpOnly/SameSite=Lax 临时绑定 Cookie；10分钟过期、一次使用。公开回调路由不要求 APP_TOKEN，但必须通过这些验证。access token 和旋转后的 refresh token 只在后端使用，状态、日志、便携 JSON 导出及源码包不包含它们。

同步配置、已发现 ID、分页和错误写入 SQLite 的独立表，重启继续；便携知识备份不含连接状态和令牌，迁移后需要重新配置与授权。只运行一个应用进程。

## 接口与验证

- `GET /api/integrations/x`：真实状态、连接账号、读取上限和最近结果；不返回授权令牌。
- `PUT /api/integrations/x/config`：client_id、interval_minutes、page_size、max_pages、long_only。
- `POST /api/integrations/x/authorize`：同站发起授权，返回官方地址并设置临时 Cookie。
- `GET /api/integrations/x/callback`：校验 state/Cookie/期限并完成 token 交换。
- `POST /api/integrations/x/switch`：`enabled`，开启时必须显式 `acknowledge_api_cost=true`。
- `POST /api/integrations/x/sync`：已开启时执行一次，遵守间隔/退避。
- `POST /api/integrations/x/disconnect`：停止、尝试撤销、移除本地凭证。

官方 [快速入门](https://docs.x.com/x-api/posts/bookmarks/quickstart/bookmarks-lookup) 仍使用 `tweet.fields/note_tweet`，而 [参考页](https://docs.x.com/x-api/users/get-bookmarks) 出现 `post.fields/note_post`。代码仅在400时尝试一次文档中的另一组字段；未经真实账号验证，不宣称两种部署都支持。

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_xsync.py -q
& .\.venv\Scripts\python.exe skills/x-second-brain/scripts/xsb.py sync-status
```

协议夹具覆盖授权绑定/过期/重复回调、PKCE、加密与导出排除、长文过滤、元数据降级、旧文新收藏、重启去重、分页续取、超时、401/402/403/429/503、刷新轮换、撤销、后台自动执行与暂停。真实 X 验收需要用户完成上述配置后，在 X 收藏一篇可核对的文章，等待一个轮询周期，核对网页中的原文/来源和分析完成状态。
