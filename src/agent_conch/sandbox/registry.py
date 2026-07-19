"""E 层: 沙箱后端注册表.

选择策略:
- SandboxRegistry: 根据 sandbox.mode 决定后端
- mode: "non-main" (非主会话用沙箱) | "always" | "never"
- 可插拔: 注册不同后端 (local/docker/ssh)
"""

from __future__ import annotations

from agent_conch.sandbox.local import LocalBackend, SandboxBackend


class SandboxMode:
    """沙箱模式."""

    NON_MAIN = "non-main"  # 非主会话用沙箱
    ALWAYS = "always"  # 总是用沙箱
    NEVER = "never"  # 从不用沙箱


class SandboxRegistry:
    """沙箱后端注册表.

    管理多个后端, 根据 session 类型 + 配置模式选择后端.
    """

    def __init__(self, mode: str = SandboxMode.NON_MAIN):
        self.mode = mode
        self._backends: dict[str, SandboxBackend] = {}
        self._default_backend_name = "local"

        # 始终注册 LocalBackend 作为回退后端。
        self.register("local", LocalBackend())

    def register(self, name: str, backend: SandboxBackend) -> None:
        """注册沙箱后端."""
        self._backends[name] = backend

    def get_backend(self, session_id: str = "", is_main: bool = True) -> SandboxBackend:
        """获取沙箱后端.

        根据 mode 和 is_main 决定:
        - NEVER: 始终返回 local (无隔离)
        - ALWAYS: 始终返回默认隔离后端，缺失时回退 local
        - NON_MAIN: 主会话返回 local，子会话返回默认隔离后端
        """
        if self.mode == SandboxMode.NEVER:
            return self._backends["local"]

        if self.mode == SandboxMode.ALWAYS:
            # 默认后端不可用时回退 local。
            return self._backends.get(self._default_backend_name, self._backends["local"])

        # NON_MAIN
        if is_main:
            return self._backends["local"]
        # 子会话使用默认沙箱；未配置时回退 local。
        return self._backends.get(self._default_backend_name, self._backends["local"])

    def set_default(self, name: str) -> None:
        """设置默认后端."""
        if name not in self._backends:
            raise ValueError(f"Backend '{name}' not registered")
        self._default_backend_name = name

    def list_backends(self) -> list[str]:
        """列出已注册的后端."""
        return list(self._backends.keys())

    async def health_check(self) -> dict[str, bool]:
        """检查所有后端可用性."""
        result = {}
        for name, backend in self._backends.items():
            result[name] = await backend.is_available()
        return result
