# 高输出压力测试超时余量修复设计

日期：2026-08-12

## 问题与证据

PR #18 同一提交的 pull_request 检查通过，但 branch push 检查中 `test_runner_bounds_stdout_and_stderr_while_draining_both_pipes` 用时 10.17 秒，超过该测试人为设置的 10 秒 Harness timeout。

系统化实验结果：

- 普通真实 pytest 子进程测试约 3.3 秒；
- stdout/stderr 各写 1 MB 的压力测试约 7.2 秒；
- reader 从 256B 改为 8KiB 后，压力测试连续 10 次仍为 7.16–7.28 秒，与修改前 7.3–7.6 秒基本相同。

因此，读取调用次数虽存在可优化点，但不是 CI 超时的主要原因。主要额外耗时是 2 MB 输出必须逐字节经过既有多层流式脱敏。8 KiB 生产改动无法可靠解决问题，已撤回且不提交。

## 修正设计

- 不修改 `mini-harness/src/fbw_harness/testing.py` 或其他产品代码。
- 保留 stdout/stderr 各 1 MB 的真实压力输出，继续覆盖双 pipe drain、无死锁、输出有界和尾部保留。
- 仅把该压力测试构造的 `HarnessConfig.pytest_timeout_seconds` 从 10 提高到 30。
- 产品默认 pytest timeout 仍为 60 秒；其他成功、失败和 timeout 行为测试不变。
- 30 秒只提供慢 CI runner 的测试余量，不改变 Harness 的公开配置或运行时默认值。

## 验证

既有 GitHub branch push 失败是本修复的 RED 证据：同一压力测试返回 `timed_out=True`、exit code 124、duration 10.17 秒。修复后必须：

1. 该真实压力测试连续运行 10 次，10/10 passed；
2. Task 8 testing/feedback 定向测试全部通过；
3. 全量 pytest、Ruff、format、当前树扫描和 diff check 通过；
4. 独立 hotfix PR 的 branch push、pull_request 两类检查均绿色；
5. 合并后 main CI绿色；
6. PR #18 rebase 到新 main 后两类检查均绿色。

若 30 秒仍超时，不继续提高数值，必须回到架构层分析流式脱敏性能。
