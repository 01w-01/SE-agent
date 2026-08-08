# FBW Coding Agent Harness 智能体过程日志

## 1. 记录约定

- 按时间和过程 task 编号排列；早期记录由完整对话、`docs/LOG.md` 和 Git 历史回填，无法可靠还原的具体时分不虚构。
- 每条包含技能、关键 prompt/context、输出或 commit、人工干预和教训。
- 当前主开发智能体为 OpenAI Codex；截至本文件初始化，没有使用 subagent。
- 不记录 API Key、Authorization 请求头或其他秘密值。

## 2. 时间线

### 2026-08-05 · P-001 · 启动并验证 Superpowers

- Superpowers 技能：`using-superpowers`、`brainstorming`。
- 关键 prompt/context：完整阅读两份课程要求；确认插件是否安装启用；扫描 uv、PowerShell 7、Scoop 环境；禁止自行确定语言。
- 输出：确认 Superpowers 6.2.0 可用；列出 Python、TypeScript、Go 候选；发现 CLI/WebUI 与凭据两类潜在冲突。
- subagent/commit：未使用 subagent；无提交。
- 人工干预：用户选择 Python + uv，并要求用白话说明 Python 与 TypeScript 分发。
- 教训：环境可行不等于用户适合；技术推荐必须包含学习和分发成本。

### 2026-08-05 · P-002 · 收敛反馈闭环

- Superpowers 技能：`brainstorming`。
- 关键 prompt/context：六个 harness 维度中重点考虑反馈闭环；要求形成确定性、可解释的演示。
- 输出：选择 pytest 失败信号、`clamp()` 边界错误、结构化 Feedback 和失败指纹。
- subagent/commit：未使用 subagent；无提交。
- 人工干预：用户依次确认单元测试失败、`clamp()` 和结构化反馈，并要求阶段性白话回顾。
- 教训：用一个简单业务错误承载复杂机制，能避免演示目标被算法细节遮蔽。

### 2026-08-05 · P-003 · 纠正产品与演示边界

- Superpowers 技能：`brainstorming`。
- 关键 prompt/context：用户指出预期是能配置 Base URL/API Key 并直接使用的简陋产品，而非只修复一个函数。
- 输出：确立“真实 LLM CLI 产品 + Mock LLM 机制演示”双轨结构。
- subagent/commit：未使用 subagent；无提交。
- 人工干预：用户推翻过窄 demo 定义，选择继续实现可运行成品。
- 教训：`demo` 一词歧义很大，必须分别确认产品可用范围和评审演示范围。

### 2026-08-05 · P-004 · 建立初始 Git 基线

- Superpowers 技能：`brainstorming`（本次提交是用户明确要求的仓库准备动作）。
- 关键 prompt/context：提交一开始的文件，提交信息 `init`；不提交 `docs/` 进度文件；忽略 `docs/temp.md`。
- 输出/commit：创建根提交 `77da924 init`；更新忽略规则。
- subagent：未使用。
- 人工干预：提交范围和 message 均由用户指定。
- 教训：该提交纳入了早期脚本中的临时 API Key，导致 Git 历史不满足正式课程凭据规则；未经用户明确授权不得擅自重写历史。

### 2026-08-05 · P-005 · 重构安全模型

- Superpowers 技能：`brainstorming`。
- 关键 prompt/context：直接修改原项目，但不能损坏其他文件；全仓复制不适合大型项目；安全级别必须可解释。
- 输出：受控动作协议、工作区围栏、`ALLOW/CONFIRM/DENY`、禁止任意 PowerShell/删除/越界、写前哈希、原子替换和逐文件回滚。
- subagent/commit：未使用 subagent；无提交。
- 人工干预：用户否决粗粒度三方案，最终选择普通受控操作自动、高风险审批的直接修改模式。
- 教训：安全方案不能只贴“高/中/低”标签，必须说明具体威胁和失败时恢复行为。

### 2026-08-05 · P-006 · 确认模块化状态机

- Superpowers 技能：`brainstorming`。
- 关键 prompt/context：比较单文件循环、模块化状态机、事件驱动插件内核；兼顾真实 CLI、可单测机制和首版复杂度。
- 输出：选择同步单进程状态机；拆分 CLI、AgentLoop、LLM、解析、策略、事务、测试、反馈、记忆和配置。
- subagent/commit：未使用 subagent；无提交。
- 人工干预：用户采纳推荐方案，并将不改变产品行为的普通技术判断委托给智能体推荐。
- 教训：面向基础较弱的项目负责人，应把批准对象从内部术语转换为可观察行为和验收结果。

