# 测试范围与复现

本页只记录脱敏结论，不随源码发布个人收藏、日志或本机部署记录。验证日期：2026-10-21。

## 自动回归

```sh
python -m pytest -q -m 'not integration'
node --test tests/browser_extension.test.cjs
```

本机 Python 3.12：80 项通过，4 项真实集成测试未选入；Node 插件测试 9 项通过。仓库附带 Windows 与 Ubuntu 的 Actions 模板；本次上传凭证缺少 workflow scope，云端 CI 尚未启用，不宣称远程测试通过。启用方法见 [.github/workflow-templates/README.md](../.github/workflow-templates/README.md)。

覆盖：原文持久化与去重、预览补全、导入导出、全文检索、引用校验、无模型降级、后台队列与并发、插件配对及权限、网络失败保留原文、OAuth 协议夹具、全文接口开关与身份检查、Windows 守护启动决策。HTTP/模型夹具用于验证协议与边界，不代表真实外部服务已接通。

## 已完成的真实验证

- 公开网页正文采集与实际本地 BGE 语义检索。
- 原创标记样例的真实本地模型跨文章分析与引用问答、重开数据库保留数据。
- 实际 Codex CLI 自动分析、分类、引用问答；验证 CLI 版本 0.163.0-alpha.10.2。
- 真实 X 原生书签点击触发插件入库；该项正文已加载，不能代表未展开长文。
- Windows 自启快捷方式实际启动及后台停止后的守护恢复；未以实际系统重启验收。
- FxEmbed 公开 Article 16,484 字符、112 个正文块与可见原文匹配；真实 Codex 分析产生 22 处有效引文。见 [全文补取报告](FREE_FULLTEXT.md)。

## 显式集成测试

以下命令可能下载模型、使用网络或消耗账号额度；不在默认 CI 运行。PowerShell 用 `$env:变量='值'` 设置开关，POSIX shell 用 export。

- `XSB_RUN_NETWORK=1`：运行 `pytest tests/test_real_models.py::test_real_public_page_extraction -q`。
- `XSB_RUN_SEMANTIC=1`：运行 `pytest tests/test_real_models.py::test_real_semantic_paraphrase -q`，下载/加载 BGE。
- `XSB_RUN_CODEX=1`：运行 `pytest tests/test_background_reader.py::test_real_codex_analysis_classification_and_grounded_answer -q`。
- 配置 `XSB_TEST_LLM_URL / XSB_TEST_LLM_MODEL / XSB_TEST_LLM_KEY`：运行 `pytest tests/test_real_models.py::test_real_llm_end_to_end -q`；支持时设置 XSB_TEST_JSON_SCHEMA=1。
- `python scripts/verify_public_fulltext.py --run-live`：真实公开样本补全文及 Codex 分析，在隔离数据目录输出报告。

## 未验收与限制

未展开原生书签点击到第三方全文、分类的完整浏览器链路；真实 X 官方 OAuth/API；手机 App 同步；真实 iPhone Safari；Docker 构建；公网多用户及大规模负载均未完成验收。

逐字引用只能证明原文存在，不能证明观点正确或模型推理完全可靠。模型质量、上下文和额度会影响结果。Starlette 测试客户端目前有弃用提示，不影响已通过的测试。
