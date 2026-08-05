import json
import shutil
import subprocess
import sys
from typing import Any

from openai import OpenAI


# 原型阶段按需求硬编码 API 配置。
BASE_URL = "https://njusehub.info/v1"
API_KEY = "[REDACTED-HISTORICAL-TOKEN]"

MAX_TOOL_ROUNDS = 10
SHELL_TIMEOUT_SECONDS = 60


client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a command in PowerShell and return stdout, stderr, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The PowerShell command to execute.",
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }
]


def pick_default_model() -> str:
    """启动时列出模型，并选择 deepseek + v4/flash 相关的模型。"""
    models = list(client.models.list().data)

    def model_id(item: Any) -> str:
        return str(getattr(item, "id", ""))

    preferred = [
        model_id(model)
        for model in models
        if "deepseek" in model_id(model).lower()
        and ("v4" in model_id(model).lower() or "flash" in model_id(model).lower())
    ]
    fallback_deepseek = [
        model_id(model) for model in models if "deepseek" in model_id(model).lower()
    ]
    fallback_any = [model_id(model) for model in models if model_id(model)]

    if preferred:
        selected = preferred[0]
    elif fallback_deepseek:
        selected = fallback_deepseek[0]
    elif fallback_any:
        selected = fallback_any[0]
    else:
        raise RuntimeError("models.list() 没有返回可用模型")

    print(f"实际选用的 model id: {selected}", flush=True)
    return selected


def get_powershell_executable() -> str:
    """优先使用 PowerShell 7 的 pwsh，不存在时回退到 Windows PowerShell。"""
    return shutil.which("pwsh") or shutil.which("powershell.exe") or "powershell.exe"


def run_shell(command: str) -> str:
    """通过 subprocess 执行 PowerShell 命令，并把结果整理成 tool 消息文本。"""
    print(f"模型想执行的命令: {command}", flush=True)

    shell = get_powershell_executable()
    completed = subprocess.run(
        [
            shell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SHELL_TIMEOUT_SECONDS,
    )

    return json.dumps(
        {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
        ensure_ascii=False,
    )


def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    """解析模型返回的 tool_call 参数，解析失败时返回空参数。"""
    try:
        parsed = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    if len(sys.argv) < 2:
        print('用法: uv run agent.py "这里是任务描述"')
        return 2

    task = " ".join(sys.argv[1:]).strip()
    if not task:
        print("任务描述不能为空")
        return 2

    try:
        model = pick_default_model()
    except Exception as exc:
        print(f"获取模型列表失败: {exc}")
        return 1

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a minimal one-shot agent. Use the run_shell tool only when "
                "the user's task requires inspecting or changing local files, running "
                "commands, or reading command output. If no tool is needed, answer directly."
            ),
        },
        {"role": "user", "content": task},
    ]

    tool_rounds = 0

    while True:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
        )
        assistant_message = response.choices[0].message
        tool_calls = assistant_message.tool_calls or []

        messages.append(assistant_message.model_dump(exclude_none=True))

        if not tool_calls:
            final_text = assistant_message.content or ""
            print(final_text)
            return 0

        tool_rounds += 1
        if tool_rounds > MAX_TOOL_ROUNDS:
            print(f"已超过最多 {MAX_TOOL_ROUNDS} 轮工具调用上限，退出。")
            return 1

        for tool_call in tool_calls:
            if tool_call.function.name != "run_shell":
                tool_result = json.dumps(
                    {"error": f"未知工具: {tool_call.function.name}"},
                    ensure_ascii=False,
                )
            else:
                arguments = parse_tool_arguments(tool_call.function.arguments)
                command = str(arguments.get("command", "")).strip()
                if command:
                    try:
                        tool_result = run_shell(command)
                    except subprocess.TimeoutExpired:
                        tool_result = json.dumps(
                            {
                                "command": command,
                                "error": f"命令执行超过 {SHELL_TIMEOUT_SECONDS} 秒",
                            },
                            ensure_ascii=False,
                        )
                else:
                    tool_result = json.dumps(
                        {"error": "run_shell 缺少 command 参数"},
                        ensure_ascii=False,
                    )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
