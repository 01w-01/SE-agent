# Git 历史敏感模式清理证据

状态：**PASS（规范 GitHub/NJU refs）**

执行时间：2026-08-12（Asia/Shanghai）

## 范围与工具

- 工具：`git-filter-repo 2.47.0`；
- 输入：只含 `refs/heads/main` 的一次性 bare clone；
- 模式：历史 `sk-...` 凭据形态，替换规则不包含真实 Key；
- 原 main：`1846675d5be6e0f1a2cfc02c61657fe5815f6cf4`；
- filter-repo 等价 head：`6110edef48c0cdffa04fec920d9a9208d7fa5538`；
- 最终 main：`9cd6cb5aad2a7633e0b52b67f4d6ab0cae86fed8`；
- 受影响提交：120；commit map 全覆盖、无零映射、old/new 列无重复。

## 不变量与验证

- filter-repo 前后 head tree 均为 `dd4926f3a1034314e7f66940de7cd00a37fe2945`；提交数量均为 120；
- 顶部额外增加一个普通合同提交，只把历史扫描测试从“已知历史应失败”更新为“清理历史应通过且无输出”；
- 临时验证 clone：当前树扫描 PASS、历史扫描 PASS、`754 passed, 1 skipped`、Ruff PASS；
- GitHub fresh clone：HEAD 与最终 main 一致，双扫描 PASS、`754 passed, 1 skipped`、Ruff PASS；
- NJU fresh clone：HEAD 与最终 main 一致，当前树扫描与历史扫描 PASS；
- 根仓库切换后：双扫描 PASS、`754 passed, 1 skipped`、Ruff PASS；旧 main 已从本地 refs/reflog/对象库清除。

## 远端更新

- GitHub/NJU `main` 均使用明确旧 SHA 的 `force-with-lease` 更新；
- GitHub 旧分支 `task/14-final-evidence` 使用明确分支旧 SHA 的租约删除；
- NJU 仅在用户临时允许 protected `main` force push 后更新；应在更新后恢复保护设置。

## 外部平台边界

规范 refs 与 fresh clone 已无扫描命中。GitHub cached views、旧 PR diff 与 internal PR refs 可能仍由平台保留；永久清除需联系 GitHub Support。该边界不改变当前 GitHub/NJU `main` 的历史扫描 PASS 结论。

本文件不包含 Key、请求头、blob 内容或匹配文本。
