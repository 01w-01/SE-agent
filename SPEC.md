# FBW Coding Agent Harness 正式规格说明

> 课程：AI4SE 期末项目 A · Coding Agent Harness
>
> 版本：1.0-draft
>
> 日期：2026-08-08
>
> 状态：等待用户审阅；批准前禁止生成 `PLAN.md` 或编写实现代码

## 1. 文档依据与约束优先级

本规格由以下材料共同沉淀：

1. `通用要求.md`；
2. `AI4SE_Final_Project_A_Coding_Agent_Harness.md`；
3. `docs/superpowers/specs/2026-08-08-coding-agent-harness-demo-design.md`；
4. `docs/STATUS.md`、`docs/LOG.md`、`docs/PROGRESS.ascii.md`；
5. 当前 brainstorming 全部对话与用户明确决定。

课程硬性要求优先；用户明确决定如与课程要求冲突，不静默覆盖，而是在 §20 记录为冲突、风险或有意偏离。现有 brainstorming 设计是本规格的设计依据，不能代替本文件。

## 2. 问题陈述

### 2.1 要解决的问题

单次 LLM 调用只能生成下一步建议，不能天然保证它能安全地读取项目、修改代码、验证结果、在失败后修正并可靠停止。直接让模型执行任意命令还可能越过工作区、破坏文件或把“自认为完成”误当成客观完成。

FBW 要把 OpenAI 兼容 LLM 封装成一个 Windows 优先的 Coding Agent Harness：它自行实现上下文组织、动作解析、有限工具、路径与权限护栏、文件事务、pytest 反馈、记忆、配置和显式状态机，用确定性代码约束模型的不确定性。

### 2.2 目标用户

- 需要在 Windows 上用 CLI 完成小型 Python 代码修复的学生或个人开发者；
- 希望理解 agent loop、反馈闭环、治理与 Mock LLM 测试的 AI4SE 学习者；
- 需要研究“移除真实 LLM 后还剩多少可验证工程”的课程评审者。

### 2.3 项目价值

- 用户得到一个可连接真实 API、能读写代码并自动测试的可运行产品，而不是仅展示提示词的玩具；
- 课程得到可离线复现的机制证据：护栏拦截、失败回灌、自我修正、无进展停机与回滚；
- 工程重点落在 harness 而不是模型能力，能够客观评审治理、反馈、上下文和安全设计；
- 模块化单进程架构便于初学者阅读，也便于 TDD、Mock 注入和后续扩展。

## 3. 目标与非目标

### 3.1 产品目标

1. 提供可安装、可运行的纯 CLI Coding Agent Harness；
2. 支持 OpenAI Chat Completions 兼容 API，默认测试模型为 `deepseek-v4-flash`；
3. 在用户指定的 Python 项目中按需读取、创建和精确修改普通文本文件；
4. 每次代码写入后由 harness 强制运行 pytest，并将结果结构化回灌；
5. 普通受控操作自动执行，仅高风险操作需要 HITL 审批，禁止项直接拒绝；
6. 直接修改原项目，但通过逐文件事务、哈希校验、原子写入和失败回滚保护文件；
7. 六个 harness 维度均有最低可运行实现，反馈闭环作为重点维度深入实现；
8. 核心机制在 Mock LLM 下离线、确定、可一键测试；
9. 使用 Windows Credential Manager 安全存储 API Key；
10. 为 Windows 10/11 x64 提供可下载的原生可执行产物和完整 README。

### 3.2 非目标

- 不使用 LangChain AgentExecutor、AutoGen、CrewAI、LlamaIndex agent 或宿主编码智能体 runner；
- 不向模型开放任意 PowerShell、任意 shell、删除、移动或重命名工具；
- 首版不支持 Python/pytest 之外的语言和测试框架；
- 不实现多 Agent 编排、事件总线、插件平台或服务端数据库；
- 不声称静态扫描和路径围栏等同于操作系统级沙箱；
- 用户明确决定不提供 WebUI，相关课程冲突见 §20；
- 不在本规格批准前生成 PLAN 或实现代码。

## 4. 用户故事

以下故事彼此可独立交付和验证，保持小而有价值，并带有明确验收结果。

### US-01 安全配置凭据

作为首次使用者，我希望通过隐藏输入把 API Key 保存到 Windows Credential Manager，并能查看状态、更新和清除，以便使用真实 LLM 而不把 Key 写入源码、配置、日志或命令历史。

### US-02 启动真实编码任务

作为 Python 开发者，我希望指定项目目录、任务、Base URL 和模型启动 CLI，以便 Agent 在明确工作区内分析并修复代码。

### US-03 观察反馈闭环

作为使用者，我希望看到每轮动作摘要、策略结果和 pytest 摘要，以便理解 Agent 为什么继续、成功或停止，同时不暴露 API Key 和完整敏感上下文。

### US-04 保护工作区边界

作为谨慎的用户，我希望工作区外路径、`.git`、凭据文件、链接和破坏性操作在工具执行前被拒绝，以免模型影响无关文件。

### US-05 审批高风险修改

作为项目所有者，我希望普通小范围源码修改自动执行，而依赖、CI、已有脏文件、大范围或危险能力修改暂停并显示风险原因，以便在效率和控制之间取得平衡。

### US-06 从失败中自动修正

作为开发者，我希望 harness 在写入后自动运行 pytest，把失败分类并回灌，让 Agent 基于客观反馈修改下一步，而不是只靠模型自我检查。

### US-07 失败后恢复

