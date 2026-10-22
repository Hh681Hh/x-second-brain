# 免费全文补取：方案与验证

调研日期：2026-10-21。实现见 `xsecondbrain/public_fulltext.py`，默认关闭。本适配器独立编写，没有复制第三方业务代码。

## 方案选择

| 方案 | 能力与限制 |
| --- | --- |
| 本项目默认 DOM 剪藏 | 不发送书签 ID 给额外取文服务；只能保存已经加载的文字 |
| [FxEmbed](https://docs.fxembed.com/api/introduction/) | 公共 v2 接口无需密钥，实测返回完整公开 Article 正文块；非 X 官方服务，不保证平台认可、永久免费或持续可用 |
| [xTap](https://github.com/mkubicek/xTap) | MIT；观察已加载页面响应，不能保证仅有列表卡片时已有完整文章 |
| [BookmarkX](https://github.com/LucasDitchun/export-bookmarks-x-twitter) | MIT；DOM 采集，同样受已加载正文范围限制 |
| [XClipper](https://github.com/zendegani/XClipper) | 当前 PolyForm Noncommercial；DOM 模式仍受页面范围限制，内部接口模式不纳入本项目 |
| [x-bookmark-exporter](https://github.com/ikaros-labs/x-bookmark-exporter) | MIT；官方 API 仍需权限/额度，不作为无 API 费用方案 |
| X 官方 API | 授权路径明确，但需应用、权限与额度，Article 返回范围仍需实际账号验证 |

FxEmbed 项目源码采用 MIT，远程服务使用仍受其服务条件和 X 平台规则影响。没有要求用户提供 Cookie 自建服务；没有把非官方接口描述为 X 授权。

## 数据流

用户在浏览器点书签 → 插件提交链接及预览 → 后台确认配置为 fxembed → 请求固定 HTTPS 域名的 `/2/status/{id}` → 核对返回帖子 ID → 保存文字正文 → Codex 分析和分类。

第三方收到需要补全的帖子数字 ID 和网络 IP；不会收到 X 密码、Cookie 或整库备份。参见 [服务隐私 FAQ](https://docs.fxembed.com/guide/faq/)；错误日志可能记录请求 URL/帖子 ID。选择外部 LLM 时，分析正文另发送给该模型提供商。

适配器不跟随重定向，不读取代理环境里的认证，不带账号认证，限制响应为 4 MB；网络错误、限流及部分服务错误最多尝试三次。身份不符、只有预览或不支持的正文结构不覆盖原文。支持文字及 Markdown 块；图片、视频和嵌入引用帖不会假装已读取。

## 真实验证

隔离测试选择公开研究样本：[Dan Koe · The influencer is dead. The Age of Experience is here.](https://x.com/thedankoe/status/2112586533610156368)。此项测试未发送用户私有书签列表，也没有修改主知识库。

- 接口预览 200 字符，完整拼接正文 16,484 字符。
- 112 个非空正文块全部在真实 X 页面可见原文中找到对应文字（忽略空白差异）。
- 隔离数据库实际运行补全文和真实 Codex CLI 分析，状态 ready，分类“获客与营销”。
- 22 处引用与正文字符偏移一致；没有用伪造模型成功响应代替验证。
- 此测试从模拟插件提交的真实公开预览开始，**不是未展开原生书签点击的真实浏览器全链路测试**。已完成的另一项原生书签测试只覆盖正文已加载的情况。

### 真实 Chrome 一键书签验收（2026-10-21）

在已获授权的实际浏览器中选择公开样本 [Dan Koe · How to fix your entire life in 1 day](https://x.com/thedankoe/status/2010751592346030461)。点击前只显示个人页卡片与预览，未加载 Article 正文；仅点击一次 X 原生书签按钮，没有展开、手工提交导入或手工触发分析。

- 插件自动提交后约 0.6 秒保存 31,021 字符全文；取得全文后才另开原文核对。
- 218 个非空段落全部能在 X 可见正文中找到（忽略空白差异）。
- 后台真实 Codex CLI 自动分析完成，状态 ready，分类“其他知识”，标签含个人成长、目标管理、自我反思、行动反馈、身份认同。24 处分析引用通过原文字符位置核对。
- 已安装的 Codex Skill 以“我总是制定新年计划却坚持不下去，怎样用一天重新梳理目标和行动？”检索，找到此文，相关片段排名为 2、7、8。
- Skill 真实问答返回 AI 模式、收藏证据充足，3 条建议引用此文，6 处引文通过原文核对。没有用测试替身替代模型。

这是单篇公开 Article 的真实成功样本，不保证所有公开帖子都能补全。个人浏览器截图、正文与完整模型输出保留在本机，不上传仓库。

重复测试需可用网络、已登录 Codex CLI 和可用额度。脚本会访问公开服务并调用真实模型，所有输出写入忽略的 data 目录：

```sh
python scripts/verify_public_fulltext.py --run-live
```

默认 none。用户自行选择服务后设置 `X_PUBLIC_FULLTEXT_PROVIDER=fxembed` 并重启后台。历史待补全记录不会因修改配置自动遍历发送；可明确选择单篇重试。关闭时改回 none 并重启。