### 2026-08-05 至 2026-08-08 · P-007 · 完成 brainstorming 设计依据

- Superpowers 技能：`brainstorming`。
- 关键 prompt/context：分节确认架构、数据流、安全、错误、停机、测试和三项 Mock 机制演示。
- 输出：`docs/superpowers/specs/2026-08-08-coding-agent-harness-demo-design.md`。
- subagent/commit：未使用 subagent；`b773647 docs: 添加 Coding Agent Harness demo 设计`。
- 人工干预：用户连续批准模块化状态机、数据流、安全默认值和测试矩阵。
- 教训：该文档足以作为设计输入，但缺少课程正式 SPEC 的 INVEST、逐功能规约、凭据安全、分发和冲突治理，不能冒充正式交付物。

### 2026-08-08T22:45:40+08:00 · P-008 · 升级为正式课程规约

- Superpowers 技能：`using-superpowers`、`brainstorming`；明确未调用 `writing-plans`。
- 关键 prompt/context：仓库虽可舍弃，本次必须按正式 AI4SE 项目完成；完整复用课程原文、设计依据、进度记录和对话；先完成并自检 SPEC，由用户批准后才能计划和编码。
- 输出：正式 `SPEC.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md`；课程冲突显式登记。
- subagent：未使用。
- 人工干预：用户纠正项目定位，并明确要求不重写 Git 历史、不做 WebUI、继续 `main`。
- 教训：仓库生命周期与工程流程严肃性是两个不同维度；“以后可能重做”不能被解释为省略正式要求。

### 2026-08-08T23:03:58+08:00 · P-009 · 处理第一轮 SPEC 审阅

- Superpowers 技能：`using-superpowers`、`brainstorming`、`receiving-code-review`；明确未调用 `writing-plans`。
- 关键 prompt/context：首版保持纯 CLI，但结构允许未来增加 WebUI；临时 Key 历史保持不动且当前不公开；解释并重新决定 main/worktree/PR。
- 输出：将 CLI 收敛为入口适配器，增加 ApplicationService、EventSink、ApprovalProvider 边界；更新凭据风险状态和编码阶段 Git 工作流。
- subagent/commit：未使用 subagent；基于 `b5f3d72` 修订正式文档。
- 人工干预：用户接受当前私有阶段 Key 风险；决定现有历史不动，从正式编码开始使用 branch + worktree + PR。
- 教训：为未来扩展预留的是稳定接口和依赖方向，不是空目录或无行为占位代码；文档阶段直接提交 main 不必强迫未来编码继续偏离课程流程。

### 2026-08-08T23:25:08+08:00 · P-010 · SPEC 获批并生成正式 PLAN

- Superpowers 技能：`using-superpowers`、`writing-plans`；未调用实现技能。
- 关键 prompt/context：用户明确回复“批准 SPEC”；PLAN 必须位于根目录，覆盖 TDD、精确文件、接口、依赖、并行、worktree/PR、冷启动和全部课程交付。
- 输出：根目录 `PLAN.md`，包含 14 个 task、88 个步骤、依赖图、冷启动门禁、统一收尾检查和 SPEC 可追踪矩阵。
- subagent/commit：未使用 subagent；PLAN 由主 Codex 根据已批准 SPEC 生成，正式文档 commit 在本轮完成。
- 人工干预：用户的批准解除 writing-plans 门禁；此前选择的 branch + worktree + PR 成为每个编码 task 的强制流程。
- 教训：计划中的测试 helper 也属于接口，若不明确定义，陌生实现者会依赖主 agent 的隐性上下文；发布 task 必须把已知不合规写成停止条件。

### 2026-08-09T00:14:24+08:00 · P-011 · Claude 冷启动连接阻塞