作为项目所有者，我希望任务失败、无进展、异常或中断时恢复到任务开始前，以免留下半完成或测试失败的修改。

### US-08 离线验证机制

作为课程评审者，我希望在没有网络和真实 Key 时运行 Mock LLM 机制演示，以便确定性验证主循环、护栏、反馈、停机和回滚确实由代码实现。

### US-09 跨会话复用项目事实

作为重复使用者，我希望只在显式启用时保存少量项目说明和成功运行摘要，以便后续任务按需利用项目知识，而不保存完整对话、文件全文或凭据。

### US-10 获取并运行发行版

作为一台全新 Windows 机器上的用户，我希望从 GitHub Release 下载校验过的 x64 可执行文件，按 README 配置凭据并运行，以便无需预装 Python 开始使用。

### 4.1 INVEST 自检与验收映射

每个故事都能按单一用户价值独立讨论和验收；必要的技术依赖不改变其独立业务目标。故事范围限定在一个可测试能力，具体实现仍可在 PLAN 阶段协商。

| 故事 | I / N（独立、可协商） | V / E / S（有价值、可估算、足够小） | T（主要验收标准） |
|---|---|---|---|
| US-01 | 凭据生命周期可独立交付；存储后端细节可协商 | 单一安全能力，边界明确 | AC-02、AC-15 |
| US-02 | 任务入口独立于具体修复策略；参数形式可协商 | 提供真实任务价值，范围为一次运行 | AC-03、AC-06 |
| US-03 | 展示层可独立于执行模块；输出样式可协商 | 可观察一次运行，字段可估算 | AC-09、AC-15 |
| US-04 | 策略拒绝可独立测试；规则阈值可协商 | 直接保护工作区，规则集合有限 | AC-05、AC-07 |
| US-05 | 审批机制可独立于拒绝规则；风险阈值可协商 | 平衡效率与控制，审批路径有限 | AC-08 |
| US-06 | 反馈闭环可用 Mock 独立验证；分类细节可协商 | 核心项目价值，限定 pytest 反馈 | AC-09、AC-10、AC-11 |
| US-07 | 事务恢复可独立注入失败测试；恢复材料形式可协商 | 避免半成品，限定本次触碰文件 | AC-12、AC-13 |
| US-08 | 演示不依赖真实 API；场景数据可协商 | 直接服务课程评审，仅三项场景 | AC-04、AC-18 |
| US-09 | 默认关闭且独立于单次运行；摘要格式可协商 | 提供有限复用价值，字段白名单很小 | AC-14、AC-15 |
| US-10 | 发行物可独立于源码安装验证；压缩格式可协商 | 降低使用门槛，限定 Windows x64 | AC-01、AC-21、AC-22 |

## 5. 系统架构

### 5.1 架构风格

采用模块化、同步、单进程状态机。所有模型决策通过统一 LLM 抽象进入同一 AgentLoop；真实客户端和 Mock 客户端不得各自实现不同循环。

```text
用户
 |
 v
CLI / Config / CredentialStore
 |
 v
AgentLoop / SessionState
 |
 +---- ContextBuilder ---- 任务 / 工具协议 / 观察 / 反馈 / 记忆
 +---- LLMClient --------- OpenAICompatibleClient / MockLLMClient
 +---- ActionParser ------ 模型工具调用 -> Action
 +---- PolicyEngine ------ ALLOW / CONFIRM / DENY
 +---- ToolDispatcher ---- 列出 / 读取 / 创建 / 精确替换
 +---- FileTransaction --- 哈希 / 恢复记录 / 原子写入 / 回滚
 +---- TestRunner -------- 固定 pytest / 超时 / 进程树终止
 +---- FeedbackEngine ---- 分类 / 摘要 / 指纹 / 无进展检测
 +---- MemoryStore ------- 会话内 / 显式跨会话摘要
 `---- Observer ---------- 控制台事件 / 可选脱敏 JSONL
```

### 5.2 状态机

```text
INITIALIZING
  -> REQUESTING_ACTION
  -> VALIDATING_ACTION
  -> WAITING_APPROVAL（仅高风险）
  -> EXECUTING
  -> VERIFYING（发生代码写入）
  -> FEEDBACK
  -> REQUESTING_ACTION / COMPLETED / FAILED / ROLLING_BACK
