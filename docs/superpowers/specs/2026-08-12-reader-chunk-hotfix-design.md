# 高输出 reader 分块性能修复设计

日期：2026-08-12

## 问题与根因

PR #18 同一提交的 pull_request 检查通过，但 branch push 检查中 `test_runner_bounds_stdout_and_stderr_while_draining_both_pipes` 用时 10.17 秒并触发 10 秒超时。

`_TailReader` 当前用 `min(8192, output_tail_limit)` 作为 pipe 读取块。输出尾部上限为 256 时，stdout/stderr 共 2 MB 会产生约 7,800 次读取、诊断扫描和流式脱敏调用。本机连续 5 次测试内部耗时约 7.3–7.6 秒，CI runner 的正常性能波动即可越界。

## 设计

- 新增私有常量 `_PIPE_READ_CHUNK_BYTES = 8192`。
- `_TailReader._drain()` 固定以 8 KiB 读取 pipe，不再让保留尾部大小决定 I/O 粒度。
- `_append_safe()` 继续只保留 `output_tail_chars` 对应的有界尾部；流式脱敏仍发生在原始 chunk 进入 tail 之前。
- 诊断 overlap、known secrets、双 pipe 并行 drain、线程 join/close 和进程超时语义不变。
- 不增加 pytest timeout，不减少 1 MB + 1 MB 压力输出，不重构 reader。

## TDD 与验收

先新增一个确定性测试，以带 `read(size)` 记录的内存 stream 直接运行 `_TailReader`，要求当 tail limit 为 256 时每次 read 请求仍为 8192。旧实现应得到 256 并 RED；生产改动后转 GREEN。

然后运行：

1. 新增定向测试；
2. 原真实双 pipe 高输出测试连续 10 次，全部通过且无 timeout；
3. Task 8 feedback/testing 定向测试；
4. 全量 pytest、Ruff、format、当前树秘密扫描和 diff check。

独立 hotfix PR 的 branch push、pull_request 两类检查都必须绿色；合并 main 后 main CI 也必须绿色。随后把 PR #18 rebase 到新 main，让它重新触发两类检查。
