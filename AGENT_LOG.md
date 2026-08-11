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
- 分支已推送；PR：[PR #1](https://github.com/01w-01/SE-agent/pull/1)。

### 2026-08-09 · P-021 · 正式 Task 2 核心契约实现与两轮修复

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-02`；分支 `task/02-core-contracts`，基线 `bf8b053`。Task brief 抽取遗漏 §1 端口签名和部分固定字段后，控制器从已批准 SPEC/PLAN 与冷启动证据生成忽略的补充契约，再恢复同一 Task，没有扩大产品范围。
- RED/GREEN：首次 RED 为缺少 `fbw_harness.errors`；实现后补充 `SessionState.touched_files` 规范化 RED。首轮 review 指出 Action 把“非空”误作“非空白”；修复后复审又发现非字符串类型被放过，均先写精确失败测试再最小修复。
- 提交：`901533a feat: 定义 Harness 核心契约`、`3f75989 fix: 修正 Action 非空校验`、`37e28ee fix: 收紧 Action 字段类型校验`。
- 最终验证：模型测试 `59 passed`、全量 `65 passed`、Ruff、累计 `git diff --check` 均通过；独立 reviewer 最终为 0 Critical、0 Important、0 Minor，`APPROVED`。
- 安全与边界：只修改 Task 2 四个白名单文件；没有真实 I/O、CLI、Workspace、Parser、Policy 或 `ApplicationService` 提前实现；凭据内容未写入源码、报告或新提交。
- 分支已推送；PR：[PR #2](https://github.com/01w-01/SE-agent/pull/2)。

### 2026-08-09 · P-022 · 正式 Task 3 声明式安全配置

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-03`；分支 `task/03-config-entry`，基线 `251d0ad`。基线全量测试为 `65 passed`。
- RED/GREEN：首次 RED 为缺少 `fbw_harness.config`；实现配置优先级、白名单、类型/正整数和 pytest 参数校验后定向 `19 passed`。独立 review 指出非 UTF-8 异常、文件错误字段标识和 pytest `@argfile` 绕过三项 Important；控制器验证 pytest 8.4.2 的 `fromfile_prefix_chars='@'` 后进入 fix round 1。
- 修复：新增 9 个真实边界测试，先观察 `19 passed, 9 failed`，再统一安全错误并拒绝 `@argfile`；提交 `a9a3586 fix: 收紧配置文件与 pytest 参数边界`。原实现提交为 `81e6c58 feat: 添加声明式安全配置`。
- 最终验证：配置测试 `28 passed`、全量 `93 passed`、Ruff 和累计 `git diff --check` 通过；scoped re-review 判定三项全部 ADDRESSED，0 新 Critical / Important / Minor。
- 安全与边界：只修改 Task 3 两个白名单文件；错误不含配置值、路径或底层解析文本；没有 shell、CLI 终端依赖或秘密字段进入配置。
- 分支已推送；PR：[PR #3](https://github.com/01w-01/SE-agent/pull/3)。

### 2026-08-09 · P-023 · 正式 Task 4 Windows 凭据生命周期

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-04`；分支 `task/04-credentials`，基线 `db1b958`，基线测试 `93 passed`。
- 实现：Fake keyring TDD 覆盖 set/get/status/clear、空白 Key、默认 service/account、后端错误脱敏和 manual marker 隔离；提交 `4e7fdc0 feat: 添加安全凭据存储`。
- review：发现异常 `__context__` 仍可泄漏 Key（Critical）和所有 `PasswordDeleteError` 被误当不存在（Important）。fix round 1 先用递归异常图与删除权限失败测试观察 RED，再在 except 块外映射固定错误、删除失败后重新确认凭据状态；提交 `1ec3d3f fix: 消除凭据异常链泄漏`。
- 最终验证：凭据 `9 passed`、全量 `102 passed`、Ruff 和累计 diff check 通过；scoped re-review 两项全部 ADDRESSED，无新 Critical / Important。
- deferred Minor：`status()` 后端失败没有独立直接测试；其实现当前复用 `get()`，留待最终整分支审查统一裁决。
- 安全边界：自动测试仅使用 Fake backend，未访问真实 Credential Manager；异常图、消息和 traceback 均不保留 Key 或 backend 原文。
- 分支已推送；PR：[PR #4](https://github.com/01w-01/SE-agent/pull/4)。

### 2026-08-09 · P-024 · 正式 Task 5 路径式工作区围栏

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`writing-plans`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-05`；分支 `task/05-workspace-fence`，基线 `a71fa61`，基线测试 `102 passed`。
- 首版：实现路径规范化、commonpath、重解析点、保护段、有界 UTF-8 读取和 SHA-256，提交 `d69365d feat: 添加工作区安全围栏`；定向 `24 passed`、全量 `126 passed`。
- review：有效审查报告指出路径式 stat/open 与 scandir 的残余竞态、检查顺序/root 链、保护范围和发现上限问题；首次 reviewer 请求被平台误判后以本地文件 API 正确性描述重试，没有修改代码。
- 用户裁决：在 PLAN 与 Windows 原生句柄级建议冲突时选择 B，保留路径式围栏；SPEC 新增 R-09，明确不把应用层围栏描述为抵御同用户恶意并发替换的操作系统沙箱。
- fix round 1：按 TDD 增加完整链检查、scandir 前复查、保护集合、1,000 返回/10,000 扫描上限、path/opened/post 状态比较和异常链脱敏；提交 `830a2a7 fix: 补强路径式工作区围栏`。
- 最终验证：工作区 `62 passed`、全量 `164 passed`、Ruff、format、累计 diff check 通过；scoped re-review 全部 ADDRESSED，无新 Critical / Important。
- 安全边界：不引入原生句柄遍历或新依赖；残余 TOCTOU 是已知限制，不作为已解决风险宣传。
- 分支已推送；PR：[PR #5](https://github.com/01w-01/SE-agent/pull/5)。

### 2026-08-10 · P-025 · 正式 Task 6 路径式文件事务与回滚

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-06`；分支 `task/06-transactions`，基线 `e161def`，基线测试 `164 passed`。
- 首版：实现首次快照、同目录临时文件、flush/fsync/replace、并发哈希、commit 与逆序/部分回滚；提交 `c67d2ac feat: 添加文件事务与回滚`。
- controller review：复现最终校验到 replace/unlink 的跨进程竞态（与路径式 PLAN 冲突），并发现恢复材料未验 hash、commit 部分清理后仍可写、目录 fsync 和运行期 reparse/身份复验缺口。
- 用户裁决：选择 B，不实现平台 CAS/句柄事务；SPEC 新增 R-10，明确保留极窄跨进程 TOCTOU，不将其描述为已解决。
- fix round 1：TDD 补恢复材料/结果双重 hash、commit-started 终态、平台目录 fsync、恢复目录链/身份复验和 dangling symlink 目录项检查；提交 `b4d7c1a fix: 补强路径式文件事务`。
- 最终验证：事务 `49 passed`、全量 `213 passed`、Ruff、定向 format、累计 diff check 通过；controller scoped re-review 为 ALL_ADDRESSED。
- 安全边界：只操作注入的 Workspace 与显式 recovery_root；不实现或宣称操作系统级跨进程条件更新。
- 分支已推送；PR：[PR #6](https://github.com/01w-01/SE-agent/pull/6)。

### 2026-08-10 · P-026 · 正式 Task 7 治理、风险分级和 HITL

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-07`；分支 `task/07-policy-hitl`，基线 `41d5095`，基线测试 `213 passed`。
- 实现：稳定 DENY/CONFIRM/ALLOW 规则、风险事实和 ApprovalProvider 边界；提交 `fc9e8d7 feat: 添加治理与人工审批`。
- review：发现无 Workspace 时 Windows 路径 fail-open、脏路径大小写、manifest/build 覆盖、capability 泄漏和风险事实丢失；fix round 1 通过 18 个预期 RED 后修复，提交 `309cc15 fix: 收紧治理规则边界`。
- 最终验证：策略 `51 passed`、全量 `264 passed`、Ruff、format、累计 diff check 通过；scoped re-review ALL_ADDRESSED。
- 依赖记录：Task 7 不存在真实 ToolDispatcher；DENY 不触达真实工具层的集成证明已写入 SDD ledger，必须由 Task 11 完成。
- 分支已推送；PR：[PR #7](https://github.com/01w-01/SE-agent/pull/7)。

### 2026-08-10 · P-027 · 正式 Task 8 pytest 与结构化反馈闭环

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`systematic-debugging`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-08`；分支 `task/08-pytest-feedback`，基线 `920e9d9`，基线测试 `264 passed`。
- 首版：固定 `sys.executable -m pytest`、cwd/shell 边界、Windows 进程树终止、分类/摘要/指纹与脱敏，提交 `45800ad feat: 添加测试反馈闭环基础`。
- 五轮 review fix：依次补 node-id/赋值/异常/有界双流/taskkill、早期诊断、先脱敏后截断、Authorization/quoted mapping/required secrets、映射 quote 与深度上限；追加 `842ee04`、`9b47845`、`97a42f9`、`4788d56`、`b4e4d65`。达到 5/5 后 reviewer 仍复现 quoted 内容绕过，按 SDD 上限停止叠补丁并升级架构修订。
- 架构修订：删除旧混合状态机，拆成 `mapping -> global -> sk-token -> known-secret` 两层流式脱敏；RED `45 failed / 5 passed`，提交 `f60bb4c fix: 重构测试输出流式脱敏`。
- 架构 fix round 1：补 standalone quoted field fragment，并把 known secrets 明确收窄为非空 ASCII tuple、三入口固定验证；追加 `247135a fix: 收紧测试反馈秘密契约`。
- 最终 review：116 类 quoted fragment 与 3,504 个 chunk 组合、mapping fuzz、known secret overlap/adjacent、63/64/65/10,000 深度均通过；Critical 0 / Important 0 / Minor 0，结论 APPROVED。
- 最终验证：Task 8 `234 passed, 1 skipped`、全量 `498 passed, 1 skipped`、Ruff、format、当前树秘密扫描和累计 diff check 全部通过；唯一 skip 为 Windows 不适用的 POSIX killpg 分支。
- 安全边界：输出在进入有界 tail 前脱敏；mapping 栈最多 64；TestRunner 的 `known_secrets` 是 required keyword-only，Task 11 必须把同一 tuple 同时传给 TestRunner 与 FeedbackEngine，并补集成测试。
- 分支已推送；PR：[PR #8](https://github.com/01w-01/SE-agent/pull/8)。

### 2026-08-10 · P-028 · 正式 Task 9 LLM 决策、解析与上下文

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`systematic-debugging`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-09`；分支 `task/09-llm-context`，基线 `d54ed9e`，基线测试 `498 passed, 1 skipped`。
- 首版：实现严格 ActionParser、每次新建的固定工具 schema、OpenAI compatible 单次决策/瞬时重试、ScriptedMockLLM 深拷贝记录和预算 ContextBuilder；提交 `419c762 feat: 添加 LLM 决策与上下文构建`。
- review fix round 1：修复测试秘密字面量、惰性 status/call/context 属性固定映射、Context 先限界再脱敏、100/100/100 数量和 path/hash 上限、最旧项完整淘汰与 schema 防污染；提交 `5d513d0 fix: 加固 LLM 与上下文边界`。
- review fix round 2：为 SDK 与 custom/mock 决策统一增加 16 calls、64 name、4 MiB arguments、16,000 content 硬上限；提交 `53f29a8 fix: 限制 LLM 决策输出规模`。
- review fix round 3：拒绝伪装 `__len__` 的 list/tuple/str 子类，在 len/iter/index/slice/encode 前 exact type fail-closed；提交 `80ca933 fix: 拒绝伪装的 LLM 响应类型`。
- 最终 review：普通 SDK list/tuple、伪装容器/字符串、lazy function/name、16/17 calls、64/65 name、4 MiB/+1 arguments 和 content 截断均通过；Critical 0 / Important 0，ALL_ADDRESSED。
- 最终验证：Task 9 `113 passed`、全量 `611 passed, 1 skipped`、Ruff、format、当前树秘密扫描和累计 diff check 全部通过；唯一 skip 延续为 Windows 不适用的 POSIX killpg 分支。
- 分支已推送；PR：[PR #9](https://github.com/01w-01/SE-agent/pull/9)。

### 2026-08-11 · P-029 · 正式 Task 10 可选白名单项目记忆

- 用户授权：知晓现有 Git 历史包含临时 API Key，仍明确授权推送到指定 GitHub 仓库并继续 PR；不改写历史，课程凭据冲突仍保留。
- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`systematic-debugging`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-10`；分支 `task/10-project-memory`，基线 `0058ca8`，基线测试 `611 passed, 1 skipped`。
- 首版：默认关闭的 `JsonProjectMemoryStore`、四字段 schema、2,000 字符上限、损坏隔离、同目录原子写与 clear，提交 `c1befd5 feat: 添加受控项目记忆`。
- task review fix round 1：按既有路径式方案 B 补静态目标/父目录 symlink 与 Windows junction、固定损坏提示、严格 UTC；提交 `de99cac fix: 加固项目记忆边界`。同用户恶意并发替换作为 SPEC R-11 残余风险，不升级为句柄引擎。
- task review fix round 2：保证 `RuntimeWarning` 被配置为 error 时仍返回无记忆运行；提交 `44c8f12 fix: 防止项目记忆警告阻断回退`。
- 最终累计 review fix：修复 quoted JSON/TOML/env 秘密字段绕过、超限/不可读/隔离失败状态误覆盖和 NUL 路径异常；提交 `5eeb08a fix: 收紧项目记忆安全边界`。
- 最终 review：三项累计 finding 全部 ADDRESSED，无新 Critical / Important；结论 Ready to merge。
- 控制器最终验证：Task 10 `32 passed`、全量 `643 passed, 1 skipped`、Ruff、format、当前树秘密扫描和累计 diff check 全部通过；唯一 skip 延续为 Windows 不适用的 POSIX killpg 分支。
- Task 11 继承：仅成功 RunResult 调用 `save_success()`；仅 enabled 且 `load()` 成功才注入 ContextBuilder；路径式 R-11 与固定安全提示必须保持。
- 分支已推送；PR：[PR #10](https://github.com/01w-01/SE-agent/pull/10)。

### 2026-08-11 · P-030 · 正式 Task 11 Agent 主循环与威胁边界裁决

- Superpowers 技能：`subagent-driven-development`、`test-driven-development`、`receiving-code-review`、`requesting-code-review`、`verification-before-completion`、`finishing-a-development-branch`。
- worktree：`D:\Codes\FBW-worktrees\task-11`；分支 `task/11-agent-loop`，基线 `5f8799a`。
- 实现提交：`e102edc feat: 实现 Agent 主循环`、`de4c48e fix: 修正 Agent 循环审查问题`、`c654dc6 fix: 收紧 Agent 循环安全边界`；覆盖 ToolDispatcher、显式状态机、真实 pytest 反馈闭环、治理/HITL、事务终态、ApplicationService、记忆与凭据注入。
- 用户裁决：有限 `_CAPABILITY_TOKENS` 只作常见模式的 best-effort `CONFIRM` 提示；它不是安全边界，不要求覆盖未列 API、字符串拼接或纯内置函数，也不继续扩表或重构。安全边界固定为工作区路径围栏、动作级策略/HITL、逐文件事务与回滚；工作区 pytest 代码执行列为 SPEC R-12 已知限制。
- 小范围 TDD 收口：先以提交/完整回滚两个终态复现恢复目录 `rmdir()` 的 `KeyboardInterrupt` 逸出，再由清理边界吞掉 `BaseException`，确保磁盘终态已确定后仍返回原 `RunResult`；提交 `4cd4cb4 fix: 保证终态清理不改变运行结果`。
- Task 12–14 reviewer 指令：按上述威胁模型审查；代码执行不在边界内，denylist 不要求完备；Critical 仅限数据丢失、回滚失败、凭据泄漏、越界写入，其余不阻断 PR；每个 task 最多一轮修复且不做第二轮复审。
- 最终门禁：Task 11 相关定向 `227 passed`、全量 `729 passed, 1 skipped`、Ruff、8 文件 format、当前树秘密扫描和累计 diff check 全部通过。
- 分支已推送；PR：[PR #11](https://github.com/01w-01/SE-agent/pull/11)。

### 2026-08-11 · P-031 · 正式 Task 12 CLI 与三项 Mock 机制演示

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`requesting-code-review`、`receiving-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-12`；分支 `task/12-cli-demos`，基线 `4447261`，基线全量 `729 passed, 1 skipped`。
- 首版提交：`473b32a feat: 添加 CLI 与机制演示`；提供 `run`、`credential`、`memory clear`、`demo` 子命令、Console/JSONL 事件边界、隐藏凭据输入、临时目录机制演示和 PowerShell 一键脚本。
- 唯一 task review：0 Critical；代码质量与安全 APPROVED；两项 Important/TODO 指出 guardrail 指标原为推算，以及组合根测试未观察真实 factory/loop 构造。两项均属于 brief 可观察行为，不涉及 SPEC R-12 的代码执行非目标。
- 唯一 fix round 1/1：先复现 ALLOW 策略下 dispatcher 调用两次而旧 demo 仍 PASS，再让结果来自真实 PolicyDecision/RunEvent/dispatcher 记录；同时实际运行 CLI 与 demo 组合根，证明同一 ApplicationService/AgentLoop、不同真实/Mock factory；提交 `4ab5134 fix: 强化演示机制验证`。按用户裁决不做第二轮复审。
- 控制器最终门禁：Task 12 定向 `11 passed`、全量 `743 passed, 1 skipped`；CLI help、`demo all`、`scripts/demo.ps1`、Ruff、本任务 format、正式当前树秘密扫描和累计 diff check 全部通过。
- 已知非阻断状态：全树 format 仍有 Task 12 白名单外的既有漂移，未跨任务修改；唯一 pytest skip 仍为 Windows 不适用的 POSIX killpg 分支。
- 分支已推送；PR：[PR #12](https://github.com/01w-01/SE-agent/pull/12)。
- 合并后 Windows 主 worktree 复验稳定失败：CRLF fixture 被 `read_text()` 规范化为 LF，expected SHA 与 FileTransaction 的磁盘字节哈希不一致。经 systematic-debugging 追踪到两个 `EditConflictError`，以显式 CRLF TDD 回归最小修复；提交 `e9b1cd9 fix: 保留演示 fixture 的 CRLF 换行`，控制器复验机制 `7 passed`、全量 `744 passed, 1 skipped` 及静态门禁通过。该集成 hotfix 不属于第二轮 reviewer/fix loop；补充 PR：[PR #13](https://github.com/01w-01/SE-agent/pull/13)。

### 2026-08-11 · P-032 · 正式 Task 13 README、CI 与 Windows 单文件分发

- Superpowers 技能：`using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`systematic-debugging`、`requesting-code-review`、`receiving-code-review`、`verification-before-completion`。
- worktree：`D:\Codes\FBW-worktrees\task-13`；分支 `task/13-distribution`，基线 `fdf0830`，基线全量 `744 passed, 1 skipped`。
- 首版提交 `852db5e build: 添加 CI 与 Windows 分发`：根/包 README、GitLab unit-test、GitHub Windows/tag workflow、PyInstaller spec、staging build、当前/历史秘密扫描和分发合同测试。
- 冻结边界实测：依次以真实 exe RED 定位包入口相对导入、fixture 未携带、冻结 `sys.executable -m pytest` 三个根因；在 spec/workpath 入口与数据/pytest 收集中最小修复，使单文件 `--help` 和 `demo all` 无需系统 Python、网络或 Key。
- 唯一 task review：规格 PASS、质量/安全 APPROVED、0 Critical；报告 staging cleanup 失败后最终产物残留、合同测试偏弱和 README cwd 三项。
- 唯一 fix round 1/1：受控复现 cleanup 非零但 exe 留存，统一失败清理最终 exe/SHA；补 spec、workflow、历史输出严格合同并修 README；提交 `84d4527 fix: 收紧分发构建清理门禁`，按用户裁决不做第二轮复审。
- 控制器最终门禁：定向 `6 passed`、完整 build 内全量 `750 passed, 1 skipped`、Ruff、format、当前树扫描、exe help/demo、SHA 与累计 diff 全部通过。
- 历史扫描按用户已接受的临时 Key 风险真实退出 `1`，只输出 SHA 与路径；tag/Release 继续被阻断，没有改写历史或弱化门禁。
- 分支已推送；PR：[PR #14](https://github.com/01w-01/SE-agent/pull/14)。

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