```

强制约束：

- 未经 PolicyEngine 判定的动作不能进入工具层；
- 每个模型轮次只接受一个动作；
- 创建或修改代码后自动进入 VERIFYING；
- 有代码修改时，最近一次测试未通过就拒绝 `finish`；
- 模型格式错误、策略拒绝、工具错误和测试失败均形成反馈；
- 达到预算、无进展或安全状态不确定时停止；
- 失败和中断默认进入 ROLLING_BACK。

### 5.3 一次任务的数据流

1. CLI 校验工作区和非秘密配置，CredentialStore 从 Credential Manager 把 Key 读入进程内存，建立 `SessionState` 与文件事务；
2. ContextBuilder 组合任务、工具 schema、项目摘要、最近 Observation/Feedback 和按需文件内容；
3. LLMClient 发起一次补全，ActionParser 把唯一工具调用解析为 `Action`；解析失败也进入反馈，不直接执行文本；
4. PolicyEngine 检查路径、动作、风险和当前事务，输出 `ALLOW`、`CONFIRM` 或 `DENY`；
5. 获准动作由 ToolDispatcher 执行；写动作先校验哈希并记录首次快照，再原子替换文件；
6. 写入代码后 TestRunner 自动运行固定 pytest，FeedbackEngine 将结果分类、脱敏、摘要并生成指纹；
7. Feedback 以高优先级回到 ContextBuilder，驱动下一轮动作；Observer 同步输出脱敏事件；
8. 只有完成门禁通过才能提交事务并形成 `RunResult`；失败、中断或无进展则回滚，成功摘要可在用户显式启用时写入 ProjectMemory。

秘密只在 CredentialStore 与 LLMClient 调用边界的进程内存中流动，不进入 Action、Feedback、Observer、事务记录或 ProjectMemory。

### 5.4 外部依赖

| 依赖 | 用途 | 边界 |
|---|---|---|
| 学校 OpenAI 兼容 API | 单轮 Chat Completions 与 tool calling | 不使用供应商高层 agent runner |
| `openai` Python SDK | 底层单次 API 调用 | 自行实现循环、解析、治理和反馈 |
| `keyring` | Windows Credential Manager 访问 | 不在仓库或日志保存明文 Key |
| pytest | 项目客观反馈和本仓库测试 | 固定命令，模型不能自定义 shell |
| uv | Python、依赖、测试和构建环境 | 不承担 `.exe` 打包 |
| PyInstaller | Windows x64 可执行文件 | 在固定 Python 构建版本上验证 |
| Git | 只读状态检查和课程过程 | 产品不自动 reset/checkout/commit |

## 6. 主要数据模型

### 6.1 关系与统一约束

```text
SessionState 1 ── * Action 1 ── 1 PolicyDecision
                     |
                     +── 0..1 Observation ── 0..1 Feedback

