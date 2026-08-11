# TestRunner 字节码缓存隔离设计

日期：2026-08-12

## 问题与目标

feedback demo 会在同一个临时项目中先写入错误实现、运行 pytest，再写回长度相同的正确实现并再次运行 pytest。Python 的时间戳型 `.pyc` 校验主要依赖源文件修改时间和大小；当两次改写处于同一时间粒度且大小相同时，第二次 pytest 可能复用第一次生成的错误字节码。GitHub Actions 已两次出现同提交一项失败、一项通过，失败表现均为修正后测试仍未通过，随后 Mock LLM 在第 4 轮耗尽。

目标是让每次 TestRunner 调用都只读取本次运行生成的字节码缓存，消除跨反馈轮次的陈旧 `.pyc` 复用，同时不删除或改写用户工作区中的缓存文件。

## 方案选择

采用每次运行独立的 `PYTHONPYCACHEPREFIX`：

1. TestRunner 在启动 pytest 前创建一个 OS 临时目录。
2. 在 pytest 子进程环境中设置 `PYTHONPYCACHEPREFIX` 指向该目录。
3. 子进程结束、超时或启动失败后，由上下文管理器清理临时目录。
4. 不把临时目录放进用户工作区，不遍历或删除工作区现有 `__pycache__`。

不采用另外两种方案：`PYTHONDONTWRITEBYTECODE` 只保证不写入，不能可靠阻止读取既有缓存；主动删除 `__pycache__` 会修改用户项目，扩大破坏面并违反最小权限原则。

## 组件与数据流

修改仅限 `fbw_harness.testing.TestRunner`：

```text
TestRunner.run(workspace)
  -> 创建独立 OS 临时 pycache 目录
  -> 复制当前进程环境并设置 PYTHONPYCACHEPREFIX
  -> Popen(pytest, cwd=workspace, env=isolated_env)
  -> 保持现有有界输出、超时和进程树终止逻辑
  -> 清理临时 pycache 目录
  -> 返回现有 TestResult
```

公开接口、HarnessConfig、TestResult、FeedbackEngine 和 AgentLoop 均不变化。

## 错误与安全边界

- 临时目录创建失败或环境构造失败必须映射为现有固定测试启动失败结果，不泄漏底层路径或异常文本。
- pytest 超时、`taskkill`、reader 回收及输出脱敏行为保持不变。
- 临时缓存位于 OS 临时目录；清理由 Python 临时目录机制完成，不操作工作区之外的任意既有路径。
- 该修复只解决 Python 字节码缓存一致性，不改变既有三项安全边界或工作区代码执行的已知限制。

## 测试与验收

TDD 回归应使用真实 TestRunner 和真实 pytest：

1. 创建一个模块及测试，第一次运行生成失败版本的字节码。
2. 将模块改成长度相同的正确版本，并把修改时间恢复为第一次运行时的值，稳定制造传统 `.pyc` 误命中条件。
3. 修复前第二次运行应失败；修复后第二次运行必须通过。
4. 断言工作区不新增 `__pycache__`，并验证临时缓存目录在成功和失败路径后均被清理。
5. 运行 TestRunner 定向测试、feedback demo 重复测试、全量 pytest、Ruff、format、当前树秘密扫描和 GitHub Actions。

验收成功标准：确定性回归由 RED 转为 GREEN，原有 750 项测试无回归，feedback demo 重复运行稳定，PR 与 main 的 GitHub Actions 均通过。
