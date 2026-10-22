# X Second Brain · X 书签知识助手

**收藏即学习，提问即调用，答案可溯源。**

在电脑 Chrome / Edge 的 X 网页点击书签，将文章交给本地后台阅读、提取方法、分类和索引。以后直接在 Codex 中提问，找回以前收藏的解决方案及原文出处。日常只需要浏览器插件，网页工作台是可选入口。

原创 MIT 项目，由 **Manifest V3 插件 + Python 后台 + SQLite 知识库 + Codex Skill** 组成。插件与本地存储免费；Codex、其他模型及可选 X 官方 API 的额度或费用由对应服务决定。

> **当前版本：0.3.6。** 默认只保存页面已经加载的文字。可选 FxEmbed 免费公开接口可以在后台补取未展开的公开长文，默认关闭。2026-10-21 已实际验证“未展开卡片原生书签点击 → 31,021 字符全文 → 真实 Codex 分析分类 → Skill 检索及带引用问答”。测试范围与限制见 [验证记录](docs/FREE_FULLTEXT.md)。

## 能做什么

| 能力 | 当前状态 |
| --- | --- |
| 原生书签点击、插件手动保存、粘贴文本、批量链接 | 已实现；插件仅感知安装它的桌面浏览器 |
| 自动获取公开 X 长文 | 可选 FxEmbed 后台补全；非官方接口，需自行启用 |
| 速读、精读、深度分析 | 配置可用 Codex CLI 或兼容模型后自动生成 |
| 问题、方法、条件、步骤、风险、原文依据 | 结构化保存，引用检查原文字符位置 |
| 分类、标签、阅读价值理由、相关文章 | 已实现；自动分类需要真实模型成功完成分析 |
| 中文全文 + 语义检索、跨文章问答 | BM25 与本地 BGE 向量融合；引用可回到来源 |
| Windows 登录后后台自启与故障恢复 | 已实现；无需管理员权限 |
| 数据导入、导出、模型替换 | 已实现；原文持久保存在本机 SQLite |
| 手机 App 书签、全账号历史自动同步 | 免费插件不支持；官方 OAuth 路径需权限及额度，未完成真实账号验收 |

没有模型配置时仍可保存、管理和全文搜索；系统会明确显示 AI 不可用。只有预览或采集失败时保留链接，不把片段冒充完整文章参与问答。

## 快速开始

需要 **Python 3.11+、Chrome / Edge**。自动阅读默认使用已经安装并登录、有可用额度的 Codex CLI。Node.js 仅运行插件开发测试时需要。

### Windows 下载后安装（推荐）