- Superpowers 技能：`using-superpowers`、`using-git-worktrees`、`systematic-debugging`；未调用实现技能。
- 关键 prompt/context：使用全新 Claude Code 2.1.226、学校 Anthropic 兼容接口、默认 Flash 模型；只用一次性进程环境，不持久化会话或凭据。
- 输出：创建隔离分支/worktree；现有 uv 包导入基线正常，旧原型没有 pytest 依赖；Claude 的自定义模型直连、原生模型槽位映射和窗口校验组合均未成功。
- subagent/commit：Claude 尚未进入任务会话，没有 subagent 产出或 commit；worktree 跟踪文件干净且不合并。
- 人工干预：用户提供学校接口、Key 和模型选择；智能体没有把 Key 复制到日志或文件。
- 教训：Anthropic `/messages` 兼容不自动等于 Claude Code CLI 全部兼容；CLI 还有模型槽位、上下文窗口和鉴权约定。三次修正失败后应停止叠加开关并重新选择网关结构。

### 2026-08-09T00:46:00+08:00 · P-012 · 官方配置验证成功、长任务被限流

- Superpowers 技能：`using-superpowers`、`systematic-debugging`；延续既有 `using-git-worktrees` 隔离环境，未调用实现技能。
- 关键 prompt/context：用户要求优先核对 DeepSeek 官方 Claude Code 文档；只用进程级环境变量，不写凭据；冷启动仍只允许读取正式 SPEC/PLAN 并试做 Task 2/5。
- 输出：确认 Claude Code 应使用 `ANTHROPIC_AUTH_TOKEN`、学校域名根地址和带 `[1m]` 的 DeepSeek 模型名；Flash/Pro 最小连接成功。两次完整冷启动分别收到通用 `503` 和明确的系统容量限流。
- subagent/commit：Claude Code 是课程要求的陌生智能体，不是 Codex subagent；没有产出源码或 commit，隔离 worktree 跟踪文件干净。
- 人工干预：用户提供 DeepSeek 官方文档入口并要求评估手动与自动方式的差异；Key 未写入本文件、配置或新提交。
- 教训：OpenAI 风格 Base URL 不能机械复制给 Anthropic SDK；自动化与手动启动共享协议，`--bare` 的认证限制才是本次实质差异。最小连通与长 Agent 任务稳定性必须分别验收。

### 2026-08-09T00:55:00+08:00 · P-013 · 冷启动发现 PLAN 依赖顺序缺陷

- Superpowers 技能：`using-superpowers`、`systematic-debugging`、`receiving-code-review`、`writing-plans`；未调用实现技能。
- 关键 prompt/context：Claude 处于 safe mode、无会话持久化，只把 `SPEC.md`、`PLAN.md` 作为权威需求；先只读检查 Task 2/5 前置依赖，禁止写文件、命令和联网。
- 输出：1 美元试跑因预算停止；仅提高到 3 美元后得到 `COLD_START_BLOCKED`。报告指出 Task 1/2/3 产物均不存在，因此不能从基线直接试做 Task 2/5。
- 人工核验：PLAN 依赖图和实际文件均支持该结论；修订 Gate 2 为顺序试做 Task 1 → Task 2，Task 5 等 Task 2/3 合并后正式实现。
- subagent/commit：Claude Code 为课程冷启动陌生智能体，不是 Codex subagent；只读检查无源码修改、无提交、无合并。
- 人工干预：用户回复“继续”，授权延续既定冷启动流程；修订版 PLAN 仍需用户重新批准，批准前不进入写入试做。
- 教训：冷启动样本不能只按功能代表性选择，还必须从 worktree 的真实基线沿依赖图可执行；预算上限也是 Agent 运行门禁的一部分，应与任务上下文规模匹配。

### 2026-08-09T01:05:00+08:00 · P-014 · 用户重新批准冷启动 PLAN

- Superpowers 技能：`using-superpowers`、`executing-plans`、`using-git-worktrees`、`test-driven-development`；开始执行前门禁，尚未宣称 Task 完成。
- 关键 prompt/context：用户明确回复“批准”；陌生 Claude 只依据已批准 SPEC/PLAN，在可舍弃 worktree 按 Task 1 → Task 2 执行 TDD。
- 输出：PLAN Gate 4 标记完成；冷启动分支将快进到本次批准证据后再启动写入型试做。
- 安全边界：只允许 Task 1/2 文件、精确的旧原型删除、uv/pytest/ruff/扫描命令和只读 Git 检查；禁止 commit、merge、联网工具及工作区越界。
- 人工干预：该批准不授权合并冷启动代码，也不解除正式实现阶段的独立 task/PR 流程。

### 2026-08-09T01:20:00+08:00 · P-015 · 写入型冷启动发现 Windows Git 路径解码缺陷

