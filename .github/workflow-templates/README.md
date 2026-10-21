# 启用 GitHub Actions

`tests.yml` 是可用的测试工作流模板，当前不自动运行。本次用于上传仓库的 GitHub OAuth 凭证没有 `workflow` scope，GitHub 拒绝创建 `.github/workflows/tests.yml`，所以模板保存在此目录；没有绕过授权限制。

有权限的仓库所有者可通过 GitHub 网页创建 `.github/workflows/tests.yml` 并粘贴本模板，或先为 GitHub CLI 授予 workflow 权限，再移动模板到该路径并提交。工作流仅需 contents:read，在 Windows/Ubuntu 的 Python 3.12 环境运行无账号 Python 与 Node 测试，不使用个人模型密钥。

启用后以 Actions 页面真实运行结果为准，不能将本机通过视为云端通过。
