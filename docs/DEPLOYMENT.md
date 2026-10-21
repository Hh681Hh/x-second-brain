# 部署与运行

推荐个人电脑源码安装，见 [README](../README.md)。数据库首次启动自动初始化；升级前先导出备份。Python 后台跨平台，Windows 登录自启由 scripts/autostart.ps1 提供。

## 运行方式

- Codex 引擎：本机安装并登录 Codex CLI，运行 `python -m xsecondbrain.agent_cli start`。
- 兼容 API：在 .env 配置 LLM_PROVIDER=api、LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY，运行 `start --engine api`。
- 无模型：API 模式留空模型/密钥，仍可保存、全文搜索；自动分析不可用。
- 只在本机监听，默认端口 8787。不要停止占用其他端口的无关服务。

插件仅支持连接同一台电脑的 loopback 地址。远程网站部署不能直接代替浏览器本机后台。

## 可选 Docker

镜像只包含 Python 应用，不包含 Codex CLI 或任何账号登录，使用 API 引擎。Docker 配置已提供，尚未完成实际容器构建验收。

```sh
docker build -t x-second-brain .
docker run --rm --name x-second-brain -p 127.0.0.1:8787:8787 \
  --env-file .env -e HOST=0.0.0.0 -e PORT=8787 -e DATA_DIR=/data \
  -e LLM_PROVIDER=api -e HEADLESS=false \
  -v xsb-data:/data x-second-brain
```

.env 中必须设置非空 APP_TOKEN；其他模型配置按 README。容器非 loopback 监听模式下浏览器配对接口会拒绝请求，这是当前保护边界；该容器方式仅用于带令牌的工作台/API，推荐本机源码后台使用浏览器插件。Skill 配置相同的 XSB_TOKEN。没有把容器方案当作已验收的日常插件方案。

## 升级与备份

更新源码前导出个人知识库；停止守护与后台后更新依赖，重新启动。扩展代码更新后需在浏览器扩展页刷新扩展，再刷新 X 网页；保留扩展加载目录以保留插件身份。Skill 安装器不覆盖既有技能，更新前自行备份旧目录。

数据库、配对和凭证在 data，日志也在该目录。保留文件不等于备份已验证；定期在隔离数据目录测试导入。不要把数据目录和个人备份上传代码仓库。
