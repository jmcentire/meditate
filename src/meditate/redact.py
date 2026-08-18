"""Local secret detection and irreversible redaction."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .models import RedactionFinding
from .util import sha256_text


@dataclass(frozen=True)
class SanitizedText:
    text: str
    findings: tuple[RedactionFinding, ...]
    truncated: bool = False

    @property
    def has_high_confidence(self) -> bool:
        return any(item.confidence == "high" for item in self.findings)


_PEM = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.DOTALL,
)
_HEADER = re.compile(
    r"(?im)^(?P<prefix>\s*(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)"
    r"(?P<value>[^\r\n]+)$"
)
_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"secret|password|passwd|session(?:[_-]?id)?|cookie)\b\s*[:=]\s*[\"']?)"
    r"(?P<value>(?!\[REDACTED)[A-Za-z0-9._~+/=-]{8,})"
)
_PREFIXED = re.compile(
    r"\b(?:sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_URL_USERINFO = re.compile(r"(?P<scheme>https?://)(?P<userinfo>[^\s/@:]+:[^\s/@]+)@", re.IGNORECASE)
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_ENTROPY_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_+/=-]{40,}(?![A-Za-z0-9_-])")


def _placeholder(kind: str, value: str) -> str:
    return f"[REDACTED:{kind}:{sha256_text(value)[:10]}]"


def _finding(kind: str, confidence: str, value: str) -> RedactionFinding:
    chosen: Literal["high", "low"] = "high" if confidence == "high" else "low"
    return RedactionFinding(kind=kind, confidence=chosen, digest=sha256_text(value))


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def sanitize_text(text: str, *, max_chars: int) -> SanitizedText:
    """Redact locally, then bound the retained excerpt.

    Findings contain only type, confidence, and a one-way digest. Original
    secret bytes are never retained in a report model.
    """

    clean = text.replace("\x00", "�")
    findings: list[RedactionFinding] = []

    def replace_whole(kind: str, confidence: str) -> Callable[[re.Match[str]], str]:
        def inner(match: re.Match[str]) -> str:
            value = match.group(0)
            findings.append(_finding(kind, confidence, value))
            return _placeholder(kind, value)

        return inner

    clean = _PEM.sub(replace_whole("private_key", "high"), clean)

    def replace_named(
        kind: str, confidence: str, prefix_group: str, value_group: str
    ) -> Callable[[re.Match[str]], str]:
        def inner(match: re.Match[str]) -> str:
            value = match.group(value_group)
            findings.append(_finding(kind, confidence, value))
            return f"{match.group(prefix_group)}{_placeholder(kind, value)}"

        return inner

    clean = _HEADER.sub(replace_named("credential_header", "high", "prefix", "value"), clean)
    clean = _ASSIGNMENT.sub(
        replace_named("credential_assignment", "high", "prefix", "value"), clean
    )
    clean = _URL_USERINFO.sub(replace_named("url_userinfo", "high", "scheme", "userinfo"), clean)
    clean = _PREFIXED.sub(replace_whole("api_key", "high"), clean)
    clean = _JWT.sub(replace_whole("jwt", "high"), clean)
    clean = _UUID.sub(replace_whole("uuid", "low"), clean)

    def replace_entropy(match: re.Match[str]) -> str:
        value = match.group(0)
        if value.startswith("[REDACTED") or _entropy(value) < 4.25:
            return value
        findings.append(_finding("high_entropy", "low", value))
        return _placeholder("high_entropy", value)

    clean = _ENTROPY_TOKEN.sub(replace_entropy, clean)
    clean = "".join(character for character in clean if character in "\n\t" or ord(character) >= 32)

    truncated = len(clean) > max_chars
    if truncated:
        half = max(1, (max_chars - 42) // 2)
        clean = f"{clean[:half]}\n[TRUNCATED:{len(clean) - 2 * half} chars]\n{clean[-half:]}"
    return SanitizedText(text=clean, findings=tuple(findings), truncated=truncated)


def surviving_high_confidence(text: str) -> tuple[RedactionFinding, ...]:
    """Return high-confidence shapes still present after sanitization."""

    findings: list[RedactionFinding] = []
    for kind, pattern in (
        ("private_key", _PEM),
        ("credential_header", _HEADER),
        ("credential_assignment", _ASSIGNMENT),
        ("api_key", _PREFIXED),
        ("jwt", _JWT),
        ("url_userinfo", _URL_USERINFO),
    ):
        for match in pattern.finditer(text):
            value = match.group(0)
            if "[REDACTED:" not in value:
                findings.append(_finding(kind, "high", value))
    return tuple(findings)
