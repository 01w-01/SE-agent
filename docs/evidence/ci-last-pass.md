# GitLab CI 通过证据

状态：**PASS（用户登录 NJU GitLab 后人工确认）**

确认时间：2026-08-12 18:23:34 +08:00

验证基线：`762b738915d1c1aaa0cb2dd1c5d4d9477c29baed`

| 必需字段 | 结果 |
|---|---|
| Pipeline URL | [NJU GitLab Pipeline #320523](https://git.nju.edu.cn/wyl510/se-agent/-/pipelines/320523) |
| Pipeline commit SHA | `762b738915d1c1aaa0cb2dd1c5d4d9477c29baed`（推送时本地 HEAD 与 `nju/main` 已核对一致） |
| Job 名称 | `unit-test` |
| 状态 | 绿色 `passed` |
| Pass 时间 | NJU GitLab 登录用户于上述确认时间核验；匿名 API 被反机器人验证页拦截，未自动读取服务端完成时间 |

`.gitlab-ci.yml` 的 `unit-test` 使用 Python 3.13 容器，依次执行当前树秘密扫描、Ruff 和全量 pytest。该证据满足课程要求的 NJU Git 仓库、指定 job 与 CI pass；它不消除真实 API、干净 Windows、历史凭据和 WebUI 偏离等其他发布阻塞。
