# 最终发布验收清单

原始验收时间：2026-08-11 23:11:26 +08:00

原始构建/发行物验收基线：`d2572cfb21f8cad92fc766fdfc603ad9dd29d279`

增量复验日期：2026-08-12

增量代码与真实 API 复验基线：`bd67e11`（包含工具调用兼容实现；后续仅修正文档证据）

结论：**READY FOR PURE-CLI RELEASE；COURSE WEBUI DEVIATION**

用户于 2026-08-13 批准纯 CLI `v0.1.0` 软件发布；WebUI 不提供，课程 WebUI 项仍未满足。构建、exe 与 SHA 行仍对应原始基线；离线测试、Ruff、当前树扫描和真实 API 行已在增量基线重新验证。未创建 tag、GitHub Release 或其他公开发布物，tag/Release 为待执行。

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
| 离线全量测试 | PASS（增量复验） | 增量基线运行 `uv run --project mini-harness pytest -q`，exit 0；`754 passed, 1 skipped in 236.63s`。原始基线及构建内证据均为 `750 passed, 1 skipped` |
| Ruff | PASS（增量复验） | 增量基线运行 `uv run --project mini-harness ruff check mini-harness`，exit 0；`All checks passed!` |
| 三项离线 demo | PASS | `pwsh -NoProfile -File scripts/demo.ps1`，exit 0；guardrail、feedback、no-progress 均为 PASS |
| 当前树秘密扫描 | PASS（增量复验） | 增量基线运行 `pwsh -NoProfile -File scripts/scan-current-tree.ps1`，exit 0，无命中输出 |
| Windows 单文件构建 | PASS（仅当前机） | `pwsh -NoProfile -File scripts/build.ps1`，exit 0；PyInstaller 6.22.0 / Python 3.13.13 |
| exe SHA-256 | PASS（仅当前机） | 最新构建为 `57e2393276dcf97d15ee3cf6094190274d895987062955b76b41ddd170701670`；20,447,552 bytes；`.sha256` 与 `Get-FileHash` 一致。该值校验本次产物，不声明不同构建之间字节级可复现 |
| exe `--help` | PASS（仅当前机） | exit 0；命令帮助成功列出 run、credential、memory、demo |
| exe `demo all` | PASS（仅当前机） | exit 0；三项 demo 均为 PASS |
| 代码签名 | 非阻断限制 | `Get-AuthenticodeSignature` 为 `NotSigned`；未从 Explorer 启动，因此没有 SmartScreen 行为证据 |
| 学校真实 API | PASS | 目标 hostname `njusehub.info`、model `deepseek-v4-flash`。用户隐藏录入凭据；兼容性修复后 RunResult 为 `COMPLETED`、2 轮、仅修改 `clamp.py`、rollback complete，独立 pytest `3 passed`。未记录 Key、请求头、完整 prompt 或响应正文；最终 `configured=False`，一次性临时项目已删除 |
| GitHub hosted 全新 Windows EXE | 软件发布 PASS | [Run 31616841988](https://github.com/01w-01/SE-agent/actions/runs/31616841988)，`main@ab3a74f`；构建、SHA、受限 PATH、`--help`、`demo all`、两次未配置 `credential status` 与三文件 artifact 全绿 |
| 实体 Windows 10/11 人工体验 | 非阻断限制 | hosted runner 不等同于实体用户机器；未验证 Explorer SmartScreen、交互 `credential set/clear` 或在同机执行真实任务 |
| GitLab CI 最后一次 pass | PASS | NJU GitLab [Pipeline #320523](https://git.nju.edu.cn/wyl510/se-agent/-/pipelines/320523)；Pipeline 当时记录原 SHA `762b738`（内容映射到重写后 `17554b3`，但该 Pipeline 未在新 SHA 重跑）；`unit-test` 绿色 passed；详见 `ci-last-pass.md` |
| 历史秘密扫描 / AC-24 | PASS | 精确重写 120 个提交并增加合同过渡提交；GitHub/NJU fresh clone 的 `pwsh -NoProfile -File scripts/scan-history.ps1` 均 exit 0、无输出；当前规范 main 为 `9cd6cb5` |
| WebUI 最终清单项 | COURSE WEBUI DEVIATION | 仓库明确只有 CLI；**WebUI 最终清单项未满足**，但用户于 2026-08-13 批准其不阻断纯 CLI 软件发布 |
| tag / Release | 待执行 | 已完成发布准备；尚未创建 tag 或 GitHub Release，创建前不得声称 Release URL 已存在 |

## 非阻断限制与课程偏离

1. 实体用户体验：如需要该证据，在干净 Windows 10/11 x64 机器补充 Explorer SmartScreen、交互凭据生命周期和真实任务；核心离线 EXE 已有 hosted clean Windows 软件发布 PASS。
2. 签名：二进制仍未签名，用户应在 SHA-256 校验后按组织安全政策处理 SmartScreen 提示。
3. 课程 WebUI：不实现 WebUI；该课程项仍未满足，作为已批准的 `COURSE WEBUI DEVIATION` 保留。

上述限制不阻断已批准的纯 CLI `v0.1.0` 软件发布；tag/Release 仍待后续执行。
