"""Versioned TOML configuration with explicit writable targets."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .util import (
    SCHEMA_VERSION,
    MeditateError,
    atomic_write,
    display_path,
    ensure_not_foreign_root,
    fail,
    sha256_bytes,
)

DEFAULT_CODEX_PROJECT_DOC_MAX_BYTES = 32_768


@dataclass(frozen=True)
class SourceConfig:
    agents: tuple[str, ...] = ("claude",)
    claude_home: Path = Path("~/.claude")
    codex_home: Path = Path("~/.codex")
    include_auto_memory: bool = True
    include_transcripts: bool = False
    max_events: int = 180
    max_excerpt_chars: int = 700
    max_jsonl_line_bytes: int = 1_000_000
    max_transcript_files: int = 20
    lookback_days: int = 0


@dataclass(frozen=True)
class KindexConfig:
    enabled: bool = True
    command: str = "kin"
    queries: tuple[str, ...] = (
        "agent behavior user preferences working style",
        "commit merge push deploy cleanup",
        "safety destructive actions verification",
    )
    max_results: int = 20


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    effort: str = "high"
    max_input_tokens: int = 80_000
    max_output_tokens: int = 8_192
    max_total_input_tokens: int = 80_000
    max_total_output_tokens: int = 8_192
    max_calls: int = 1
    timeout_seconds: int = 300


@dataclass(frozen=True)
class SafetyConfig:
    protected_headings: tuple[str, ...] = ()
    size_floor_ratio: float = 0.40
    size_ceiling_ratio: float = 1.20
    max_churn_ratio: float = 0.65
    max_malformed_ratio: float = 0.02
    minimum_free_bytes: int = 5_000_000


@dataclass(frozen=True)
class VerificationConfig:
    suite: Path | None = None
    agent: str = "claude"
    model: str = ""
    repeats: int = 3
    timeout_seconds: int = 180
    max_output_chars: int = 20_000


@dataclass(frozen=True)
class ApplyConfig:
    allow_unattended_apply: bool = False
    minimum_attended_applies: int = 3
    unattended_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetentionConfig:
    derived_days: int = 30


@dataclass(frozen=True)
class Config:
    config_path: Path
    targets: tuple[Path, ...]
    data_root: Path
    state_root: Path
    cache_root: Path
    env_file: Path | None
    sources: SourceConfig
    kindex: KindexConfig
    llm: LLMConfig
    safety: SafetyConfig
    verification: VerificationConfig
    apply: ApplyConfig
    retention: RetentionConfig
    raw_bytes: bytes

    @property
    def hash(self) -> str:
        return sha256_bytes(self.raw_bytes)

    @property
    def allowed_targets(self) -> set[Path]:
        return {target.expanduser().absolute() for target in self.targets}


def default_config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "meditate" / "config.toml"


def default_config_text() -> str:
    return """# Meditate configuration (schema version 1)
schema_version = 1
targets = ["~/.claude/CLAUDE.md"]
# Optional mode-0600 KEY=value file for cron. Prefer your normal shell profile
# for interactive runs. Never commit this file.
env_file = ""

[paths]
data_root = "~/.local/share/meditate"
state_root = "~/.local/state/meditate"
cache_root = "~/.cache/meditate"

[sources]
agents = ["claude"] # claude, codex, or both
claude_home = "~/.claude"
codex_home = "~/.codex"
include_auto_memory = true
include_transcripts = false
max_events = 180
max_excerpt_chars = 700
max_jsonl_line_bytes = 1000000
max_transcript_files = 20
lookback_days = 0

[kindex]
# When enabled and `kin` is installed, every configured search is required.
# A failed search or node read aborts before planning rather than silently
# dropping the durable evidence source.
enabled = true
command = "kin"
queries = [
  "agent behavior user preferences working style",
  "commit merge push deploy cleanup",
  "safety destructive actions verification",
]
max_results = 20

[llm]
provider = "anthropic"
model = "claude-sonnet-4-6"
effort = "high"
max_input_tokens = 80000
max_output_tokens = 8192
max_total_input_tokens = 80000
max_total_output_tokens = 8192
max_calls = 1
timeout_seconds = 300

