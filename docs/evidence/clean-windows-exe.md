# GitHub hosted 干净 Windows EXE 验收证据

状态：**PASS（云端全新 Windows 离线运行范围）**

验收时间：2026-08-13（Asia/Shanghai）

## 基线

- Workflow：[Clean Windows EXE acceptance Run 31616841988](https://github.com/01w-01/SE-agent/actions/runs/31616841988)
- Commit：`ab3a74fe0e76503b465d082437b8b487a5a3d548`
- Runner：GitHub hosted `windows-latest`，每次任务使用全新会话
- 权限：`contents: read`

## 通过项

- 当前树扫描：PASS
- 完整历史扫描：PASS
- `scripts/build.ps1`：PASS
- EXE SHA-256 与 `.sha256`：PASS
- 运行时 PATH：只包含 Windows 系统目录与 PowerShell 7，不包含 Python、uv 或项目虚拟环境
- `fbw-harness.exe --help`：PASS
- `fbw-harness.exe demo all`：PASS
- `fbw-harness.exe credential status`：连续两次均显示 `configured=False`
- 临时运行目录：finally 清理
- artifact 上传：PASS，3 文件

Artifact：[`fbw-harness-clean-windows-ab3a74fe0e76503b465d082437b8b487a5a3d548`](https://github.com/01w-01/SE-agent/actions/runs/31616841988/artifacts/9149681946)，包含 EXE、SHA 和固定字段验收摘要。

## 未覆盖边界

- hosted runner 不等同于实体 Windows 10/11 用户机器；
- 自动化未观察 Explorer 双击和 SmartScreen UI；
- 未执行交互式 `credential set/clear`；
- 未使用学校 API Key或执行真实 LLM 任务；
- 未创建 tag 或 GitHub Release；
- WebUI 有意偏离不属于本次验收。

因此，本证据支持“GitHub hosted 全新 Windows 上，单文件 EXE 核心离线运行通过”，不支持更宽泛的人工体验或真实 API 声明。