1. 从 [最新发布](https://github.com/Hh681Hh/x-second-brain/releases/latest) 下载 `x-second-brain-0.3.6-source.zip`，解压到一个固定目录。
2. 安装 Python 3.11+；需要 AI 阅读时准备已安装并登录的 Codex CLI（`codex login`）。未准备好时仍可手动收藏及全文搜索。
3. 双击根目录的 `install-windows.cmd`。安装器创建虚拟环境、安装依赖、生成本地配置、安装 Codex Skill、注册当前用户自启并打开连接页；不会覆盖已有 `.env`、数据库或 Skill。
4. 按下方步骤在 Chrome / Edge 加载 `xsecondbrain/browser_extension`，配对一次，刷新 X 页面。

此项目尚未上架浏览器扩展商店，不是免步骤的商店安装包。Python、浏览器加载及配对仍需用户完成；第一次语义检索会下载本地模型。

如需**不展开长文也尝试自动补全文**，阅读下方 FxEmbed 隐私说明后，在 PowerShell 运行：

```powershell
& ./scripts/install-windows.ps1 -EnablePublicFulltext
```

该参数表示同意向 FxEmbed 发送待补全帖子 ID，默认安装不会开启。修改已有后台配置后须按“Windows 登录自启”的步骤重启后台。

安装器可选参数：`-Basic`（新安装关闭语义模型，保留全文搜索）、`-SkipSkill`、`-NoAutostart`、`-NoStart`、`-PythonExe C:\path\python.exe`（指定已安装的解释器）。只安装依赖、不启动任何进程或注册自启可同时使用 `-NoStart -NoAutostart`。安装器会跳过可能打开微软商店的 Python 别名；找不到解释器时请安装 Python 并启用 PATH，或显式指定路径。失败时保留文件，可解决错误后重新运行。安装依赖需要网络，模型调用使用对应账号额度。

### 从源码安装

```sh
git clone https://github.com/Hh681Hh/x-second-brain.git
cd x-second-brain
```

Windows PowerShell：

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -e '.[semantic,test]'
Copy-Item .env.example .env
codex login
& ./.venv/Scripts/python.exe -m xsecondbrain.agent_cli start --setup-if-needed
```

macOS / Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[semantic,test]'
cp .env.example .env
codex login
.venv/bin/python -m xsecondbrain.agent_cli start --setup-if-needed
```

首次启动自动初始化 `data/knowledge.sqlite3`，后续启动自动补建新增表。不要覆盖已有 `.env`。本地语义模型首次下载约 90 MB；暂不需要语义检索可安装 `.[test]` 并设置 `EMBEDDING_PROVIDER=none`。

### 安装插件并配对

1. 打开 `chrome://extensions` 或 `edge://extensions`，启用开发者模式。
2. 选择“加载已解压的扩展程序”，选择仓库中的 `xsecondbrain/browser_extension`。也可下载 [Releases](https://github.com/Hh681Hh/x-second-brain/releases) 中的插件 ZIP，解压后选择含 `manifest.json` 的目录。
3. 打开 [本地连接页](http://127.0.0.1:8787/)，生成一次性配对码。在工具栏插件中输入并连接。
4. 刷新已经打开的 X 网页，随后照常点击原生书签按钮。

默认模式下，未展开的长文只暂存预览。希望不手动展开时，先阅读下方“自动补全文”。已有收藏可在展开原文后点插件“保存当前内容”；相同链接去重并允许补全，不需要取消后重新收藏。

插件监听用户点击及网页显示的收藏状态，不控制 X 登录、不读取密码或 Cookie、不调用 X 内部 GraphQL、不自动遍历账号历史。页面结构变化可能影响识别。只有收到后台确认才从浏览器队列移除；离线暂存后每分钟重试，队列上限 100 条、共 150 万字符。

### 可选：自动补全文

在 `.env` 中设置，然后重启后台：

```dotenv
X_PUBLIC_FULLTEXT_PROVIDER=fxembed
```

仅当浏览器提交的内容被识别为预览时，后台把该帖子的数字 ID 发给 `api.fxtwitter.com`，取得公开文字正文后自动排队分析。无需 X 开发者应用或 X Cookie；启用即选择向这个第三方发送需要补全的帖子 ID，服务也能看到网络 IP。不会提交整份知识库或账号密码。

FxEmbed 是非官方第三方服务，当前公开接口无需密钥；**不保证永久免费、平台认可、全量覆盖或长期稳定**。私密、已删除、付费受限内容可能无法读取；图片 OCR、视频转写、整串帖子与站外全文不在该适配器范围内。失败保留预览及错误。严格只接受官方授权接口时，请保持 `none`，或自行配置官方 API 路径。

[免费方案调研及真实测试](docs/FREE_FULLTEXT.md) · [FxEmbed 文档](https://docs.fxembed.com/api/introduction/) · [第三方隐私说明](https://docs.fxembed.com/guide/faq/)

### Windows 登录自启

```powershell
& ./scripts/autostart.ps1 -Action enable
& ./scripts/autostart.ps1 -Action status
```

注册当前用户的 Windows 计划任务，登录时启动隐藏守护，并每分钟尝试恢复退出的守护进程；守护每 30 秒检查服务，连接被拒绝时恢复。文件锁和任务设置防止重复启动。同时保留启动文件夹快捷方式；计划任务注册被系统拒绝时会明确提示仅有登录自启。`status` 显示自启配置，实际后台健康状态用 `python -m xsecondbrain.agent_cli status` 检查。

启用时保存当前可用的 Codex CLI 路径，避免 Windows 计划任务缺少桌面应用 PATH 而无法分析。登录后运行，关机、休眠或用户未登录时不工作。保留项目与虚拟环境位置；移动项目或 Codex CLI 路径变化后重新启用。停用及正常停止：

```powershell
& ./scripts/autostart.ps1 -Action disable
& ./.venv/Scripts/python.exe -m xsecondbrain.agent_cli stop
```

修改配置后，如已启用守护，先 disable、stop，再 enable，避免旧进程保留环境变量。macOS / Linux 后台可运行，未附带系统自启安装器。

## 在 Codex 中调用知识库

```powershell
& ./.venv/Scripts/python.exe scripts/install_skill.py
```

安装到 `$CODEX_HOME/skills` 或 `~/.codex/skills`，已存在时拒绝覆盖；可使用 `--target /absolute/skills` 指定技能父目录。打开新 Codex 会话后，可以说：

- “搜索我以前收藏的关于 AI Agent 获客的文章。”
- “根据收藏的方法，帮我设计自动客服；把文章建议和你的补充判断分开。”
- “把相关收藏整理成研究报告，每个重要结论附原文出处。”

Skill 通过真实 HTTP 接口读取同一个知识库，不把聊天记忆当成收藏。后台阅读是独立临时 Codex CLI 会话，不会自动在当前聊天发送消息。

```powershell
& ./.venv/Scripts/python.exe skills/x-second-brain/scripts/xsb.py stats
& ./.venv/Scripts/python.exe skills/x-second-brain/scripts/xsb.py browser-status
& ./.venv/Scripts/python.exe skills/x-second-brain/scripts/xsb.py search '怎样减少重复答疑？'
& ./.venv/Scripts/python.exe skills/x-second-brain/scripts/xsb.py ask '根据收藏，怎样搭建自动客服？'
```

[Skill 操作规范](skills/x-second-brain/SKILL.md) · [API 客户端说明](skills/x-second-brain/references/api.md)

## 配置与运维

完整变量见 [.env.example](.env.example)。密钥只存服务端，不提交到 Git。

| 配置 | 作用 |
| --- | --- |
| `PORT=8787` / `DATA_DIR=./data` | 服务端口与数据目录 |
| `LLM_PROVIDER=codex` | 使用现有 CLI 登录及额度；缺少登录或额度时保留原文并报错 |
| `LLM_PROVIDER=api` | 配置 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`；启动用 `start --engine api` |
| `EMBEDDING_PROVIDER=local` | 本地 BGE；可改 `api` 或 `none` |
| `KNOWLEDGE_WORKERS=1` | 同时阅读文章数，允许 1–3 |
| `X_PUBLIC_FULLTEXT_PROVIDER=none` | 第三方补全默认关闭；可选 `fxembed` |
| `APP_TOKEN` | 所有者接口访问令牌；Skill 使用对应 `XSB_TOKEN` |

日常命令：`python -m xsecondbrain.agent_cli status`、`connect`、`stop`。只停止经过项目标记和 PID 验证的本项目进程。日志在 `data/app.log`、`data/agent-console.log`、`data/autostart.log`。

只需要手工管理而没有模型时，设置 `LLM_PROVIDER=api` 并留空模型及密钥，执行 `python -m xsecondbrain.agent_cli start --engine api`。页面显示 AI 未配置，仍可管理原文。

可选界面：[工作台](http://127.0.0.1:8787/workbench)、[API 文档](http://127.0.0.1:8787/api/docs)、[官方 OAuth 设置](http://127.0.0.1:8787/official-x)。官方同步需要自己的开发者应用、权限与 API 额度，见 [X_SYNC.md](docs/X_SYNC.md)。

备份与恢复（备份含私人正文和对话，请妥善保存）：

```powershell
& ./.venv/Scripts/python.exe skills/x-second-brain/scripts/xsb.py export --output ./backup.json
& ./.venv/Scripts/python.exe skills/x-second-brain/scripts/xsb.py import --file ./backup.json
```

导出不包含插件令牌、模型密钥、X OAuth 凭证或模型权重。后台默认仅监听本机；不要直接暴露到公网。容器运行与限制见 [部署说明](docs/DEPLOYMENT.md)。

## 在工作台读收藏重点

打开 [工作台](http://127.0.0.1:8787/workbench#home)，首页先展示最近收藏，每篇显示摘要、作者、分类和处理状态。

首页的“AI 已整理”和“知识与方法”统计后台真正保存的分析；“只看未读”表示你本人是否读过，与 AI 处理进度独立。缺全文、分析失败或仅存原文会列入“查看待处理”。已配对插件和启用补全文的状态会在首页显示，但配对不代表浏览器当前在线。页面空闲时也会检查新收藏，无需手动刷新或点开文章触发分析。

点击一篇文章默认进入“重点摘要”：

- **30 秒读懂**：突出核心总结。
- **记住这几个要点**：先看前三个要点，继续查看全部精读。
- **可以怎么做**：显示已有方法，按需展开执行步骤。
- **核对原文**：点击引用定位保存正文；精读、深度分析和原文仍可切换。

这里复用已生成且带出处的分析，不会因打开文章再次调用模型。没有全文或模型未配置时明确提示，不把原文摘录伪装成摘要。页面适配手机宽度；这是网页排版适配，不代表手机 X App 收藏同步。

## 架构与代码

```text
X 原生书签点击 → MV3 插件 → 本地接收 / 去重 / 队列
                               ↓ 预览 + 用户启用时
                         FxEmbed 公开全文接口
                               ↓
                   原文 + 三层摘要 + 方法卡 + 分类
                               ↓
                SQLite / FTS5 + 本地或 API Embedding
                               ↓
              Codex Skill / 网页问答 → 真实片段与原链接
```

`xsecondbrain/` 为后端与前端，包含 `browser_extension/`；`skills/` 为可独立安装的 Skill；`scripts/` 为启动、打包与验证工具；`tests/` 使用隔离数据库。数据库保留原文，问答不只搜索摘要。混合检索通过 RRF 融合，引用逐字核对；引用存在不等于作者观点已被外部事实核实。

[设计与数据结构](docs/DESIGN.md) · [竞品调研](docs/RESEARCH.md) · [后台与权限](docs/BACKGROUND.md)

## 升级已有索引

更新代码并重启后台后，已有收藏可执行以下命令，利用已保存的知识卡重建检索索引，无需再次调用阅读模型。原文、分析与引用位置保持不变。本地向量模型不产生 API 费用；使用远程 Embedding 时仍按供应商计费。

```powershell
& ./.venv/Scripts/python.exe scripts/reindex_saved.py --all
```

也可使用 `--article <文章ID>` 只更新一篇已分析的收藏。

## 测试与开发

```powershell
& ./.venv/Scripts/python.exe -m pytest -q -m 'not integration'
node --test tests/browser_extension.test.cjs
```

2026-10-22 已通过 84 项 Python 测试、9 项插件 Node 测试。真实模型/外网测试需显式启用，默认 CI 不使用个人账号或付费额度。公开 Article 隔离测试取得 16,484 字符正文，22 处引文通过原文偏移验证。随后真实 Chrome 未展开卡片书签测试取得 31,021 字符，218 段均与可见 X 正文匹配，24 处分析引用及 6 处问答引用通过原文核对；实际分类为“其他知识”，标签包括个人成长、目标管理。详见 [全文验证](docs/FREE_FULLTEXT.md)。

最新用户验收：从 GitHub 实际下载并安装发布包，网页保存与重启持久化通过；真实 Chrome 未展开正文点击原生书签，自动补取 16,484 字符、分析并分类为“获客与营销”。中文问题找回英文文章排名第 1，真实 Skill 问答的 3 处该文引文通过原文核对，网页点击引用能定位正文。修复了旧索引中文知识描述截断导致的漏召回。

[测试范围与复现方法](docs/TESTING.md) · [贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md) · [更新记录](CHANGELOG.md)

尚未完成：手机收藏同步、免费全账号历史遍历、自动周刊、OCR、完整 Thread 聚合、自动矛盾图谱、生产多用户及大规模负载验收。Codex CLI 真实阅读验证版本为 `0.163.0-alpha.10.2`；其他 CLI 版本参数变化可能需要适配。

## 许可

核心原创代码采用 [MIT](LICENSE)。第三方依赖及模型按各自许可证使用，见 [第三方声明](THIRD_PARTY_NOTICES.md)、[依赖清单](docs/dependency-licenses.json) 和 `licenses/`。参考项目仅用于调研，未复制其业务代码、UI 或品牌。文章版权归原作者，个人知识库不会随代码上传。