写 Action 1 ── 1 TransactionRecord
成功 RunResult 0..1 ──> ProjectMemory 摘要
```

- `SessionState` 是一次运行的聚合根，动作、观察和反馈必须带同一 `run_id`；
- 每个写动作在执行前必须已有唯一的 `TransactionRecord`，同一相对路径的首次快照不可覆盖；
- 数据模型中的路径只保存规范化后的工作区相对路径；
- 所有可持久化或可输出模型均禁止出现 API Key、Authorization 请求头和完整文件正文；
- Observation 可以没有 Feedback（例如成功读取），但测试失败、策略拒绝和工具错误必须产生 Feedback。

### 6.2 Action

| 字段 | 类型 | 约束 |
|---|---|---|
| `kind` | 枚举 | `list_files`、`read_file`、`create_file`、`edit_file`、`finish` |
| `path` | 可选相对路径 | 禁止绝对路径、`..`、链接和受保护路径 |
| `expected_sha256` | 可选字符串 | `edit_file` 必填 |
| `old_text` / `new_text` | 可选字符串 | 精确替换；旧文本必须恰好出现一次 |
| `content` | 可选字符串 | `create_file` 使用，受大小和类型限制 |
| `reason` | 字符串 | 仅作说明，不能覆盖策略判定 |

### 6.3 PolicyDecision

| 字段 | 类型 | 说明 |
|---|---|---|
| `level` | `ALLOW` / `CONFIRM` / `DENY` | 执行权限 |
| `rule_id` | 字符串 | 触发的稳定规则编号 |
| `reason` | 字符串 | 面向用户和 LLM 的脱敏原因 |
| `risk_facts` | 列表 | 文件数、改动行数、敏感能力等 |

### 6.4 Observation 与 Feedback

| 字段 | 说明 |
|---|---|
| `kind` | 文件结果、工具错误、测试失败、超时、策略拒绝等 |
| `success` / `passed` | 工具或测试是否成功 |
| `exit_code` | pytest 或内部执行结果 |
| `summary` | 有长度上限的稳定摘要 |
| `failed_tests` | 可靠提取时的失败测试名 |
| `output_tail` | 脱敏且截断的原始输出尾部 |
| `fingerprint` | 识别重复失败的稳定指纹 |

### 6.5 SessionState

| 字段 | 说明 |
|---|---|
| `run_id` | 当前运行标识，不含凭据 |
| `state` | 当前状态机状态 |
| `round_count` | 已使用模型动作轮数 |
| `actions` | 动作签名与结果历史 |
| `last_feedback` | 最新结构化反馈 |
| `last_test_passed` | 完成门禁依据 |
| `touched_files` | 本次事务涉及文件 |
| `invalid_count` / `repeat_count` | 停机计数 |

### 6.6 TransactionRecord

保存目标相对路径、原始存在状态、原始 SHA-256、恢复材料路径和恢复状态。同一文件第一次触碰后的原始记录不可被后续修改覆盖。

### 6.7 ProjectMemory

只包含用户显式项目说明、最近一次成功运行摘要、更新时间和格式版本。禁止保存 API Key、完整对话和文件全文。

## 7. 功能规约

### F-01 CLI 与配置

| 项目 | 规约 |
|---|---|
| 输入 | `run`、`credential`、`memory` 子命令；工作区、任务、Base URL、模型和非秘密配置 |
| 行为 | 解析参数、加载 TOML/默认值、规范化目录、建立 SessionState；秘密值不接受普通明文配置 |
| 输出 | 状态事件、最终 RunResult、稳定退出码 |
| 边界 | Windows 10/11 x64；工作区不得为磁盘根或用户主目录 |
| 错误 | 参数/配置无效时在调用 LLM 与写文件前退出，返回 `2` |

### F-02 凭据管理

| 项目 | 规约 |
|---|---|
| 输入 | 隐藏输入 API Key；Credential Manager 中的服务名与账户别名 |
| 行为 | 支持 `credential set/status/clear`；Key 由 Windows Credential Manager 保存；运行时读取到内存 |
| 输出 | 仅显示已配置/未配置、来源和操作结果，永不回显 Key |
| 边界 | 默认服务名固定为 `fbw-harness`；首版不接受命令行参数、环境变量、TOML 或 `.env` 中的 Key |
| 错误 | 凭据库不可用、拒绝访问或 Key 为空时失败；不退回仓库明文文件 |

### F-03 上下文与 LLM 决策

| 项目 | 规约 |
|---|---|
| 输入 | 任务、工具 schema、项目摘要、最近 Observation/Feedback、按需读取的文件内容 |
| 行为 | ContextBuilder 按优先级构造上下文；OpenAICompatibleClient 发起单次 Chat Completions；ActionParser 只接受唯一工具调用或结构化 finish |
| 输出 | Action 或结构化解析错误 |
| 边界 | 不全量加载仓库；旧观察压缩，最后反馈和相关文件优先保留 |
| 错误 | 鉴权错误立即停止；临时网络错误最多重试 2 次；连续 3 次格式错误停止 |

### F-04 文件发现与读取

| 项目 | 规约 |
|---|---|
| 输入 | 工作区内相对目录或文件路径 |
| 行为 | 应用忽略规则、规范化路径、检查沿途重解析点；读取允许的普通文本并计算 SHA-256 |
| 输出 | 有上限的文件列表，或文本内容、编码和哈希 |
| 边界 | 跳过 `.git`、虚拟环境、构建产物、凭据、二进制和超限文件 |
| 错误 | 越界、链接、编码失败或文件变化时返回结构化工具错误，不泄漏外部内容 |

### F-05 创建与精确修改

| 项目 | 规约 |
|---|---|
| 输入 | `create_file` 内容，或 `edit_file` 的路径、预期哈希、旧文本和新文本 |
| 行为 | 策略判定后建立首次恢复记录；在内存生成结果；同目录临时文件完整写入后原子替换 |
| 输出 | 修改摘要、新哈希和受影响行数 |
| 边界 | 普通操作单轮最多 3 个文件、200 行；普通单文件最大 256 KiB；不提供模型删除/移动/重命名 |
| 错误 | 哈希陈旧、旧文本不唯一、风险未批准或写入失败时不覆盖目标，并返回结构化错误 |

### F-06 治理与 HITL

| 项目 | 规约 |
|---|---|
| 输入 | Action、工作区事实、Git 脏状态、修改规模、静态危险能力提示 |
| 行为 | 产生 ALLOW/CONFIRM/DENY；CONFIRM 显示文件、规模、规则和后续测试；DENY 不允许强制绕过 |
| 输出 | PolicyDecision、用户审批结果或拒绝 Feedback |
| 边界 | 普通受控源码修改自动执行；依赖/CI/配置/脏文件/大范围/危险能力进入确认 |
| 错误 | 无法安全判定时按高风险或拒绝处理，永不默认放行 |

### F-07 pytest 执行器

| 项目 | 规约 |
|---|---|
| 输入 | 固定配置的 `uv run pytest -q`、工作区和 60 秒默认超时 |
| 行为 | 写入后自动启动固定参数子进程；捕获 stdout/stderr；Windows 超时后终止进程树 |
| 输出 | 退出码、时长、截断输出和 TestResult |
| 边界 | 模型不能提供命令、参数或 shell 片段；输出尾部默认最多 12,000 字符 |
| 错误 | 命令缺失、收集错误、失败和超时均转为结构化反馈，不让主进程崩溃 |

### F-08 反馈闭环

| 项目 | 规约 |
|---|---|
| 输入 | TestResult、工具结果和策略结果 |
| 行为 | 分类、保守提取失败测试、脱敏、摘要、生成稳定指纹；将最新反馈置于下一轮高优先级上下文 |
| 输出 | Feedback 与下一轮 Context |
| 边界 | 不能可靠提取时保留原始摘要，不编造 expected/actual；最近反馈不得被旧历史挤出 |
| 错误 | 相同动作签名与反馈指纹连续 2 次判定 `no_progress` 并停止 |

### F-09 文件事务与回滚

| 项目 | 规约 |
|---|---|
| 输入 | 每个已获准的创建/修改及任务结束原因 |
| 行为 | 首次触碰时把恢复材料写到系统临时目录 `fbw-harness/<run-id>`；成功清理并保留修改；失败/中断恢复原始状态 |
| 输出 | 提交或回滚摘要、未恢复文件和恢复材料位置 |
| 边界 | 测试中间失败保留当前修改以继续修正；内部可移除本轮新建文件，但不向模型暴露删除工具 |
| 错误 | 回滚不完整时不清理恢复材料，返回 `3` 并要求人工处理 |

### F-10 记忆

| 项目 | 规约 |
|---|---|
| 输入 | 会话事件、用户显式项目说明、成功 RunResult |
| 行为 | 会话内始终记录；跨会话存储默认关闭，启用后只保存项目说明和成功摘要；按需检索后注入 ContextBuilder |
| 输出 | 精简 ProjectMemory 或内存状态 |
| 边界 | 模型不能任意写入记忆；不保存 Key、完整对话、文件全文和失败恢复内容 |
| 错误 | 格式损坏时隔离该记忆并提示，不阻断无记忆运行；写入失败不影响文件事务 |

### F-11 可观测性

| 项目 | 规约 |
|---|---|
| 输入 | 状态迁移、动作摘要、策略决定、测试结果、停止和回滚事件 |
| 行为 | 控制台逐步显示；可选 JSONL 使用脱敏结构化事件，默认不持久化运行日志 |
| 输出 | 可读事件、最终摘要、运行 ID 和退出码 |
| 边界 | 不记录 API Key、请求头、完整文件内容或完整 LLM 上下文 |
| 错误 | 日志写入失败只告警，不应绕过安全机制或改变任务结果 |

### F-12 分发与首次运行

| 项目 | 规约 |
|---|---|
| 输入 | 版本标签、固定 Python 构建环境、PyInstaller 配置 |
| 行为 | 生成 Windows x64 可执行文件、SHA-256 校验文件和发布说明；首次运行引导安全配置 Key |
| 输出 | GitHub Release 下载产物与 README 安装/运行/安全说明 |
| 边界 | 目标 Windows 10/11 x64；首版未签名，README 说明 SmartScreen 风险和校验方式 |
| 错误 | 构建或一键测试失败时禁止发布；新机器冒烟失败时版本不视为可交付 |

## 8. 领域与机制设计

### 8.1 Coding 领域的四类机制

| 类别 | 本项目设计 |
|---|---|
| 动作 / 工具 | 列出、读取、创建、精确替换；内部固定 pytest；不开放任意 shell 和删除 |
| 客观反馈 | pytest 退出码、失败测试、收集/语法/导入/断言/超时分类、脱敏输出与稳定指纹 |
| 危险动作 | 越界、链接、凭据、`.git`、删除、任意命令直接拒绝；依赖/CI/脏文件/大范围/危险能力需审批 |
| 记忆 | 会话状态始终存在；显式启用的项目说明和成功摘要按需检索，不全量载入 |

### 8.2 六个 harness 维度的最低实现

| 维度 | 最低可运行实现 | 离线可测证据 |
|---|---|---|
| 决策封装 | ContextBuilder + LLMClient + ActionParser + 显式状态机 | Mock LLM 驱动完整状态转换 |
| 工具 | 文件发现、读取、创建、精确替换、固定 pytest | Fake/临时工作区断言输入输出与未调用路径 |
| 上下文与记忆 | 优先级上下文、旧观察摘要、会话状态、可选 ProjectMemory | 给定历史后断言选取、压缩和禁止字段 |
| 治理护栏 | 路径围栏、风险分级、HITL、禁止项、事务回滚 | 构造 Action 后确定性断言 ALLOW/CONFIRM/DENY |
| 反馈闭环 | 强制测试、结构化反馈、回灌、完成门禁、无进展检测 | 注入失败后断言下一动作变化与停止原因 |
| 配置 | TOML/CLI 声明测试命令、预算、阈值、日志和记忆；秘密分离 | 配置解析、优先级、非法值和秘密字段拒绝测试 |

### 8.3 重点维度：反馈闭环深入设计

反馈闭环是主要贡献，不只把原始 pytest 文本塞回模型，而是形成以下代码管线：

```text
代码写入
 -> TestRunner 强制执行
 -> TestResult 采集退出码/输出/时长
 -> FeedbackEngine 分类与脱敏
 -> 生成摘要和 fingerprint
 -> ContextBuilder 高优先级回灌
 -> Mock/真实 LLM 产生不同下一动作
 -> 完成门禁或 no_progress 停机
