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
| `subagent-driven-development` / `executing-plans` | 未使用 | PLAN 已生成，但实现仍被冷启动门禁阻挡 |
| `test-driven-development` | 未使用 | 实现尚未开始 |
| `requesting-code-review` | 未使用 | 尚无实现 task 可评审 |
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