[safety]
protected_headings = []
size_floor_ratio = 0.40
size_ceiling_ratio = 1.20
max_churn_ratio = 0.65
max_malformed_ratio = 0.02
minimum_free_bytes = 5000000

[verification]
# Owner-authored JSON suite. It is never sent to the consolidation planner.
suite = ""
agent = "claude" # claude or codex
model = ""
repeats = 3
timeout_seconds = 180
max_output_chars = 20000

[apply]
# Compatibility fields retained in schema version 1. They do not bypass the
# owner-defined semantic qualification gate. A changed plan still needs its own
# passed, hash-bound verification receipt before any apply mode can write.
allow_unattended_apply = false
minimum_attended_applies = 3
# Evidence allowlisting records review provenance but cannot establish behavioral
# equivalence or substitute for the owner suite.
unattended_evidence_ids = []

[retention]
derived_days = 30
"""


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        fail("invalid_config", f"[{name}] must be a TOML table")
    return value


def _path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        fail("invalid_config", f"{field} must be a non-empty path string")
    return Path(value).expanduser().absolute()


def _positive(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        fail("invalid_config", f"{field} must be a positive integer")
    return value


def _nonnegative(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        fail("invalid_config", f"{field} must be a non-negative integer")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        fail("invalid_config", f"{field} must be true or false")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail("invalid_config", f"{field} must be a non-empty string")
    return value.strip()


def load_config(path: Path | None = None) -> Config:
    selected = (path or default_config_path()).expanduser().absolute()
    try:
        payload = selected.read_bytes()
        raw = tomllib.loads(payload.decode("utf-8"))
    except FileNotFoundError:
        fail("config_missing", f"Configuration not found: {selected}; run `meditate init`")
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        fail("invalid_config", f"Invalid TOML in {selected}: {exc}")

    if raw.get("schema_version") != SCHEMA_VERSION:
        fail("config_schema", f"Expected schema_version = {SCHEMA_VERSION}")
    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        fail("invalid_config", "targets must be a non-empty array")
    targets = tuple(_path(item, "targets[]") for item in targets_raw)
    if len(set(targets)) != len(targets):
        fail("invalid_config", "targets contains duplicate paths")

    paths = _table(raw, "paths")
    sources_raw = _table(raw, "sources")
    kindex_raw = _table(raw, "kindex")
    llm_raw = _table(raw, "llm")
    safety_raw = _table(raw, "safety")
    verification_raw = _table(raw, "verification")
    apply_raw = _table(raw, "apply")
    retention_raw = _table(raw, "retention")

    agents = tuple(str(item).lower() for item in sources_raw.get("agents", ["claude"]))
    if not agents or any(item not in {"claude", "codex"} for item in agents):
        fail("invalid_config", "sources.agents may contain only claude and codex")

    source = SourceConfig(
        agents=agents,
        claude_home=_path(sources_raw.get("claude_home", "~/.claude"), "sources.claude_home"),
        codex_home=_path(sources_raw.get("codex_home", "~/.codex"), "sources.codex_home"),
        include_auto_memory=_boolean(
            sources_raw.get("include_auto_memory", True), "sources.include_auto_memory"
        ),
        include_transcripts=_boolean(
            sources_raw.get("include_transcripts", False), "sources.include_transcripts"
        ),
        max_events=_positive(sources_raw.get("max_events", 180), "sources.max_events"),
        max_excerpt_chars=_positive(
            sources_raw.get("max_excerpt_chars", 700), "sources.max_excerpt_chars"
        ),
        max_jsonl_line_bytes=_positive(
            sources_raw.get("max_jsonl_line_bytes", 1_000_000),
            "sources.max_jsonl_line_bytes",
        ),
        max_transcript_files=_positive(
            sources_raw.get("max_transcript_files", 20), "sources.max_transcript_files"
        ),
        lookback_days=int(sources_raw.get("lookback_days", 0)),
    )
    if source.lookback_days < 0:
        fail("invalid_config", "sources.lookback_days cannot be negative")

    queries_raw = kindex_raw.get("queries", list(KindexConfig().queries))
    if not isinstance(queries_raw, list) or not all(isinstance(item, str) for item in queries_raw):
        fail("invalid_config", "kindex.queries must be an array of strings")
    kindex = KindexConfig(
        enabled=_boolean(kindex_raw.get("enabled", True), "kindex.enabled"),
        command=_string(kindex_raw.get("command", "kin"), "kindex.command"),
        queries=tuple(queries_raw),
        max_results=_positive(kindex_raw.get("max_results", 20), "kindex.max_results"),
    )
    llm = LLMConfig(
        provider=_string(llm_raw.get("provider", "anthropic"), "llm.provider"),
        model=_string(llm_raw.get("model", "claude-sonnet-4-6"), "llm.model"),
        effort=_string(llm_raw.get("effort", "high"), "llm.effort"),
        max_input_tokens=_positive(llm_raw.get("max_input_tokens", 80_000), "llm.max_input_tokens"),
        max_output_tokens=_positive(
            llm_raw.get("max_output_tokens", 8_192), "llm.max_output_tokens"
        ),
        max_total_input_tokens=_positive(
            llm_raw.get("max_total_input_tokens", 80_000), "llm.max_total_input_tokens"
        ),
        max_total_output_tokens=_positive(
            llm_raw.get("max_total_output_tokens", 8_192), "llm.max_total_output_tokens"
        ),
        max_calls=_positive(llm_raw.get("max_calls", 1), "llm.max_calls"),
        timeout_seconds=_positive(llm_raw.get("timeout_seconds", 300), "llm.timeout_seconds"),
    )
    if llm.provider != "anthropic":
        fail("unsupported_provider", "This release supports provider = 'anthropic' only")
    if llm.effort not in {"low", "medium", "high", "xhigh", "max"}:
        fail("invalid_config", "llm.effort must be low, medium, high, xhigh, or max")

    protected = safety_raw.get("protected_headings", [])
    if not isinstance(protected, list) or not all(isinstance(item, str) for item in protected):
        fail("invalid_config", "safety.protected_headings must be an array of strings")
    safety = SafetyConfig(
        protected_headings=tuple(protected),
        size_floor_ratio=float(safety_raw.get("size_floor_ratio", 0.40)),
        size_ceiling_ratio=float(safety_raw.get("size_ceiling_ratio", 1.20)),
        max_churn_ratio=float(safety_raw.get("max_churn_ratio", 0.65)),
        max_malformed_ratio=float(safety_raw.get("max_malformed_ratio", 0.02)),
        minimum_free_bytes=_positive(
            safety_raw.get("minimum_free_bytes", 5_000_000), "safety.minimum_free_bytes"
        ),
    )
    if not (0 < safety.size_floor_ratio <= 1 <= safety.size_ceiling_ratio):
        fail("invalid_config", "safety size ratios must satisfy 0 < floor <= 1 <= ceiling")
    if not (0 <= safety.max_churn_ratio <= 1 and 0 <= safety.max_malformed_ratio <= 1):
        fail("invalid_config", "safety ratios must be between zero and one")

    env_raw = raw.get("env_file", "")
    env_file = (
        Path(env_raw).expanduser().absolute() if isinstance(env_raw, str) and env_raw else None
    )
    unattended_ids_raw = apply_raw.get("unattended_evidence_ids", [])
    if not isinstance(unattended_ids_raw, list) or not all(
        isinstance(item, str) and item.startswith("evt_") and len(item) > 4
        for item in unattended_ids_raw
    ):
        fail("invalid_config", "apply.unattended_evidence_ids must contain evidence IDs")
    if len(set(unattended_ids_raw)) != len(unattended_ids_raw):
        fail("invalid_config", "apply.unattended_evidence_ids contains duplicates")

    suite_raw = verification_raw.get("suite", "")
    if not isinstance(suite_raw, str):
        fail("invalid_config", "verification.suite must be a path string")
    verification_agent = _string(
        verification_raw.get("agent", "claude"), "verification.agent"
    ).casefold()
    if verification_agent not in {"claude", "codex"}:
        fail("invalid_config", "verification.agent must be claude or codex")
    verification_model_raw = verification_raw.get("model", "")
    if not isinstance(verification_model_raw, str):
        fail("invalid_config", "verification.model must be a string")

    config = Config(
        config_path=selected,
        targets=targets,
        data_root=_path(paths.get("data_root", "~/.local/share/meditate"), "paths.data_root"),
        state_root=_path(paths.get("state_root", "~/.local/state/meditate"), "paths.state_root"),
        cache_root=_path(paths.get("cache_root", "~/.cache/meditate"), "paths.cache_root"),
        env_file=env_file,
        sources=source,
        kindex=kindex,
        llm=llm,
        safety=safety,
        verification=VerificationConfig(
            suite=(Path(suite_raw).expanduser().absolute() if suite_raw.strip() else None),
            agent=verification_agent,
            model=verification_model_raw.strip(),
            repeats=_positive(verification_raw.get("repeats", 3), "verification.repeats"),
            timeout_seconds=_positive(
                verification_raw.get("timeout_seconds", 180),
                "verification.timeout_seconds",
            ),
            max_output_chars=_positive(
                verification_raw.get("max_output_chars", 20_000),
                "verification.max_output_chars",
            ),
        ),
        apply=ApplyConfig(
            allow_unattended_apply=_boolean(
                apply_raw.get("allow_unattended_apply", False),
                "apply.allow_unattended_apply",
            ),
            minimum_attended_applies=_nonnegative(
                apply_raw.get("minimum_attended_applies", 3),
                "apply.minimum_attended_applies",
            ),
            unattended_evidence_ids=tuple(unattended_ids_raw),
        ),
        retention=RetentionConfig(
            derived_days=_nonnegative(
                retention_raw.get("derived_days", 30), "retention.derived_days"
            )
        ),
        raw_bytes=payload,
    )
    ensure_not_foreign_root(Path.home())
    return config


def with_llm_overrides(
    config: Config,
    *,
    model: str | None = None,
    effort: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_total_input_tokens: int | None = None,
    max_total_output_tokens: int | None = None,
) -> Config:
    for value, field in (
        (max_input_tokens, "max_input_tokens"),
        (max_output_tokens, "max_output_tokens"),
        (max_total_input_tokens, "max_total_input_tokens"),
        (max_total_output_tokens, "max_total_output_tokens"),
    ):
        if value is not None and value < 1:
            fail("invalid_override", f"{field} must be positive")
    selected_effort = effort or config.llm.effort
    if selected_effort not in {"low", "medium", "high", "xhigh", "max"}:
        fail("invalid_override", "effort must be low, medium, high, xhigh, or max")
    llm = replace(
        config.llm,
        model=model or config.llm.model,
        effort=selected_effort,
        max_input_tokens=(
            max_input_tokens if max_input_tokens is not None else config.llm.max_input_tokens
        ),
        max_output_tokens=(
            max_output_tokens if max_output_tokens is not None else config.llm.max_output_tokens
        ),
        max_total_input_tokens=(
            max_total_input_tokens
            if max_total_input_tokens is not None
            else max_input_tokens
            if max_input_tokens is not None
            else config.llm.max_total_input_tokens
        ),
        max_total_output_tokens=(
            max_total_output_tokens
            if max_total_output_tokens is not None
            else max_output_tokens
            if max_output_tokens is not None
            else config.llm.max_total_output_tokens
        ),
    )
    return replace(config, llm=llm)


def resolve_codex_project_doc_max_bytes(config: Config) -> tuple[int, str]:
    """Resolve Codex's configured project-instruction byte budget conservatively."""

    path = config.sources.codex_home / "config.toml"
    try:
        if path.is_symlink() or not path.is_file():
            return DEFAULT_CODEX_PROJECT_DOC_MAX_BYTES, "default"
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return DEFAULT_CODEX_PROJECT_DOC_MAX_BYTES, "default"
    value = raw.get("project_doc_max_bytes")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return DEFAULT_CODEX_PROJECT_DOC_MAX_BYTES, "default"
    return value, display_path(path)


def write_default_config(path: Path, *, force: bool = False) -> None:
    selected = path.expanduser().absolute()
    if selected.exists() and not force:
        raise MeditateError("config_exists", f"Configuration already exists: {selected}")
    if selected.exists() and selected.is_symlink():
        fail("symlink_config", f"Refusing to overwrite symlinked config: {selected}")
    atomic_write(selected, default_config_text().encode("utf-8"), mode=0o600)
