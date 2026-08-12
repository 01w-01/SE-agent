# FBW v0.1.0 发布证据

## 固定发布字段

| 字段 | 值 |
| --- | --- |
| 版本 | `v0.1.0` |
| Release | <https://github.com/01w-01/SE-agent/releases/tag/v0.1.0> |
| 发布工作流 | [Run 31624847385](https://github.com/01w-01/SE-agent/actions/runs/31624847385)（`unit-test`、`release` 均成功） |
| tag 对象 | `b602450f861a078afcf291ec9a4412670f04895a` |
| tag 目标提交 | `f61bf48684ca0ada9de8ac00644ff7d2e68dc60b` |
| 平台 | Windows x64，pure CLI |
| 附件 | `fbw-harness.exe`、`fbw-harness.exe.sha256` |
| SHA-256 | `b96abc383ce2cee995298ca7394e3e5862b58b245fbbd9490007576e29350fed` |
| EXE 大小 | `20160138` bytes |

## 独立下载复核

- SHA-256 与随附校验文件一致。
- `fbw-harness.exe --help`：exit `0`。
- `fbw-harness.exe demo all`：exit `0`；三个 demo 均 PASS。
- `fbw-harness.exe credential status`：连续两次均 exit `0`，均显示 `configured=True; service=fbw-harness; account=default`；用户裁决按该现有状态验收，未回显或变更凭据内容。
- GitHub hosted clean Windows Run `31616841988` 曾独立记录无凭据 `credential status` 为 `configured=False`；该环境证据不替代本次下载复核。
- 受控下载目录已清理，`CLEANED=True`。

## 边界

- 二进制未签名；使用前仍须校验 SHA-256，并按组织安全政策处理 SmartScreen。
- 本发行物为纯 CLI；WebUI 课程项仍是已批准的 `COURSE WEBUI DEVIATION`，未宣称课程清单全部完成。
- Explorer SmartScreen 与实体 Windows 10/11 人工体验未在本发行物下载复核中覆盖。
- `REFLECTION.md` 正文仍由学生本人完成，本次未创建或代写。
