# Git 历史敏感模式清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变规范 `main` 当前项目内容的前提下，清除全部公开分支历史中的 `sk-...` 扫描命中，同步 GitHub/NJU，并保留可审计、可恢复的执行证据。

**Architecture:** 先以普通 PR 把设计和计划纳入稳定基线，再在 OS 临时目录的单分支 bare clone 中用 `git-filter-repo` 精确改写历史。tree 等价、双扫描、测试和 Ruff 全绿后，使用明确旧 SHA 的 `force-with-lease` 更新两个远端；最后以普通证据 PR 更新旧 SHA 引用和验收文档，并清除临时 bundle、镜像及本地旧对象。

**Tech Stack:** Git 2.54、PowerShell 7、Python 3.13、uv/uvx、git-filter-repo 2.47.0、pytest、Ruff、GitHub CLI。

## Global Constraints

- 不读取、打印、提交或写入替换文件中的真实 Key；只使用扫描规则本身。
- 不使用无条件 `git push --force`，仅允许把已记录的 ref 名和预期旧 SHA 显式传给 `--force-with-lease`。
- 不使用 `git reset --hard`；本地 `main` 只通过带旧值条件的 `git update-ref` 切换。
- 当前 tree 等价、历史扫描、当前树扫描、全量 pytest、Ruff 任一失败时，禁止更新远端。
- 远端 SHA 与预期不一致、分支保护阻止更新或出现未知 refs 时立即停止。
- 三份根 `docs/STATUS.md`、`docs/LOG.md`、`docs/PROGRESS.ascii.md` 永远不提交、不进入 bundle。
- GitHub PR 缓存永久清除是 Support 外部步骤；本计划只保证规范 refs、新 clone 和项目历史扫描通过。
- 不创建 tag 或 Release；干净 Windows 与 WebUI 有意偏离仍需另行处理。

---

### Task 1: 以普通 PR 固化设计和执行基线

**Files:**
- Modify: `docs/superpowers/specs/2026-08-12-history-secret-cleanup-design.md`
- Create: `docs/superpowers/plans/2026-08-12-history-secret-cleanup.md`

**Interfaces:**
- Consumes: 当前 GitHub/NJU `main@4305dd6`、已批准设计。
- Produces: 两端 CI 绿色且只含文档变更的唯一清理基线 SHA，记为 `$cleanupBaseline`。

- [ ] **Step 1: 自检设计与计划**

```powershell
rg -n 'T[B]D|T[O]DO|i[m]plement later|f[i]ll in details' docs/superpowers/specs/2026-08-12-history-secret-cleanup-design.md docs/superpowers/plans/2026-08-12-history-secret-cleanup.md
git diff --check
pwsh -NoProfile -File scripts/scan-current-tree.ps1
```

Expected: placeholder 查询无命中；其余命令 exit 0。

- [ ] **Step 2: 提交计划修订**

```powershell
git add -- docs/superpowers/specs/2026-08-12-history-secret-cleanup-design.md docs/superpowers/plans/2026-08-12-history-secret-cleanup.md
git diff --cached --check
git commit -m "docs: 规划 Git 历史敏感信息清理"
```

- [ ] **Step 3: 推送并创建普通 PR**

推送 `fix/history-secret-cleanup`，创建到 `main` 的 PR。PR 正文必须声明这是设计/计划，不执行历史重写，并附当前树扫描结果。

- [ ] **Step 4: 等待 GitHub branch/pull_request CI 绿色后合并**

Expected: 两个 `unit-test` 绿色；非 tag 的 release 正确跳过。合并后快进本地 `main`，记下 `$cleanupBaseline = git rev-parse main`。

- [ ] **Step 5: 同步 NJU 并确认最新 pipeline 绿色**

使用专用 NJU SSH 密钥普通推送 `main`，核对 `nju/main == $cleanupBaseline`；由用户登录确认最新 pipeline 绿色。

- [ ] **Step 6: 清理设计 worktree 与功能分支**

确认设计提交已是 `$cleanupBaseline` 祖先且 worktree 干净，然后删除 GitHub 远端功能分支、本地 worktree 和本地功能分支。Expected: `git worktree list` 只剩根工作区。