```

反馈类别至少包括：通过、断言失败、测试收集失败、语法/导入错误、超时、策略拒绝和工具错误。分类是保守且确定的：无法可靠识别时使用 `unknown_test_failure`，不让模型臆测成为 harness 的事实。

反馈指纹由类别、退出码、失败测试名和规范化摘要生成。连续两轮动作签名及反馈指纹均相同，判定无进展。最近 Feedback 必须高于旧观察进入上下文；发生代码修改后，只有最新 TestResult 通过才允许完成。

### 8.4 机制演示

1. **治理演示**：Mock LLM 请求读取 `../outside.txt` 或执行删除动作；PolicyEngine 在工具调用前 DENY，并断言文件工具未被调用。
2. **反馈修正演示**：Mock LLM 首次给出错误 `clamp()` 边界修改；真实 pytest 失败；Feedback 回灌后返回不同且正确的修改；pytest 通过后完成。
3. **重点维度演示**：Mock LLM 重复无效修改；相同反馈指纹连续两次；AgentLoop 以 `no_progress` 停止并恢复原文件。

三项演示使用真实 AgentLoop、工具、事务、pytest、反馈和护栏，只替换 LLM，且不依赖网络和真实 Key。

## 9. 凭据威胁模型与安全存储

### 9.1 资产与威胁

| 资产/风险 | 威胁场景 | 对策 |
|---|---|---|
| API Key | 硬编码、Git 历史、配置文件、日志或终端历史泄露 | Credential Manager、隐藏输入、秘密扫描、脱敏日志、禁止 CLI 明文参数 |
| 工作区文件 | 越界、链接绕过、覆盖并发修改、半写入 | 规范路径、重解析点检查、SHA-256、原子写入、事务回滚 |
| 用户机器 | 模型生成代码通过 pytest 执行危险能力 | 固定命令、静态能力提示、高风险审批、明确非沙箱边界、只处理可信项目 |
| 运行上下文 | 完整文件或请求头进入日志/记忆 | 最小上下文、输出截断、脱敏字段、默认无持久日志 |
| 恢复材料 | 临时副本残留或被无关进程读取 | 独立 run 目录、最小文件集、成功/完整回滚后清理、失败时明确路径 |

### 9.2 安全存储流程

- `credential set`：隐藏输入，写入 Windows Credential Manager；
- `credential status`：只显示是否存在、服务名和账户别名；
- `credential clear`：删除对应凭据并确认结果；
- `run`：只从 Credential Manager 读取；缺失时提示用户先执行 `credential set`；
- 任何命令都不回显、记录或写入明文 Key；
- `.env*` 保持 Git 忽略并禁止 Agent 工具读取。

### 9.3 当前历史冲突

提交 `77da924` 中的既有原型/检测脚本已经包含临时 API Key，因此当前 Git 历史不符合课程“历史中不得出现凭据”的要求。解决合规问题至少需要：撤销/轮换该 Key、从当前树移除明文、经用户明确授权后重写历史、再次全历史扫描。用户明确要求本轮不得自行重写历史，所以该问题保持为阻断公开提交的未解决风险。

## 10. 非功能性需求

### 10.1 性能

- 参考 Windows x64 机器上，不含外部 API 和 pytest 时，源码 CLI 启动目标不超过 2 秒，PyInstaller 单文件发行版冷启动目标不超过 5 秒；
- 单个普通文本文件默认不超过 256 KiB；
- 文件列表、上下文和输出必须有上限，避免把全仓库一次载入内存或模型；
- 默认最多 6 个模型动作轮、2 次临时网络重试、60 秒 pytest；
- 同一进程内串行执行，避免并发写同一工作区。

### 10.2 安全

- 满足 §9 凭据设计；
- 所有工具先策略后执行；
- 禁止项不可通过普通确认绕过；
- 写入具备哈希、原子替换和恢复记录；
- 测试明确不构成操作系统沙箱；
- 发布前对当前树与完整历史执行凭据扫描，任何命中阻断发布。

### 10.3 可用性

- 错误消息必须说明发生阶段、原因和下一步，不只显示堆栈；
- 控制台显示 `[轮次]`、动作摘要、策略结果、测试摘要和最终停止原因；
- 高风险审批必须显示触发规则和受影响文件；
- `Ctrl+C` 触发受控停止和回滚；
- README 面向全新 Windows 机器给出从下载到首次任务的完整步骤。

### 10.4 可观测性

- 每次运行有非秘密 run ID；
- 状态迁移、策略决定、测试和回滚有结构化事件；
- 默认仅控制台，不持久化完整日志；
- 可选 JSONL 只能包含脱敏摘要；
- 最终 RunResult 包含轮数、修改文件、最后测试、停止和回滚状态。

### 10.5 可靠性与可测试性

- 核心机制不依赖真实 LLM、网络或 Key；
- 所有外部边界通过接口可注入 Mock/Fake；
- 单元测试多次运行结果一致；
- 回滚不完整不得被报告为成功；
- CI 的 `unit-test` job 必须通过，最后一次 CI/CD 状态必须为 pass。

## 11. 错误处理与停机

| 情况 | 处理 | 退出/状态 |
|---|---|---|
| 参数、配置、工作区无效 | 调用 LLM 前停止 | 退出码 `2` |
| Key 缺失或 Credential Manager 错误 | 引导配置或停止 | `2` |
| API 鉴权失败 | 停止；已有修改则回滚 | `1` |
| 临时网络失败 | 最多重试 2 次 | 耗尽后 `1` |
| 工具调用格式错误 | 结构化回灌 | 连续 3 次后 `1` |
| 策略拒绝 | 不调用工具，回灌规则 | 可继续 |
| 文件哈希变化 | 拒绝覆盖，要求重读 | 可继续 |
| 精确替换不唯一 | 回灌工具错误 | 可继续 |
| pytest 失败 | 分类并回灌 | 可继续 |
| pytest 超时 | 终止进程树并回灌 | 可继续/预算控制 |
| 相同动作与反馈连续 2 次 | 判定无进展 | 回滚，`1` |
| 最大 6 轮 | 停止 | 回滚，`1` |
| 用户中断或内部异常 | 受控停止 | 回滚，`1` |
| 回滚不完整 | 保留恢复材料并报警 | `3` |

任务成功要求：如发生代码写入，最近一次 pytest 必须通过；LLM 必须请求 `finish`；不存在待审批、未完成写入或回滚状态。

## 12. 技术选型与理由

| 选型 | 理由 | 代价/控制 |
|---|---|---|
| Python | 初学友好，文件/进程/JSON/测试生态成熟，适合快速表达状态机 | 动态类型风险通过类型标注、dataclass 和测试控制 |
| uv | 可重复管理 Python、锁文件、依赖和一键命令 | `.exe` 另用 PyInstaller |
| Python 3.13 x64 构建 | 相比最新解释器更适合作为固定发行构建基线 | 源码兼容范围在实现时验证并锁定 |
| 标准库 `argparse`/`tomllib` | 减少 CLI 与配置依赖 | 界面朴素但满足纯 CLI |
| OpenAI Python SDK | 学校 API 已验证为 OpenAI 格式，允许自定义 Base URL | 仅使用单轮底层调用，不使用 agent runner |
| `keyring` | 为 Windows Credential Manager 提供可测试抽象 | 需处理后端不可用与打包兼容 |
| pytest | 与 Coding 领域客观反馈、TDD 和课程要求一致 | 首版仅支持 pytest 项目 |
| PyInstaller | 生成 Windows x64 可执行文件，符合 GitHub Release 分发决定 | 产物较大、未签名、需新机验证 |
| GitLab CI + GitHub Actions | 前者满足 `.gitlab-ci.yml`/`unit-test`，后者构建 GitHub Release | 两套 CI 增加维护成本，见 §20 |

纯 CLI 不涉及前端，因此豁免 Open Design。

## 13. 配置设计

非秘密配置使用 TOML；优先级为 CLI 参数 > 项目配置 > 用户配置 > 内置默认值。秘密字段不得出现在 TOML schema。

配置至少包含：Base URL、模型、pytest 固定参数、轮数、网络重试、超时、普通修改阈值、输出上限、日志模式、记忆开关与记忆路径。未知字段、非法类型、负数预算和包含秘密字段名的配置必须报错。

Agent 读取配置用于约束行为；Agent 修改依赖/CI/测试配置属于高风险并需审批。配置不能启用任意 shell、越界路径或删除工具。

## 14. 测试与验证策略

### 14.1 TDD

每个 PLAN task 必须先添加最小失败测试并实际观察失败，再写最少实现使其通过，最后重构。PLAN 需要记录失败测试、命令和预期失败原因。禁止先写实现再补测试。

### 14.2 单元测试矩阵

- ActionParser：合法、未知、缺参、多调用、混合文本；
- ContextBuilder：优先级、压缩、最后反馈保留、敏感字段排除；
- PolicyEngine：ALLOW/CONFIRM/DENY、越界、凭据、重解析点、规模和危险能力；
- FileTransaction：哈希冲突、精确替换、原子写入、新文件、提交、回滚和回滚失败；
- TestRunner：通过、失败、收集错误、超时、进程树终止和输出截断；
- FeedbackEngine：分类、保守降级、脱敏、指纹和无进展；
- MemoryStore：显式启用、按需检索、禁止字段和损坏隔离；
- CredentialStore：set/status/clear、不可用、空值和不回显；
- AgentLoop：状态转换、强制测试、finish 门禁、预算、中断与真实/Mock 共用接口。

### 14.3 集成与机制演示

使用 pytest 临时目录和 Mock LLM，调用真实文件工具、事务、pytest、反馈、护栏和 AgentLoop，完成 §8.4 三项确定性演示。默认 `uv run pytest` 不依赖网络、真实 Key 或用户真实项目。

### 14.4 冷启动验证

SPEC 与 PLAN 完成后、正式实现前，使用不同类型的新智能体，在全新会话中仅提供 `SPEC.md` 与 `PLAN.md`，让其选择 1–2 个 task 并在不确定处暂停。问题、误解和修订前后 diff 记录到 `SPEC_PROCESS.md`。该步骤不得导入本窗口历史。

### 14.5 真实 API 与全新机器验证

- 手动真实 API 冒烟只验证接口接线与完整 CLI 流程，不作为确定性单测；
- Windows x64 发行物必须在未安装项目 Python 环境的全新机器/干净虚拟机验证；
- 验证 Credential Manager 录入、状态、更新、清除、运行、SmartScreen 说明和 SHA-256；
- 任何凭据扫描命中、单元测试失败或 CI 非 pass 都阻断发布。

## 15. 分发与 CI

### 15.1 分发形态

- 目标平台：Windows 10/11 x64；首版不承诺 macOS 或 Linux 发行物；
- 产物：PyInstaller 单文件 `.exe`、SHA-256 文件、版本说明；
- 渠道：用户明确选择 GitHub Release 链接；
- 签名：首版不签名，README 明确 SmartScreen 与校验方法；
- 源码用户可使用 uv 安装和运行，但正式验收以下载发行物为准。

### 15.2 README 必需章节

- 项目简介；
- 获取与安装；
- 首次安全配置 Key；
- 运行命令与示例；
- 目录结构；
- 测试与机制演示；
- 分发与校验；
- 安全边界与威胁模型摘要；
- 已知限制与合规偏离；
- 第三方依赖与许可证。

### 15.3 CI

- `.gitlab-ci.yml` 必须包含名为 `unit-test` 的 job；
- 每次 push 运行离线测试和凭据扫描；
- GitHub Actions 在 Windows runner 上运行测试、构建 `.exe`、生成 SHA-256，并仅在版本标签发布；
- 最终提交前保存最后一次 pass 的 CI/CD 执行记录；
- Release 只允许来自通过测试和凭据扫描的 commit。

## 16. 验收标准

### 16.1 产品验收

- AC-01：全新 Windows x64 用户能从 Release 下载并启动 CLI；
- AC-02：`credential set/status/clear` 使用 Credential Manager 且不回显 Key；
- AC-03：真实 OpenAI 兼容 API 能完成至少一次受控 Python 修复任务；
- AC-04：真实与 Mock LLM 共用同一 AgentLoop；
- AC-05：模型不能绕过 ActionParser、PolicyEngine 或固定 pytest；
- AC-06：普通读取、创建和精确修改能在工作区内成功；
- AC-07：越界、`.git`、凭据、链接、任意命令和删除在工具调用前被拒绝；
- AC-08：高风险动作显示规则和文件后等待确认；
- AC-09：代码写入后自动运行 pytest，失败形成结构化 Feedback；
- AC-10：Feedback 能导致 Mock LLM 下一动作发生确定变化；
- AC-11：测试未通过时 `finish` 被拒绝；
- AC-12：无进展、预算、中断和内部异常触发受控停止与回滚；
- AC-13：回滚不完整返回 `3` 并保留恢复材料；
- AC-14：可选跨会话记忆只保存允许字段并能按需注入；
- AC-15：控制台/JSONL/记忆不含 Key、请求头和完整敏感内容。

### 16.2 工程验收

- AC-16：至少 3 个职责清晰模块，实际按 §5 边界拆分；
- AC-17：`uv run pytest` 一键离线通过核心测试；
- AC-18：三项机制演示可重复运行且结果一致；
- AC-19：TDD 红—绿—重构证据、task commit 和评审结果进入 PLAN/AGENT_LOG；
- AC-20：`.gitlab-ci.yml` 存在 `unit-test` 且最终 CI/CD 为 pass；
- AC-21：GitHub Release 包含 `.exe`、SHA-256 和说明；
- AC-22：README 覆盖课程必需章节和全新机器路径；
- AC-23：SPEC、PLAN、SPEC_PROCESS、AGENT_LOG、README、REFLECTION 和机制演示齐全；
- AC-24：公开发布前完整 Git 历史凭据扫描为零命中。

## 17. 课程过程与交付约束

- brainstorming 产出正式 SPEC 并经用户批准；
- 批准后才能调用 `writing-plans` 生成正式 PLAN；
- PLAN task 明确路径、2–5 分钟步骤、失败测试、验证、依赖和并行关系；
- PLAN 后进行不同类型智能体冷启动验证并修订 SPEC/PLAN；
- 实现使用 `test-driven-development`，并按任务执行 spec 合规和代码质量两阶段评审；
- `AGENT_LOG.md` 持续记录技能、prompt/context、subagent、commit、人工干预和教训；
- `SPEC_PROCESS.md` 持续记录 brainstorming、冷启动缺陷和修订 diff；
- `PLAN.md` 每完成 task 标记并附 commit hash；
- `REFLECTION.md` 由学生本人撰写，AI 只能辅助润色并标注。

## 18. 学术规范

- 第三方代码与依赖在 README 列出许可证；
- 学生自行编写部分在文件/函数注释标明；
- commit/PR 说明标注使用的 subagent 和人工修改；
- 反思报告不得由 AI 代写；
- 本项目的最终判断、规格批准和风险接受由学生负责。

## 19. 风险与已知限制

| ID | 风险/限制 | 影响 | 缓解/状态 |
|---|---|---|---|
| R-01 | pytest 以当前 Windows 用户权限执行，不是系统沙箱 | 生成代码仍可能影响机器 | 固定命令、危险能力审批、可信项目边界、明确残余风险 |
| R-02 | 精确文本替换弱于完整补丁 | 复杂修改可能失败或轮次增加 | 哈希与唯一匹配换取确定性；后续再评估结构化 diff |
| R-03 | 模型 tool calling 可能返回格式异常 | Agent 停滞 | 严格解析、反馈、3 次上限、Mock 覆盖 |
| R-04 | PyInstaller、keyring 与固定 Python 版本打包兼容性 | `.exe` 构建或 Credential Manager 失败 | 早期最小打包 spike、Windows CI、新机验证 |
| R-05 | 两套 CI 和 GitHub Release 增加维护 | 流程复杂 | GitLab 负责课程 job，GitHub Actions 负责 Windows release，职责分开 |
| R-06 | 结构化 pytest 解析受输出格式影响 | 分类不完整 | 保守降级并保留脱敏 output_tail，不编造字段 |
| R-07 | 跨会话记忆可能泄露项目事实 | 隐私风险 | 默认关闭、字段白名单、显式路径、禁止秘密与全文 |
| R-08 | 初学者难以审查内部架构 | 人工批准质量风险 | 以可观察行为、验收标准和冷启动验证降低隐性假设 |

## 20. 冲突、有意偏离与未决问题

### C-01 纯 CLI 与 WebUI 强制项冲突

用户明确决定只做纯 CLI，不提供 WebUI；课程最终清单第 9 项却要求可访问 WebUI URL。通用分发要求允许原生二进制/包，A 项本身也适合 CLI，但最终清单文字仍构成风险。本规格保留纯 CLI 决定，并将其标为有意偏离；提交前应向教师取得书面确认，否则可能影响合规评分。

### C-02 临时 API Key 已进入 Git 历史

`77da924` 已包含临时 Key，违反课程“当前树和历史均不得有凭据”的要求。用户禁止本轮自行重写历史。公开推送/正式提交前必须由用户明确授权处理历史并轮换 Key；在此之前 AC-24 不可能通过。

### C-03 当前在 main 推进与 worktree/PR 冲突

用户明确要求本次继续在 `main` 上、不新建分支；课程要求每个独立功能使用 worktree 和 PR。本规格如实记录该偏离。可在用户后续改变授权时恢复正式分支/worktree/PR；未改变前不得偷偷新建分支。

### C-04 项目从探索 demo 转为正式课程项目

早期文档和提交把仓库描述为随时可舍弃的 demo。用户现已明确：仓库可在未来重做，但本次流程和成品必须按正式课程项目完成。本文件取代旧的范围定位；旧设计仍作为 brainstorming 依据和过程证据保留。

### C-05 GitLab CI 与 GitHub Release

课程要求 NJU Git 仓库及 `.gitlab-ci.yml`，用户决定使用 GitHub Release。默认方案是 GitLab CI 完成课程 `unit-test` 和最终 pass，GitHub Actions 构建/发布 Windows `.exe`；需要确认 GitHub 镜像与 Release 链接是否被课程接受。

## 21. SPEC 批准门禁

本文件须完成占位符、一致性、范围和歧义自检，并由用户明确批准。批准后才允许：

1. 调用 Superpowers `writing-plans`；
2. 创建正式 `PLAN.md`；
3. 进行不同类型智能体冷启动验证；
4. 修订并再次批准 SPEC/PLAN；
5. 进入 TDD 实现。

当前不得编写实现代码，也不得自行重写 Git 历史、创建分支或解决 §20 的用户授权冲突。
