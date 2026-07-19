"""G 层：仅保存引用的 Credential Pool 与轮换策略。"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

SecretResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class CredentialRef:
    alias: str
    provider: str
    reference: str
    backend: str = "env"
    priority: int = 100


@dataclass(frozen=True)
class CredentialLease:
    alias: str
    provider: str
    secret: str
    backend: str


@dataclass
class _CredentialState:
    failures: int = 0
    disabled_until: float = 0.0
    last_used_at: float = 0.0
    uses: int = 0


class CredentialPool:
    """环境变量、Bitwarden/1Password 引用统一轮换；不会持久化明文。"""

    def __init__(
        self,
        credentials: list[CredentialRef] | None = None,
        resolvers: dict[str, SecretResolver] | None = None,
        failure_cooldown: int = 60,
    ) -> None:
        self.credentials = list(credentials or [])
        self.resolvers: dict[str, SecretResolver] = {
            "env": os.environ.get,
            "bitwarden": self._bitwarden_resolver,
            "1password": self._one_password_resolver,
        }
        self.resolvers.update(resolvers or {})
        self.failure_cooldown = failure_cooldown
        self._state = {item.alias: _CredentialState() for item in self.credentials}

    def add(self, credential: CredentialRef) -> None:
        self.credentials.append(credential)
        self._state.setdefault(credential.alias, _CredentialState())

    def acquire(self, provider: str) -> CredentialLease | None:
        now = time.time()
        candidates = [
            item
            for item in self.credentials
            if item.provider == provider and self._state[item.alias].disabled_until <= now
        ]
        candidates.sort(
            key=lambda item: (
                item.priority,
                self._state[item.alias].uses,
                self._state[item.alias].last_used_at,
                item.alias,
            )
        )
        for item in candidates:
            resolver = self.resolvers.get(item.backend)
            if resolver is None:
                continue
            secret = resolver(item.reference)
            if not secret:
                continue
            state = self._state[item.alias]
            state.uses += 1
            state.last_used_at = now
            return CredentialLease(item.alias, item.provider, secret, item.backend)
        return None

    def record_success(self, alias: str) -> None:
        state = self._state.get(alias)
        if state is not None:
            state.failures = 0
            state.disabled_until = 0.0

    def record_failure(self, alias: str) -> None:
        state = self._state.get(alias)
        if state is not None:
            state.failures += 1
            state.disabled_until = time.time() + self.failure_cooldown

    def metadata(self) -> list[dict[str, object]]:
        return [
            {
                "alias": item.alias,
                "provider": item.provider,
                "backend": item.backend,
                "reference": self._redact_reference(item.reference),
                "priority": item.priority,
                "failures": self._state[item.alias].failures,
                "disabled_until": self._state[item.alias].disabled_until,
                "uses": self._state[item.alias].uses,
            }
            for item in sorted(self.credentials, key=lambda value: (value.provider, value.priority, value.alias))
        ]

    @staticmethod
    def _redact_reference(reference: str) -> str:
        if len(reference) <= 4:
            return "****"
        return reference[:2] + "***" + reference[-2:]

    @staticmethod
    def _bitwarden_resolver(reference: str) -> str | None:
        return CredentialPool._run_secret_cli(["bw", "get", "password", reference])

    @staticmethod
    def _one_password_resolver(reference: str) -> str | None:
        return CredentialPool._run_secret_cli(["op", "read", reference])

    @staticmethod
    def _run_secret_cli(command: list[str]) -> str | None:
        try:
            result = subprocess.run(  # noqa: S603 - fixed executable and argv, no shell
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        secret = result.stdout.strip()
        return secret if result.returncode == 0 and secret else None
