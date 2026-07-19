"""E/G 层：HTTP 出站网络白名单。"""

from __future__ import annotations

import fnmatch
import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class NetworkDecision:
    allowed: bool
    reason: str


@dataclass
class NetworkPolicy:
    """按主机名/CIDR 控制 HTTP(S) 出站；未启用时保持向后兼容。"""

    enforce: bool = False
    allowlist: list[str] = field(default_factory=list)

    def evaluate_url(self, url: str) -> NetworkDecision:
        if not self.enforce:
            return NetworkDecision(True, "network allowlist disabled")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return NetworkDecision(False, "only HTTP(S) URLs with a hostname are allowed")
        host = parsed.hostname.lower().rstrip(".")
        for entry in self.allowlist:
            candidate = entry.strip().lower().rstrip(".")
            if not candidate:
                continue
            if self._matches(host, candidate):
                return NetworkDecision(True, f"host '{host}' matched network allowlist")
        return NetworkDecision(False, f"host '{host}' is not in the network allowlist")

    @staticmethod
    def _matches(host: str, entry: str) -> bool:
        if "/" in entry:
            try:
                return ipaddress.ip_address(host) in ipaddress.ip_network(entry, strict=False)
            except ValueError:
                return False
        return fnmatch.fnmatchcase(host, entry)

    def require_url(self, url: str) -> None:
        decision = self.evaluate_url(url)
        if not decision.allowed:
            raise PermissionError(decision.reason)
