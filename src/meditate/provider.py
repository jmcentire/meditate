"""Bounded Anthropic provider with no model fallback and redacted failures."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from .config import Config
from .models import RunUsage
from .util import fail


@dataclass(frozen=True)
class SecretValue:
    value: str
    source: str

    def __str__(self) -> str:
        return "[REDACTED]"

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"


class Provider(Protocol):
    name: str
    model: str

    def complete(
        self, *, system: str, payload: str, schema: dict[str, Any]
    ) -> tuple[str, RunUsage]: ...


def _env_file(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail("env_file_missing", f"Configured env file does not exist: {path}")
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        fail("unsafe_env_file", f"Env file must be a regular non-symlink: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        fail("unsafe_env_file_mode", f"Env file must be mode 0600: {path}")
    values: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            fail("invalid_env_file", f"Invalid KEY=value line {line_no} in {path}")
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"'")
        if not name.replace("_", "").isalnum() or not name[:1].isalpha():
            fail("invalid_env_file", f"Invalid variable name on line {line_no} in {path}")
        values[name] = value
    return values


def resolve_anthropic_key(config: Config) -> tuple[SecretValue, tuple[str, ...]]:
    file_values = _env_file(config.env_file)
    warnings: list[str] = []

    def lookup(name: str) -> str:
        return os.environ.get(name, "").strip() or file_values.get(name, "").strip()

    value = lookup("ANTHROPIC_API_KEY")
    if value:
        return SecretValue(value, "ANTHROPIC_API_KEY"), tuple(warnings)
    fail("anthropic_key_missing", "No Anthropic key found in ANTHROPIC_API_KEY")


def _safe_error(exc: BaseException, secret: SecretValue) -> str:
    message = str(exc).replace(secret.value, "[REDACTED]")
    return f"{type(exc).__name__}: {message[:1000]}"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, config: Config) -> None:
        try:
            import anthropic
        except ImportError:
            fail("anthropic_sdk_missing", "Install the anthropic package to run `meditate plan`")
        self._anthropic = anthropic
        self._secret, self.warnings = resolve_anthropic_key(config)
        self.model = config.llm.model
        self.max_tokens = config.llm.max_output_tokens
        self.timeout = config.llm.timeout_seconds
        self.effort = config.llm.effort
        self.client = anthropic.Anthropic(api_key=self._secret.value, timeout=self.timeout)

    def complete(
        self, *, system: str, payload: str, schema: dict[str, Any]
    ) -> tuple[str, RunUsage]:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.0,
                system=system,
                messages=cast(Any, [{"role": "user", "content": payload}]),
                output_config=cast(
                    Any,
                    {
                        "effort": self.effort,
                        "format": {"type": "json_schema", "schema": schema},
                    },
                ),
            )
        except Exception as exc:
            fail(
                "provider_error",
                f"Anthropic request failed for {self.model}: {_safe_error(exc, self._secret)}",
            )
        pieces: list[str] = []
        for block in response.content:
            value = getattr(block, "text", None)
            if getattr(block, "type", "") == "text" and isinstance(value, str):
                pieces.append(value)
        if not pieces:
            fail("provider_empty", f"Anthropic model {self.model} returned no text")
        stop_reason = str(response.stop_reason or "")
        if stop_reason == "max_tokens":
            fail("provider_truncated", f"Anthropic model {self.model} exhausted max_output_tokens")
        response_model = getattr(response, "model", "")
        usage = RunUsage(
            calls=1,
            actual_input_tokens=int(getattr(response.usage, "input_tokens", 0)),
            actual_output_tokens=int(getattr(response.usage, "output_tokens", 0)),
            stop_reason=stop_reason,
            model_id=(
                response_model if isinstance(response_model, str) and response_model else self.model
            ),
        )
        return "".join(pieces), usage


def create_provider(config: Config) -> Provider:
    if config.llm.provider == "anthropic":
        return AnthropicProvider(config)
    fail("unsupported_provider", f"Unsupported provider: {config.llm.provider}")
