# fbw-harness 包

此目录包含 FBW Coding Agent Harness 的 Python 包、离线测试与 Windows 打包配置。完整的用户文档、安装、凭据安全配置、运行示例、机制演示与限制见[项目总 README](../README.md)。

开发命令：

```powershell
uv run --project mini-harness pytest -q
uv run --project mini-harness ruff check src tests
uv run --project mini-harness fbw-harness demo all
```

本包要求 Python 3.13。真实运行的 API Key 只通过 `fbw-harness credential set` 保存到 Windows Credential Manager；不要把 Key 写入测试、配置、环境文件或命令历史。
