# 干净 Windows EXE 自动验收设计

## 目标

使用 GitHub 托管的全新 `windows-latest` runner，验证打包后的单文件 CLI 能在运行时不依赖项目 Python/uv 环境完成核心离线操作，并留下可下载 artifact 与 CI 记录。此流程不创建 tag 或 Release。

## 方案

新增独立的手动工作流 `clean-windows-acceptance.yml`。工作流只允许 `workflow_dispatch`，使用只读仓库权限：

1. checkout 完整历史并安装 uv/Python，仅用于源码测试和构建；
2. 运行当前树与完整历史扫描；
3. 调用现有 `scripts/build.ps1`，复用已有全量测试、扫描、PyInstaller 和 SHA 生成逻辑；
4. 把 exe 与 SHA 复制到 runner 临时目录；
5. 在子进程中把 `PATH` 限制为 Windows 系统目录，不包含 Python、uv 或仓库虚拟环境；
6. 校验 SHA，并运行 `fbw-harness.exe --help`、`demo all`、`credential status`；
7. 验证 runner 初始无本项目凭据，命令不得创建凭据；
8. 上传 exe、SHA 和一份不含秘密的验收摘要 artifact。

## 安全与边界

- 不使用学校 API Key，不访问 LLM API，不执行真实任务；
- 不创建 tag、GitHub Release 或持久凭据；
- artifact 只包含 exe、SHA 和固定字段摘要；
- hosted runner 能证明全新云端 Windows 会话中的离线运行，不等同于实体 Windows 10/11 用户机器；
- 自动化不能观察 Explorer 双击、SmartScreen UI 或交互式 `credential set`，这些项目保持未覆盖；
- WebUI 有意偏离不属于本任务。

## 验收标准

- 工作流可手动触发且最小权限为 `contents: read`；
- build、SHA 校验、三个 EXE 命令全部 exit 0；
- 运行 EXE 时 PATH 不含 Python/uv/项目虚拟环境；
- `credential status` 显示未配置，执行后仍未配置；
- artifact 上传成功；
- workflow、合同测试、Ruff、当前树与历史扫描通过；
- 正式证据明确写成“GitHub hosted clean Windows PASS”，不宣称 SmartScreen/实体新机或真实 API 已覆盖。
