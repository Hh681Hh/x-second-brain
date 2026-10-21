# 日常流程：免费插件 + 后台 Codex

电脑 Chrome / Edge 的 X 网页亲手点书签 → 插件保存这一条已加载的正文 → 本机后台接收去重 → Codex CLI 自动阅读、分类、提取方法 → 用户直接在Codex对话检索和提问。无需日常工作台。下述页面采集边界适用于默认模式；0.3.2 新增的可选第三方公开全文补取默认关闭，详见 [FREE_FULLTEXT.md](FREE_FULLTEXT.md)。

插件安装与配对见 [README](../README.md)。插件源码在 `xsecondbrain/browser_extension`，Manifest V3，仅storage/alarms权限以及X与本地服务的站点权限，无Cookie权限、内部API、自动翻页或外部分析服务。未上架商店，用户在扩展管理页本地加载。

## 用户触发采集的边界

只监听浏览器中真实用户的原生bookmark点击，并观察当前帖子的removeBookmark显示状态稳定1.2秒，最多观察8秒；这是UI状态，不能当作X服务器提交成功的证明。不会在收藏页枚举、抓取历史或打开其他文章。取消书签不会删除本地知识，以免误删已经加工的原文。

使用DOM现有tweetText/Article富文本；保留原文字段、未知作者留空，不能凭空补全。显示更多、Article卡片、缺正文、超过12万字符的来源均标记partial。partial不进分析和问答证据；再次保存展开正文或从Skill提供全文可升级同一记录。普通单帖也不等于全Thread，采集范围记录在extraction_note并提供给模型。

页面结构未知时可能监听失败；需打开具体帖子或Article后点插件“保存当前内容”。这仍只读取已加载内容，不能解决平台未展示的正文。不同设备、关闭浏览器的书签操作无法被感知。

## 配对、队列与持久化

本地连接页生成64随机比特的配对码，10分钟过期、一次性使用、最多6次猜测；服务端存SHA256，插件取得独立随机提交令牌。令牌只保存在浏览器本地trusted contexts，正文页面拿不到，服务端也只存令牌哈希。

正常所有者API维持APP_TOKEN及同源限制，插件只调用pair/capture/ping，匹配扩展ID与可选Origin；CORS仅在这三个路由对有效扩展来源开放。提交令牌无法取回收藏正文、导出、模型密钥或改变配置。连接页可撤销所有配对，原文保留。同一路径生成的相同扩展ID在另一浏览器重新配对会替换先前凭证，需要时重新连接。

队列持久存在Chrome本地storage，上限100条、合计150万字符。更新串行化，收到服务端确认后才移除；离线每分钟重试。事件ID幂等、规范URL与正文哈希去重，重启不会重新阅读同一份正文。4xx错误保留并标记待处理，用户可重试或清空；AI处理错误由本地后台及插件状态显示，原文保留，可以通过Skill重试。

数据库新增browser_pairs/browser_pair_code/browser_clips/browser_events表；浏览器令牌不随知识导出。备份中的浏览器预览继续保持needs_content，不会恢复成完整文章。

## 后台与阅读器

双击项目根目录“启动X书签助手.cmd”，或运行 `python -m xsecondbrain.agent_cli start`。`connect` 打开一次性配对页，`status` 显示真实分类计数与插件状态，`stop` 只在自己的服务PID与项目标记匹配后停止本进程及阅读子进程。默认8787，数据在data目录。Windows 用户可通过 `scripts/autostart.ps1 -Action enable` 安装登录自启；详见 README。

后台调用已登录的官方Codex CLI，使用默认模型和账号可用额度，来源内容通过stdin交给临时结构化阅读会话。不是自动向本聊天投递消息，也不访问当前对话记忆。正式用法依据 [OpenAI文档](https://learn.chatgpt.com/docs/non-interactive-mode)。

实际命令使用 `--ignore-user-config --ephemeral --sandbox read-only --output-schema`，关闭Shell、插件、浏览器、应用及多Agent工具，过滤X和模型密钥环境变量，不复制CLI登录令牌。只有结构与逐字证据校验通过的输出写入库。超时、额度、登录及版本错误可见，原文不丢失。验证版本0.163.0-alpha.10.2；跨平台代码已实现，真实CLI推理在当前Windows验证。

首次下载本地BGE向量约90MB；无模型API Key时也可保存、全文搜索。Codex不可用时不会伪造分类和分析；用户在当前Codex中仍可用Skill取回真实正文进行人工授权下的整理。API兼容LLM接口与旧本地模型脚本保留为替代选项。

可选X官方OAuth仍在 `/official-x`，属于另一种有授权与费用要求的全账号同步途径，本次没有启用。用户目前只选择免费插件，不需要申请开发者应用。