### Task 2: 创建可恢复快照和单分支重写镜像

**Files:**
- Create outside workspace: `%TEMP%/fbw-history-cleanup-$guid/original-main.bundle`
- Create outside workspace: `%TEMP%/fbw-history-cleanup-$guid/rewrite.git`
- Create outside workspace: `%TEMP%/fbw-history-cleanup-$guid/replacements.txt`

**Interfaces:**
- Consumes: `$cleanupBaseline`、GitHub/NJU main、GitHub 旧分支 `task/14-final-evidence`。
- Produces: 已验证 bundle、只含 `refs/heads/main` 的 bare clone、原始 SHA/tree/commit-count 元数据。

- [ ] **Step 1: 严格核对根工作区状态**

```powershell
git status --porcelain
git worktree list --porcelain
git ls-remote origin refs/heads/main refs/heads/task/14-final-evidence
git ls-remote nju refs/heads/main
git tag --list
```

Expected: 只有三份预期未跟踪进度文件；只有根 worktree；两个 main 均等于 `$cleanupBaseline`；旧 GitHub 分支 SHA 与调查记录一致；无 tag。

- [ ] **Step 2: 创建唯一 OS 临时根并记录不变量**

用 `[guid]::NewGuid().ToString('N')` 生成 `$guid`，创建名称精确为 `fbw-history-cleanup-$guid` 的 `$cleanupRoot`，验证其直接父目录是 `[IO.Path]::GetTempPath()`。记录 `$oldMain`、`$oldTree = git rev-parse "$oldMain^{tree}"`、`$oldCount = git rev-list --count $oldMain`、`$oldLegacyBranch`。

- [ ] **Step 3: 创建和验证单分支 bundle**

```powershell
git bundle create "$cleanupRoot/original-main.bundle" main
git bundle verify "$cleanupRoot/original-main.bundle"
```

Expected: bundle verify exit 0，bundle 不进入仓库。

- [ ] **Step 4: 创建只含 main 的 bare clone**

```powershell
git clone --bare --single-branch --branch main D:\Codes\FBW "$cleanupRoot/rewrite.git"
git -C "$cleanupRoot/rewrite.git" for-each-ref --format='%(refname) %(objectname)'
```

Expected: 规范输入仅为 `refs/heads/main`，SHA 为 `$oldMain`；若出现其他 heads/tags，停止。

- [ ] **Step 5: 创建无秘密的替换规则并验证工具版本**

`replacements.txt` 只含：

```text
regex:sk-[A-Za-z0-9]{12,}==>[REDACTED-HISTORICAL-TOKEN]
```

使用 `uvx --from git-filter-repo==2.47.0 git-filter-repo --version`，Expected: exit 0；不进行全局安装。

### Task 3: 重写历史并完成所有本地门禁

**Files:**
- Modify only in temp bare clone: all historical blobs matching the regex
- Create outside workspace: `%TEMP%/fbw-history-cleanup-$guid/verify-local`
- Read: `rewrite.git/filter-repo/commit-map`

**Interfaces:**
- Consumes: bare clone、replacement file、原始不变量。
- Produces: `$newMain`、commit map、本地全绿的新历史。

- [ ] **Step 1: 执行敏感数据模式重写**

```powershell
Push-Location "$cleanupRoot/rewrite.git"
try {
    uvx --from git-filter-repo==2.47.0 git-filter-repo --sensitive-data-removal --no-fetch --force --replace-text "$cleanupRoot/replacements.txt"
}
finally {
    Pop-Location
}
```

`--no-fetch` 为强制要求：敏感数据模式默认会从 origin 镜像抓取全部 refs，而本设计只允许已经核对的 bare `main` 输入。Expected: exit 0；禁止移除 `--no-fetch`、更改替换规则或扩大 refs。

- [ ] **Step 2: 验证历史结构与当前 tree 不变量**

记录 `$newMain` 并断言：

```powershell
git -C "$cleanupRoot/rewrite.git" rev-parse "refs/heads/main^{tree}"
git -C "$cleanupRoot/rewrite.git" rev-list --count refs/heads/main
git -C "$cleanupRoot/rewrite.git" log -1 --format='%s' refs/heads/main
```