- Superpowers 技能：`using-superpowers`、`executing-plans`、`using-git-worktrees`、`test-driven-development`、`systematic-debugging`；因验证失败停止在 Task 1。
- 关键 prompt/context：Claude 只执行已批准的 Task 1 → Task 2，允许精确删除旧原型和运行 uv/pytest/ruff/扫描，禁止 commit、merge、任意 PowerShell和越界。
- 环境发现：第一次 Write/Edit/Glob/Grep 的 `EPERM` 来自 Codex 外层可写根不包含兄弟 worktree；在同一 Claude 白名单下授权外层访问后恢复，不是 PLAN 或 Claude 文件工具缺陷。
- 产出：Task 1 文件已形成但未完成门禁；10 美元预算停止前未进入 Task 2。人工验证得到包版本测试通过、ruff 通过、凭据扫描测试因中文路径错误解码失败。
- 缺陷核验：`git ls-files` 原始 UTF-8 字节被 `text=True` 按 Windows 默认代码页解码成乱码；实际文件存在且索引正常。PLAN 改用 `git ls-files -z` 和逐路径 UTF-8 严格解码。
- subagent/commit：Claude Code 是冷启动陌生智能体；冷启动分支有未提交 Task 1 变更，main 仅记录文档修订，试做代码不合并。
- 人工干预：Gate 4 因新 PLAN 缺陷重新打开，需用户批准后继续；未自行修改 Claude 产出的测试来绕过门禁。
- 教训：Windows 优先不仅是运行平台声明，任何 subprocess 文本边界都必须明确编码；独立核验必须重跑完整命令，不能因 Claude 已生成文件就推断绿色。

### 2026-08-09T01:30:00+08:00 · P-016 · 用户批准 Windows 路径解码修订

- Superpowers 技能：`using-superpowers`、`executing-plans`、`test-driven-development`；恢复冷启动 Gate 2 前的批准门禁。
- 关键 prompt/context：用户明确回复“批准”；修订只改变 Task 1 测试读取 Git 路径的编码与分隔方式，不改变产品 SPEC 或 Task 接口。
- 输出：PLAN Gate 4 再次标记完成；准备把 `5ac9b97` 及本次批准证据同步到保留未提交 Task 1 产物的冷启动 worktree。
- 安全边界：继续保留不提交、不合并、限定 Task 1/2 文件和命令的约束；Task 1 全绿前不进入 Task 2。

### 2026-08-09T01:45:00+08:00 · P-017 · Task 1/2 独立评审未通过

- Superpowers 技能：`executing-plans`、`test-driven-development`、`verification-before-completion`、`requesting-code-review`、`receiving-code-review`；未进入正式实现。
- 执行结果：陌生 Claude 完成 Task 1/2；主 Codex 独立验证 19/19、ruff 和正常扫描均通过，但独立 reviewer 报告 4 个 Important 安全/契约问题，冷启动 Gate 2 判定不通过。
- 复现证据：非 Git 目录扫描退出 0；嵌套秘密和构造后 Mapping 注入可见；RawDecision/RunResult 不完整构造被接受；READ_FILE 缺 path 被接受。
- 反馈处理：确认 fail-open、递归秘密、深度不可变、动作必填和固定签名问题；仅部分采纳“Action 拒绝所有多余字段”，继续把 JSON 未知字段职责留给 Task 9 Parser。
- PLAN 修订：增加错误路径与嵌套负例，规定递归冻结和循环拒绝，恢复固定构造签名，限定五个 Protocol，补 README 根链接；Gate 4 重新打开。
- subagent：`/root/cold_start_review` 只读评审完成，无文件修改；冷启动 Claude 产物仍未提交或合并。
- 教训：正常路径全绿不能证明安全门禁 fail-closed；计划中的固定签名若没有负例，陌生实现者会用“方便测试”的默认值悄悄改变公共契约。
- reviewer 二次只读复核确认职责划分合理，并要求测试与文字完全一致；已补精确错误码/固定摘要、完整 Action 必填负例、非字符串键/不支持对象代表负例及 Task 12 JSON 序列化边界。

### 2026-08-09 · P-018 · 重启恢复与集中 PLAN 修订批准

