# Git 历史敏感模式清理设计

日期：2026-08-12

## 1. 目标与完成定义

本次工作清除所有公开分支历史中符合项目扫描规则 `sk-[A-Za-z0-9]{12,}` 的内容，使新 clone 执行 `scripts/scan-history.ps1` 返回 0，并解除该门禁对 Release 的阻断。

完成必须同时满足：

1. 重写前后的 `main` 当前文件树对象完全一致，正常项目文件不增删、不改变；
2. 当前树扫描、历史扫描、全量 pytest、Ruff 全部通过；
3. GitHub 与 NJU GitLab 的 `main` 均指向同一个重写后提交；
4. GitHub 旧远端分支 `task/14-final-evidence` 不再引用旧历史；
5. 从两个远端分别新建的验证 clone 均通过历史扫描；
6. 当前本地仓库完成安全切换，不再保留可达的旧分支、remote-tracking ref 或 reflog；
7. 一次性备份在双远端和本地验证完成后删除。

本次不把“公开 branch 历史已清理”描述为“GitHub 所有内部缓存已永久清除”。

## 2. 已知范围

- 当前基线为 `main@4305dd6a4711d7401176a66bf038af9ce5af9dff`，GitHub/NJU `main` 一致；仓库无 tag。
- 历史扫描只输出 commit/path 元数据，已确认命中早期 `detect-api.ps1`、`mini-harness/agent.py`，以及两个后来已修正但旧 blob 仍存在的测试文件。
- 当前树扫描已通过，因此不能通过修改当前文件解决。
- GitHub 仍有旧远端分支 `task/14-final-evidence`；NJU 只有 `main`。
- 用户确认没有其他协作者或需要保留的 clone。

## 3. 方案选择

采用“精确内容替换”，不采用重新建立单一根提交，也不采用只轮换 Key。

- 精确替换保留 commit 的父子结构、提交信息、作者、日期和课程过程，只改变含匹配内容的 blob 及其后代 SHA。
- 新根提交会丢失课程要求关注的 Superpowers、TDD、PR 和迭代过程，不接受。
- 只轮换 Key 无法让现有历史扫描通过，不能解除 Release 门禁。

替换范围与项目扫描规则一致：所有历史 blob 中匹配 `sk-[A-Za-z0-9]{12,}` 的字节序列替换为不再匹配该规则的固定占位符 `[REDACTED-HISTORICAL-TOKEN]`。真实临时 Key和旧测试假串统一处理，避免新历史仍被相同门禁阻断。

## 4. 隔离、工具与可恢复性

### 4.1 不在当前工作仓库内试改

历史转换在 OS 临时目录下的全新镜像 clone 中执行。使用 `uvx` 临时运行固定版本的 `git-filter-repo`，不进行全局安装；记录实际版本。

当前 `D:\Codes\FBW` 在远端更新验证完成前保持原样，三份未跟踪进度文件不进入镜像、历史或备份。

### 4.2 一次性备份

强制更新远端前，从原始 `main@4305dd6` 创建 Git bundle，存放于工作区外的 OS 临时目录。备份文件只用于本次失败恢复，不上传、不提交、不复制到项目目录。

备份生命周期：

1. 创建后用 `git bundle verify` 验证；
2. 远端更新或本地切换任一步失败时保留，供恢复；
3. 两个远端的新 clone、本地 main 和所有门禁均验证通过后删除；
4. 删除后不可从本机恢复旧历史，这是敏感历史清除的预期结果。

## 5. 重写与不变量验证

### 5.1 重写输入

一次性镜像只导入需要保留的规范分支 `main`。旧 GitHub 分支不进入新规范历史，随后在远端显式删除。无 tag，因此不产生 tag 更新。

### 5.2 必须保持的不变量

重写前记录：

- 原始 `main` SHA；
- 原始 `main^{tree}` tree object ID；
- GitHub/NJU `main` SHA；
- GitHub 旧分支 SHA；
- 当前树和历史扫描退出码。

重写后必须满足：

