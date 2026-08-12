# OpenAI 工具选择兼容降级设计

日期：2026-08-12

## 问题

学校网关 `https://njusehub.info/v1` 与 `deepseek-v4-flash` 已实测支持 OpenAI chat 和 tools，但带 `tool_choice="required"` 时返回 HTTP 400；省略 `tool_choice` 后能正常返回工具调用。现有客户端把该 400 归一为 `LLMDecisionError`，真实 AgentLoop 无法开始。

## 设计

`OpenAICompatibleClient` 初始保持严格模式：发送 `tools` 与 `tool_choice="required"`。若且仅若该请求得到可安全识别的 HTTP 400，则：

1. 将该 client 实例标记为不支持 required；
2. 同一轮只重发一次相同 model/messages/tools，但省略 `tool_choice`；
3. 后续轮次直接使用 tools-only，不再重复制造 400；
4. 仍由 ActionParser 强制“恰好一个合法工具调用”，模型返回文本、零个或多个工具仍进入既有格式反馈/失败边界。

401/403、429、5xx、连接错误、超时和畸形响应保持原语义；400 降级后的第二次失败不再次降级。公开 factory/client 接口、配置范围和错误文本不变。

## 安全与测试

- 不读取或输出 HTTP 响应正文、Key、Base URL 或异常文本；状态码属性读取继续放在不可信异常边界。
- Fake SDK 测试先证明旧实现在 required 400 后直接失败，再验证调用序列为 `required -> tools-only`。
- 验证一个 client 后续 decide 只发 tools-only；新 client 仍从 required 开始。
- 验证 401 不降级、400 后再次失败固定归一、tools-only 响应仍必须满足现有 RawDecision 上限。
- 完成定向/全量/Ruff/format/秘密扫描后，再重跑一次性真实 API clamp 修复；最终清除 CredentialStore 和临时项目。