- Superpowers 技能：`using-superpowers`、`using-git-worktrees`、`systematic-debugging`；按既有冷启动流程恢复现场并验证条件。
- 关键 prompt/context：用户要求电脑重启后先检查 Git、worktree 和未完成任务；若无影响，即视为批准集中修订后的 `PLAN.md`。
- 恢复证据：`main=e09cb62`，`cold-start/claude-spec-plan=b04511a`；冷启动未提交文件清单与重启前一致；两处均无 Git 索引锁；无遗留 Claude/uv/Python 任务。
- 验证输出：冷启动现状全量 pytest 为 `19 passed`，ruff 为 `All checks passed!`，正常路径凭据扫描退出 `0`。
- 人工干预：恢复条件满足，用户的条件式批准正式生效；PLAN Gate 4 标记完成。批准不改变 Gate 2 未通过的结论，也不授权提交或合并试做代码。
- 下一步：把批准证据同步到保留现场，在同一可舍弃 worktree 按新版测试执行 RED—GREEN 修复，再做独立复审。

### 2026-08-09 · P-019 · 冷启动 Gate 2 通过

- Superpowers 技能：`executing-plans`、`test-driven-development`、`systematic-debugging`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`；完成冷启动修复、复现、重做 TDD 和独立复审。
- Claude 第一轮结果：新增安全契约后从 19 项扩展到 37 项；主 Codex独立复验 pytest、ruff、正常扫描和非 Git 扫描均符合当时测试。
- reviewer 第一轮结果：0 Critical、3 Important，分别为 Git executable 启动失败、空 payload 冻结绕过、其余 tuple/frozenset 字段未规范化；主 Codex逐项复现并判定为 PLAN 已有要求的实现偏离。
- TDD 过程纠偏：第二次 Claude 在测试工具审批前写入生产修复，不能形成 RED 证据；保留新增测试、撤回该轮生产修改后，独立观察 1 个扫描失败和 11 个模型失败，再重新实现 GREEN。
- 最终验证：`50 passed`、无 pytest warning、ruff 全绿；正常扫描退出 `0`；Git 真缺失时退出 `2`、stdout 空、stderr 固定。第三次 reviewer 报告 0 Critical、0 Important、0 Minor，Ready to proceed: Yes。
- subagent/commit：`/root/cold_start_rereview` 仅做两轮只读复审，无文件修改；Claude 与主 Codex的冷启动试做保持未提交、未合并。正式过程文档 commit 在本轮完成。
- 清理结果：确认临时分支无独有 commit 后，按 PLAN 删除 `D:\Codes\FBW-worktrees\cold-start-claude` 和 `cold-start/claude-spec-plan`；未提交试做代码不可从 commit 恢复，正式过程证据保留在 `main`。
- 人工判断：Gate 2 标记完成。正式 Task 1 仍受“缺少 NJU Git/GitHub remote URL”门禁阻挡。

### 2026-08-09 · P-020 · 正式 Task 1 实现与独立评审修复

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`；另有独立 reviewer 只读审查。
- worktree：`.worktrees` 路径偏差已纠正为 PLAN 指定的 sibling worktree `D:\Codes\FBW-worktrees\task-01`；在独立 `task/01-package-skeleton` 分支执行。
- RED/GREEN 证据：先观察到未声明 pytest，继而观察到包缺失、旧原型命中与扫描器缺失；扫描器额外覆盖 Git 不可用、Git executable 不在 PATH、原生命令错误处理开启，以及真实临时 Git 仓库命中分支。命中分支临时破坏后，测试按预期因错误退出码和错误输出失败；撤回破坏后恢复绿色。
- 验证：定向 smoke 与全量 pytest 均为 `6 passed`；Ruff、正常当前树扫描和 `git diff --check` 通过。
- 提交：实现 `c5ed568 chore: 建立安全项目骨架`；review-fix `1c8c001 test: 覆盖秘密扫描命中分支`。
- 评审：1 个 Important（真实临时 Git 仓库命中分支缺覆盖）已在 fix round 1 修复；命名 Minor 延后处理。未记录凭据内容。

## 3. 当前关键决定