Expected: new tree 等于 `$oldTree`；commit count 等于 `$oldCount`；头提交信息与旧 main 相同；`$newMain != $oldMain`。

- [ ] **Step 3: 在 bare clone 运行历史扫描**

```powershell
pwsh -NoProfile -File D:\Codes\FBW\scripts\scan-history.ps1
```

命令 cwd 固定为 `rewrite.git`。Expected: exit 0、无命中输出；exit 1 或 2 都停止。

- [ ] **Step 4: 从新历史创建本地验证 clone**

```powershell
git clone --single-branch --branch main "$cleanupRoot/rewrite.git" "$cleanupRoot/verify-local"
```

在 `verify-local` 运行：

```powershell
pwsh -NoProfile -File scripts/scan-current-tree.ps1
pwsh -NoProfile -File scripts/scan-history.ps1
uv run --project mini-harness pytest -q
uv run --project mini-harness ruff check mini-harness
```

Expected: 两个扫描 exit 0；pytest 0 failures；Ruff exit 0。

- [ ] **Step 5: 验证 commit map 完整且不含秘密输出**

commit map 必须包含 `$oldMain -> $newMain`，main 可达的每个旧 commit 都必须得到非零新 SHA；旧、新 commit 列均无重复。只记录受影响 commit 数、首次旧/新 SHA、受影响 refs；不得输出 blob 内容。

### Task 4: 用租约更新 GitHub 和 NJU 规范 refs

**Files:**
- No tracked file changes
- Create outside workspace: fresh GitHub/NJU verification clones

**Interfaces:**
- Consumes: `$oldMain`、`$newMain`、`$oldLegacyBranch`、全绿 mirror。
- Produces: 两个远端 main 等于 `$newMain`，旧 GitHub 分支删除，两个 fresh clone 历史扫描通过。

- [ ] **Step 1: 更新前重新核对租约**

```powershell
git ls-remote origin refs/heads/main refs/heads/task/14-final-evidence
git ls-remote nju refs/heads/main
```

Expected: 三个值逐字等于 Task 2 记录；任何变化停止。

- [ ] **Step 2: 用明确租约更新 GitHub main**

从 bare mirror 推送：

```powershell
git push --force-with-lease="refs/heads/main:$oldMain" https://github.com/01w-01/SE-agent.git refs/heads/main:refs/heads/main
```

Expected: GitHub main 等于 `$newMain`。

- [ ] **Step 3: 用明确租约删除旧 GitHub 分支**

```powershell
git push --force-with-lease="refs/heads/task/14-final-evidence:$oldLegacyBranch" https://github.com/01w-01/SE-agent.git :refs/heads/task/14-final-evidence
```

Expected: `ls-remote` 不再返回该分支。

- [ ] **Step 4: 从 GitHub fresh clone验证**

clone 到 `$cleanupRoot/verify-github`，核对 HEAD=`$newMain`，运行当前树扫描、历史扫描、全量 pytest、Ruff。全部通过后才继续 NJU。

- [ ] **Step 5: 用专用 SSH 密钥和明确租约更新 NJU main**

使用临时 known_hosts 文件与 `id_ed25519_nju_git`，执行：

```powershell
git push --force-with-lease="refs/heads/main:$oldMain" git@git.nju.edu.cn:wyl510/se-agent.git refs/heads/main:refs/heads/main
```

Expected: NJU main 等于 `$newMain`；临时 known_hosts 文件在 finally 删除。

- [ ] **Step 6: 从 NJU fresh clone验证**

使用同一专用 SSH 配置 clone 到 `$cleanupRoot/verify-nju`，核对 HEAD=`$newMain`，运行当前树扫描与历史扫描。Expected: exit 0。

### Task 5: 安全切换当前 clone并清除旧本地对象

**Files:**
- Preserve untracked: `docs/STATUS.md`、`docs/LOG.md`、`docs/PROGRESS.ascii.md`

**Interfaces:**
- Consumes: 两个远端已验证的新 main、bundle、当前本地 old main。
- Produces: 根仓库 main/remote-tracking refs 均为 `$newMain`，旧历史不可达。

- [ ] **Step 1: 再次验证本地未提交范围**