- 新 `main^{tree}` 与原始 tree object ID 完全相同；
- `git diff <原始-main> <新-main> --` 无输出；
- commit 数量、首尾提交信息和合并拓扑检查无异常；
- `scripts/scan-current-tree.ps1` exit 0；
- `scripts/scan-history.ps1` exit 0；
- 全量 pytest 0 failures；
- Ruff exit 0。

任一不变量失败时，停止在本地，不推送任何远端。

## 6. 双远端更新

### 6.1 并发保护

更新前再次只读查询 GitHub/NJU `main` 和 GitHub 旧分支 SHA。任一值与重写前记录不一致，说明远端在操作期间发生变化，立即停止并重新设计，禁止覆盖未知提交。

### 6.2 更新方式

只使用带明确旧 SHA 租约的 `--force-with-lease=<ref>:<expected-old-sha>`，禁止无条件 `--force`。

顺序：

1. 更新 GitHub `main`；
2. 删除 GitHub 旧分支 `task/14-final-evidence`；
3. 从 GitHub 创建全新验证 clone并运行历史扫描；
4. 更新 NJU `main`；
5. 从 NJU 创建全新验证 clone并运行历史扫描；
6. 核对两个远端 `main` 都等于新 SHA。

如果 GitHub 已更新而 NJU 失败，保留 bundle 和镜像，不回滚已经安全清理的 GitHub；诊断 NJU 后继续把同一新历史同步过去。禁止重新推回旧敏感历史。

## 7. 当前本地仓库切换

双远端通过后才处理 `D:\Codes\FBW`：

1. 确认只有三份预期未跟踪进度文件，没有 tracked 修改；
2. 获取新 `origin/main`；
3. 将本地 `main` 移到已验证的新 SHA；这是历史重写所必需的非快进更新；
4. 恢复/保留三份未跟踪进度文件；
5. 删除旧本地 cleanup 分支、旧 remote-tracking refs、reflog，执行对象清理；
6. 复跑当前树扫描、历史扫描、全量 pytest、Ruff；
7. 删除一次性镜像、验证 clones 和 bundle。

本地非快进切换只针对已精确核对的新 `main`，不使用 `git reset --hard` 丢弃未知工作。若发现 tracked 修改或额外未跟踪文件，停止并报告。

## 8. 托管平台残留边界

GitHub 官方说明：仅重写并强推分支后，旧提交仍可能通过 commit SHA 缓存或 Pull Request 内部引用访问；永久清除这些引用需要联系 GitHub Support，而且清除相关内部 PR refs 可能使旧 PR diff 无法继续查看。

因此本次分两种结论：

- **Release 历史门禁通过：** 规范分支、新 clone 和项目扫描均无匹配，可在本次自动流程内完成。
- **GitHub 内部缓存永久清除：** 自动流程整理受影响的首次修改 commit、新旧 SHA 和可能关联的 PR 元数据，由用户通过 GitHub Support 提交；Support 是否受理及 PR diff 影响属于外部步骤。

本项目不删除整个 GitHub 仓库，因为那会丢失课程 PR、CI 与审查过程。NJU 未使用 Merge Request，本次更新规范 `main` 后以新 clone扫描与最新 pipeline 作为证据。

## 9. CI 与正式证据

- GitHub 新 `main` 必须等待 workflow 绿色。
- NJU 新 `main` 必须由用户登录后确认最新 pipeline 绿色。
- 更新 `PLAN.md`、`AGENT_LOG.md`、`README.md`、`docs/evidence/release-checklist.md` 与 `docs/evidence/ci-last-pass.md`，记录新 SHA、扫描通过、双端 CI 与平台缓存边界。
- 不创建 tag/Release，直到干净 Windows 和 WebUI 有意偏离等剩余门禁另行裁决。
- 不在任何文档、命令输出或 Support 元数据中回显 Key 原文。

## 10. 停止条件

出现以下任一情况必须停止，不自行猜测：

- 当前仓库出现预期三份进度文件之外的未提交内容；
- 重写前后当前 tree 不一致；
- 历史扫描仍命中或扫描器自身错误；
- 测试、Ruff 或当前树扫描失败；
- 远端 SHA 与租约预期不一致；
- 分支保护拒绝 force-with-lease；
- 任一操作需要删除或覆盖未在本文精确列出的分支、tag、文件或远端引用。
