"""端到端 Demo：模拟一个完整的 coding agent 行为序列。

无需真实 LLM API，用 ScriptedProvider 预设：
  1. 调用 read_file 读取 hello.py
  2. 分析发现语法错误
  3. 调用 write_file 修复
  4. 确认完成

验证全链路：Profile 加载 → Loop → 推理(工具决策) → 权限校验 → 工具执行 → 轨迹 → 评测
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    # 确保域注册
    import conch.domains  # noqa: F401

    from conch.core.loop import AgentLoop, TaskStatus
    from conch.core.profile import ProfileLoader
    from conch.core.registry import registry
    from conch.runtime.model.scripted import ScriptedProvider

    # 先创建测试文件
    test_file = Path("demo_hello.py")
    test_file.write_text("print('hello world'\n", encoding="utf-8")

    # 预设 Agent 行为脚本
    provider = ScriptedProvider([
        # Step 1: 读文件
        {"tool_call": {"name": "read_file", "args": {"path": str(test_file)}}},
        # Step 2: 分析
        {"content": "Found syntax error: missing closing parenthesis on line 1. Fixing..."},
        # Step 3: 写修复后的文件
        {"tool_call": {"name": "write_file", "args": {
            "path": str(test_file),
            "content": "print('hello world')\n",
        }}},
        # Step 4: 确认完成
        {"content": "Fixed! The syntax error has been resolved."},
    ])

    # 加载 Profile
    loader = ProfileLoader("profiles")
    profile = loader.load("coding-agent-v1")

    # 构建 Loop
    loop = AgentLoop(
        profile=profile,
        registry=registry,
        model=provider,
    )

    # 执行
    task = "Fix the syntax error in demo_hello.py"
    print(f"Task: {task}\n")
    state = await loop.run(task)

    # 结果
    print(f"\n{'='*50}")
    print(f"Status:  {state.status.value}")
    print(f"Steps:   {state.steps}")
    print(f"Tokens:  {state.total_tokens}")
    print(f"Cost:    ${state.total_cost:.4f}")
    print(f"Actions: {len(state.actions)}")
    for i, action in enumerate(state.actions):
        atype = action.get("type", "?")
        if atype == "tool_call":
            tool = action.get("tool", "?")
            result = action.get("result", {})
            if isinstance(result, dict):
                if result.get("error"):
                    print(f"  [{i+1}] tool={tool} ERROR: {result['error']}")
                elif result.get("content"):
                    print(f"  [{i+1}] tool={tool} content={result['content'][:60]!r}")
                elif result.get("success"):
                    print(f"  [{i+1}] tool={tool} wrote {result.get('bytes', 0)} bytes")
                else:
                    print(f"  [{i+1}] tool={tool} result={result}")
            else:
                print(f"  [{i+1}] tool={tool}")
        else:
            content = action.get("content", "")
            print(f"  [{i+1}] text: {content[:60]!r}")

    # 验证修复结果
    print(f"\n{'='*50}")
    fixed_content = test_file.read_text(encoding="utf-8")
    print(f"File content after fix: {fixed_content!r}")
    if fixed_content == "print('hello world')\n":
        print("VERIFY: File correctly fixed!")
    else:
        print("VERIFY: File NOT fixed correctly")

    # 清理
    test_file.unlink()

    return 0 if state.status == TaskStatus.DONE else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