Expected: 只有三份指定未跟踪文件；无 tracked 修改、额外 worktree、分支或 tag。否则停止。

- [ ] **Step 2: 以旧 SHA 条件原子移动本地 main**

```powershell
git update-ref refs/heads/main $newMain $oldMain
git update-ref refs/remotes/origin/main $newMain $oldMain
git update-ref refs/remotes/nju/main $newMain $oldMain
```

Expected: 三条 ref 均等于 `$newMain`；工作树因 tree 相同保持无 tracked diff，三份进度文件仍存在。

- [ ] **Step 3: 清除旧 refs、reflog 与不可达对象**

先列出所有本地 refs并确认没有旧 SHA或未知引用，再执行：

```powershell
git reflog expire --expire=now --all
git gc --prune=now
```

Expected: `git fsck --unreachable --no-reflogs` 不列出旧敏感提交；历史扫描 exit 0。

- [ ] **Step 4: 在当前根仓库重跑门禁**

运行当前树扫描、历史扫描、全量 pytest、Ruff和 `git status --short --branch`。Expected: 全绿且只列三份未跟踪进度文件。

### Task 6: 更新 SHA 引用、正式证据与双端 CI

**Files:**
- Mechanically modify: all tracked `*.md` files containing old commit SHA tokens
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `README.md`
- Modify: `docs/evidence/release-checklist.md`
- Modify: `docs/evidence/ci-last-pass.md`
- Create: `docs/evidence/history-rewrite.md`

**Interfaces:**
- Consumes: commit map、`$oldMain/$newMain`、双远端 fresh-clone证据。
- Produces: 不引用旧 commit token 的审计文档、普通 PR、最新双端绿色 CI。

- [ ] **Step 1: 创建新 worktree和证据分支**

从 `$newMain` 创建 `fix/history-cleanup-evidence` 与独立 worktree；基线历史扫描必须 exit 0。

- [ ] **Step 2: 机械更新旧 SHA 引用**

读取 commit map，对所有 Git 跟踪的 Markdown 执行两类 token 边界替换：完整 40 位旧 SHA → 新 SHA；唯一七位旧前缀 → 对应新 SHA七位前缀。零映射只允许已明确删除的旧分支独有提交；不得替换非 commit 哈希。

验证：搜索 commit map 中全部非零旧 SHA的完整值与唯一七位前缀，受版本控制 Markdown 中均无残留；PR URL/编号不变。

- [ ] **Step 3: 写入历史重写证据**

`history-rewrite.md` 只记录日期、工具版本、旧/新 main SHA、受影响 commit 数、tree 等价、扫描/测试结果、GitHub/NJU fresh clone结果、旧分支删除和 GitHub Support边界，不记录 Key或 blob内容。

同步将 Release 历史扫描门禁从 FAIL 改为 PASS；保持干净 Windows、WebUI 有意偏离及 tag/Release 未运行。

- [ ] **Step 4: 验证并提交证据分支**

运行两个扫描、全量 pytest、Ruff、Markdown旧 SHA检查和 diff check。提交：

```powershell
git commit -m "docs: 记录 Git 历史清理证据"
```

- [ ] **Step 5: 普通推送、PR、CI和合并**

创建 GitHub PR；branch/pull_request CI 绿色后合并。同步 NJU main，等待 GitHub main workflow 绿色与用户确认 NJU 最新 pipeline 绿色。

- [ ] **Step 6: 最终 fresh clone与清理**

从 GitHub/NJU 最终 main 各建一次 fresh clone，历史扫描均 exit 0；根仓库全量/扫描/Ruff通过后，删除 evidence 分支/worktree、所有验证 clone、rewrite mirror、replacement file和 bundle。删除前逐一验证它们都位于精确 `$cleanupRoot`；最后删除空 cleanup root。

- [ ] **Step 7: 整理 GitHub Support 元数据**

只向用户提供 GitHub 官方 Support 页面、仓库 URL、首次受影响旧 commit SHA、受影响 PR编号和“请求移除 cached views/internal PR refs”的说明模板。不得包含 Key原文；Support 外部步骤保持待用户提交，不阻断规范 refs 的历史扫描 PASS。