| 决定 | 来源/责任 | 状态 |
|---|---|---|
| Python + uv，Windows 优先，首版纯 CLI | 用户选择 | 已写入 SPEC |
| CLI 仅为适配器，核心允许未来接 WebUI | 用户要求、AI 细化 | 已写入 SPEC |
| 模块化同步单进程状态机 | AI 推荐、用户采纳 | 已写入 SPEC |
| 反馈闭环为重点，pytest 为主信号 | 共同收敛 | 已写入 SPEC |
| 真实 CLI + Mock LLM 共用内核 | AI 修正、用户采纳 | 已写入 SPEC |
| 普通受控操作自动，仅高风险审批 | 用户选择 | 已写入 SPEC |
| 禁止任意 PowerShell、删除、越界 | 用户要求 | 已写入 SPEC |
| 直接修改、逐文件事务和失败回滚 | 用户选择、共同细化 | 已写入 SPEC |
| Credential Manager 存储 Key | AI 依据课程要求推荐 | 待用户随 SPEC 审阅 |
| 现有历史留在 `main`；编码阶段 branch + worktree + PR | 用户决定 | 此前流程偏离已解决 |
| 首版不实现 WebUI，但保留入口扩展边界 | 用户决定 | 仍与课程最终清单冲突 |
| 不自行重写含 Key 的 Git 历史 | 用户接受当前风险 | 仅在公开发布/正式提交时阻断 |

## 4. Superpowers 技能使用状态

| 技能 | 使用情况 | 证据/说明 |
|---|---|---|
| `using-superpowers` | 已使用 | 会话开始和正式定位修订时核对技能流程 |
| `brainstorming` | 已使用 | P-001 至 P-009，产出设计依据并迭代正式 SPEC |
| `receiving-code-review` | 已使用 | P-009，核对并落实用户第一轮 SPEC 审阅 |
| `writing-plans` | 已使用 | P-010，依据已批准 SPEC 生成正式 PLAN |
| `using-git-worktrees` | 已使用 | P-011，创建可舍弃的 Claude 冷启动 worktree；正式实现 worktree 尚未创建 |
| `subagent-driven-development` / `executing-plans` | 已部分使用 | `executing-plans` 已用于冷启动 Gate 2；正式 task 尚未开始 |
| `test-driven-development` | 已使用 | 冷启动 Task 1/2 建立并纠正 RED—GREEN 证据 |
| `requesting-code-review` | 已使用 | 冷启动 Task 1/2 经独立 reviewer 多轮复审至零问题 |
| `finishing-a-development-branch` | 未使用 | 尚未进入收尾 |

## 5. 已知偏离与待解决冲突

### D-01 · WebUI

- 课程要求：最终提供可访问 WebUI。
- 当前决定：首版纯 CLI；CLIAdapter 与核心解耦，未来可增加 WebUIAdapter。
- 处理：不创建无行为占位代码；如实记录“可扩展”仍不等于已交付 WebUI，后续需用户或课程方作最终裁决。

### D-02 · 凭据已进入历史

- 课程要求：源码、日志、配置和 Git 历史均不得含 Key。
- 当前事实：`77da924` 已包含学校临时 Key。
- 处理：用户接受当前私有开发风险，不在新文档重复 Key，也不重写现有历史；公开发布/正式提交时凭据扫描仍会失败，届时如实报告而不绕过门禁。

### D-03 · 分支、worktree 与 PR

- 课程要求：按 worktree/subagent/PR 流程保留过程证据。
- 当前决定：现有文档历史保留在 `main`；正式编码开始采用 branch + worktree + PR。
- 处理：此前偏离已解决；待 SPEC、PLAN 和冷启动门禁完成后，由 `using-git-worktrees` 创建首个实现 worktree。

### D-04 · 探索定位

- 早期上下文：称为随时可舍弃的探索 demo。
- 当前决定：按正式课程流程完成可运行成品。
- 处理：后者覆盖交付范围；前者作为需求演化证据保留。

## 6. 提交索引

| Commit | 内容 | 过程含义 |
|---|---|---|
| `77da924 init` | 初始文件与旧原型 | 建立基线，同时引入凭据历史冲突 |
| `b773647 docs: 添加 Coding Agent Harness demo 设计` | brainstorming 设计依据 | 不是正式 SPEC |
| `b5f3d72 docs: 补齐正式课程规约与过程记录` | 正式 SPEC 与过程记录初版 | 进入用户书面审阅门禁 |
| `2286e3c docs: 修订 CLI 扩展边界与开发流程` | 第一轮 SPEC 审阅修订 | 进入最终批准门禁 |

后续正式文档提交完成后，应在本表新增其 commit；实现阶段每个 PLAN task 还需记录 task、技能、subagent、人工修改和验证证据。
