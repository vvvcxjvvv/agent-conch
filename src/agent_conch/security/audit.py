"""G 层：P3 安全审计与 Dangerous Config Detection。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class AuditFinding:
    code: str
    severity: str
    message: str
    path: str


class SecurityAudit:
    """对配置执行确定性、可测试的安全扫描。"""

    SECRET_KEYS = {"api_key", "token", "password", "secret"}

    def scan(self, config: dict[str, Any]) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        self._scan_values(config, "", findings)

        sandbox = config.get("sandbox") or {}
        if sandbox.get("mode") == "never":
            findings.append(
                AuditFinding(
                    "SANDBOX_DISABLED",
                    "high",
                    "Sandbox mode 'never' permits host execution",
                    "sandbox.mode",
                )
            )
        if sandbox.get("default_backend") == "docker" and sandbox.get("network") == "host":
            findings.append(
                AuditFinding(
                    "DOCKER_HOST_NETWORK",
                    "high",
                    "Docker host networking weakens isolation",
                    "sandbox.network",
                )
            )
        allowed_roots = sandbox.get("allowed_roots") or []
        if "/" in allowed_roots:
            findings.append(
                AuditFinding(
                    "ROOT_FILESYSTEM_ALLOWED",
                    "critical",
                    "Sandbox allowed_roots exposes the entire host filesystem",
                    "sandbox.allowed_roots",
                )
            )

        api = config.get("api") or {}
        if api.get("host") in {"0.0.0.0", "::"}:
            findings.append(
                AuditFinding(
                    "PUBLIC_API_BIND",
                    "medium",
                    "API is reachable from external network interfaces",
                    "api.host",
                )
            )

        layers = set((config.get("layers") or {}).get("enabled") or [])
        verification = config.get("verification") or {}
        if "verification" in layers and not verification.get("commands"):
            findings.append(
                AuditFinding(
                    "EMPTY_VERIFICATION_GATE",
                    "high",
                    "VerificationLayer is enabled without deterministic checks",
                    "verification.commands",
                )
            )

        quota = config.get("quota") or {}
        if "llm_quota" in layers and int(quota.get("max_tokens", 0)) <= 0:
            findings.append(
                AuditFinding(
                    "INVALID_LLM_QUOTA",
                    "high",
                    "LLM quota must be a positive token count",
                    "quota.max_tokens",
                )
            )

        api_base = str((config.get("model") or {}).get("api_base") or "")
        parsed = urlparse(api_base)
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            findings.append(
                AuditFinding(
                    "INSECURE_MODEL_ENDPOINT",
                    "high",
                    "Remote model endpoint uses unencrypted HTTP",
                    "model.api_base",
                )
            )
        return findings

    def _scan_values(
        self,
        value: Any,
        path: str,
        findings: list[AuditFinding],
    ) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if str(key).lower() in self.SECRET_KEYS and isinstance(child, str) and child:
                    findings.append(
                        AuditFinding(
                            "INLINE_SECRET",
                            "critical",
                            "Secret-like value must be referenced through an environment variable",
                            child_path,
                        )
                    )
                self._scan_values(child, child_path, findings)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._scan_values(child, f"{path}[{index}]", findings)
