# 最终发布验收清单

验收时间：2026-08-11 23:11:26 +08:00

验收基线：`cd2b0ef647e6be7072aeeca4bca8bb82ecde55e8`

结论：**不可发布（NOT RELEASABLE）**

任一强制门禁缺少通过证据都会阻断发布。本次只完成当前开发机上可安全执行的检查；未创建 tag、GitHub Release 或其他公开发布物。

## 环境与版本

| 项目 | 实测值 | 证据范围 |
|---|---|---|
| 操作系统 | 现有 Windows 11 x64，build 26200.8875、25H2 | 当前开发机，不是干净目标机；注册表兼容名称显示 `Windows 10 Home China` |
| 项目 Python | 3.13.13 | uv 项目环境与 PyInstaller 构建解释器 |
| uv | 0.11.17 | 当前开发机 |
| PowerShell | 7.4.18 Core | 当前开发机 |
| Git | 2.54.0.windows.1 | 当前开发机 |
| PyInstaller | 6.22.0 | 本次构建日志 |

## 门禁结果

| 门禁 | 状态 | 客观证据 |
|---|---|---|
| 离线全量测试 | PASS | `uv run --project mini-harness pytest -q`，exit 0；`750 passed, 1 skipped in 103.14s`。构建内再次为 `750 passed, 1 skipped in 103.33s` |
| Ruff | PASS | `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`，exit 0；`All checks passed!` |
| 三项离线 demo | PASS | `pwsh -NoProfile -File scripts/demo.ps1`，exit 0；guardrail、feedback、no-progress 均为 PASS |
| 当前树秘密扫描 | PASS | `pwsh -NoProfile -File scripts/scan-current-tree.ps1`，exit 0，无命中输出 |
| Windows 单文件构建 | PASS（仅当前机） | `pwsh -NoProfile -File scripts/build.ps1`，exit 0；PyInstaller 6.22.0 / Python 3.13.13 |
| exe SHA-256 | PASS（仅当前机） | `f8ecc9d6334c77fcdd6814a4398952a90cb0bf04363b9b99f4bfd3c9ae5a872d`；20,449,961 bytes；`.sha256` 与 `Get-FileHash` 一致 |
| exe `--help` | PASS（仅当前机） | exit 0；命令帮助成功列出 run、credential、memory、demo |
| exe `demo all` | PASS（仅当前机） | exit 0；三项 demo 均为 PASS |
| 代码签名 | NOT PASS | `Get-AuthenticodeSignature` 为 `NotSigned`；未从 Explorer 启动，因此没有 SmartScreen 行为证据 |
| 学校真实 API | BLOCKED | 目标 hostname `njusehub.info`、model `deepseek-v4-flash`。CredentialStore 为 `configured=False`；自动凭据提取/联网被安全审批拒绝，未完成必要的人工隐藏输入，未发起请求；无 RunResult、修改路径或测试摘要。临时项目已删除，最终仍为 `configured=False` |
| 干净 Windows 10/11 x64 | BLOCKED | 本机已有项目 Python/uv，不能作为干净新机；未验证 SmartScreen、exe 凭据 set/status/clear 或真实任务 |
| GitLab CI 最后一次 pass | BLOCKED | 只有 GitHub `origin`，没有 GitLab remote/pipeline URL；详见 `ci-last-pass.md` |
| 历史秘密扫描 / AC-24 | FAIL（预期阻断） | `pwsh -NoProfile -File scripts/scan-history.ps1`，exit 1；只输出 commit/path 元数据，共 34 行、18 个 commit、4 个路径，包含 `77da924`，未输出匹配内容；未重写历史 |
| WebUI 最终清单项 | BLOCKED | 仓库明确只有 CLI，未找到课程方书面豁免；**WebUI 最终清单项未满足** |
| tag / Release | NOT RUN | 上述强制门禁未全部通过，按 PLAN 禁止发布 |

## 发布阻塞项

1. 由人工通过隐藏输入配置临时凭据后，在 OS 临时项目完成一次真实 API 受控修复，并在 `finally` 清除凭据；当前未执行。
2. 在未安装本项目 Python/uv 的干净 Windows 10/11 x64 机器完成 exe、SHA、SmartScreen、凭据生命周期、demo 和真实任务验收。
3. 提供可核实的 GitLab pipeline URL、commit SHA、`unit-test` pass 时间。
4. 合规处理历史凭据并使历史扫描退出 0；需用户另行明确授权，当前不得改写历史。
5. 交付 WebUI，或取得课程方允许纯 CLI 的书面豁免。

只有五项全部解决并重新执行所有门禁后，才可考虑创建 tag/Release。
