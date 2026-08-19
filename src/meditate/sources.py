"""Streaming readers for Claude, Codex, auto-memory, and Kindex evidence."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .models import Authority, EvidenceEvent, SourceStats
from .redact import sanitize_text, surviving_high_confidence
from .util import display_path, fail, sha256_text

_ORIGIN_SESSION = re.compile(r"originSessionId:\s*[\"']?([0-9a-fA-F-]{20,})")


def _timestamp(value: Any, fallback: float = 0.0) -> str:
    instant: datetime
    try:
        if isinstance(value, (int, float)):
            seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            instant = datetime.fromtimestamp(seconds, tz=UTC)
        elif isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            instant = datetime.fromisoformat(normalized)
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=UTC)
            instant = instant.astimezone(UTC)
        else:
            raise ValueError
    except (ValueError, TypeError, OSError, OverflowError):
        instant = datetime.fromtimestamp(max(0.0, fallback), tz=UTC)
    return instant.isoformat().replace("+00:00", "Z")


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    pieces: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        value = item.get("text") or item.get("input_text")
        if isinstance(value, str) and item.get("type") in {
            "text",
            "input_text",
            "output_text",
            None,
        }:
            pieces.append(value)
    return "\n".join(pieces)


def _make_event(
    *,
    source_kind: str,
    authority: Authority,
    timestamp: str,
    session_id: str | None,
    scope: str,
    text: str,
    locator: str,
    max_chars: int,
) -> tuple[EvidenceEvent | None, bool]:
    if not text.strip():
        return None, False
    content_hash = sha256_text(text)
    sanitized = sanitize_text(text, max_chars=max_chars)
    # Secret-bearing records are excluded wholesale. This intentionally loses
    # some evidence rather than uploading a partially understood credential dump.
    if sanitized.has_high_confidence or surviving_high_confidence(sanitized.text):
        return None, True
    stable = "\x00".join((source_kind, session_id or "", timestamp, content_hash))
    event_id = f"evt_{sha256_text(stable)[:18]}"
    return (
        EvidenceEvent(
            id=event_id,
            source_kind=source_kind,
            authority=authority,
            timestamp=timestamp,
            session_id=session_id,
            scope=scope,
            text=sanitized.text,
            source_locator=locator,
            content_sha256=content_hash,
            redactions=sanitized.findings,
        ),
        False,
    )


def _jsonl(path: Path, max_line_bytes: int) -> Iterator[tuple[int, dict[str, Any] | None, int]]:
    try:
        with path.open("rb") as handle:
            for index, raw_line in enumerate(handle, start=1):
                size = len(raw_line)
                if size > max_line_bytes:
                    yield index, None, size
                    continue
                try:
                    value = json.loads(raw_line)
                except (UnicodeError, json.JSONDecodeError):
                    yield index, None, size
                    continue
                yield index, value if isinstance(value, dict) else None, size
    except OSError:
        return


def _within_lookback(timestamp: str, days: int) -> bool:
    if days <= 0:
        return True
    try:
        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    return instant >= datetime.now(UTC) - timedelta(days=days)


def _claude_history(config: Config) -> tuple[list[EvidenceEvent], SourceStats]:
    path = config.sources.claude_home / "history.jsonl"
    if not path.exists():
        return [], SourceStats()
    events: list[EvidenceEvent] = []
    records = malformed = sensitive = bytes_seen = 0
    for line_no, record, size in _jsonl(path, config.sources.max_jsonl_line_bytes):
        records += 1
        bytes_seen += size
        if record is None:
            malformed += 1
            continue
        text = record.get("display")
        if not isinstance(text, str):
            malformed += 1
            continue
        when = _timestamp(record.get("timestamp"), path.stat().st_mtime)
        if not _within_lookback(when, config.sources.lookback_days):
            continue
        session = record.get("sessionId")
        scope = str(record.get("project") or "global")
        event, excluded = _make_event(
            source_kind="claude_history_user",
            authority=Authority.REPEATED_USER_PREFERENCE,
            timestamp=when,
            session_id=str(session) if session else None,
            scope=scope,
            text=text,
            locator=f"{display_path(path)}:{line_no}",
            max_chars=config.sources.max_excerpt_chars,
        )
        sensitive += int(excluded)
        if event:
            events.append(event)
    return events, SourceStats(
        files_seen=1,
        bytes_seen=bytes_seen,
        records_seen=records,
        records_emitted=len(events),
        malformed_records=malformed,
        sensitive_records_excluded=sensitive,
    )


def _codex_history(config: Config) -> tuple[list[EvidenceEvent], SourceStats]:
    path = config.sources.codex_home / "history.jsonl"
    if not path.exists():
        return [], SourceStats()
    events: list[EvidenceEvent] = []
    records = malformed = sensitive = bytes_seen = 0
    for line_no, record, size in _jsonl(path, config.sources.max_jsonl_line_bytes):
        records += 1
        bytes_seen += size
        if record is None or not isinstance(record.get("text"), str):
            malformed += 1
            continue
        when = _timestamp(record.get("ts"), path.stat().st_mtime)
        if not _within_lookback(when, config.sources.lookback_days):
            continue
        session = record.get("session_id")
        event, excluded = _make_event(
            source_kind="codex_history_user",
            authority=Authority.REPEATED_USER_PREFERENCE,
            timestamp=when,
            session_id=str(session) if session else None,
            scope="global",
            text=str(record["text"]),
            locator=f"{display_path(path)}:{line_no}",
            max_chars=config.sources.max_excerpt_chars,
        )
        sensitive += int(excluded)
        if event:
            events.append(event)
    return events, SourceStats(
        files_seen=1,
        bytes_seen=bytes_seen,
        records_seen=records,
        records_emitted=len(events),
        malformed_records=malformed,
        sensitive_records_excluded=sensitive,
    )


def _auto_memory(config: Config, agent: str) -> tuple[list[EvidenceEvent], SourceStats]:
    root = config.sources.claude_home if agent == "claude" else config.sources.codex_home
    if agent == "claude":
        paths = sorted(root.glob("projects/*/memory/*.md"))
    else:
        paths = sorted(root.glob("memories/**/*.md"))
    events: list[EvidenceEvent] = []
    bytes_seen = malformed = sensitive = 0
    for path in paths:
        try:
            data = path.read_text(encoding="utf-8")
            info = path.stat()
        except (OSError, UnicodeError):
            malformed += 1
            continue
        bytes_seen += info.st_size
        origin = _ORIGIN_SESSION.search(data)
        event, excluded = _make_event(
            source_kind=f"{agent}_auto_memory",
            authority=Authority.AUTO_MEMORY,
            timestamp=_timestamp(None, info.st_mtime),
            session_id=origin.group(1) if origin else None,
            scope=path.parent.parent.name,
            text=data,
            locator=display_path(path),
            max_chars=config.sources.max_excerpt_chars,
        )
        sensitive += int(excluded)
        if event:
            events.append(event)
    return events, SourceStats(
        files_seen=len(paths),
        bytes_seen=bytes_seen,
        records_seen=len(paths),
        records_emitted=len(events),
        malformed_records=malformed,
        sensitive_records_excluded=sensitive,
    )


def _recent_transcripts(root: Path, pattern: str, limit: int) -> list[Path]:
    paths = list(root.glob(pattern))
    paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return paths[:limit]


def _transcripts(config: Config, agent: str) -> tuple[list[EvidenceEvent], SourceStats]:
    if agent == "claude":
        root = config.sources.claude_home
        paths = _recent_transcripts(
            root, "projects/**/*.jsonl", config.sources.max_transcript_files
        )
    else:
        root = config.sources.codex_home
        paths = _recent_transcripts(
            root, "sessions/**/*.jsonl", config.sources.max_transcript_files
        )
    events: list[EvidenceEvent] = []
    records = malformed = unknown = sensitive = bytes_seen = 0
    for path in paths:
        fallback = path.stat().st_mtime
        inferred_session = path.stem
        for line_no, record, size in _jsonl(path, config.sources.max_jsonl_line_bytes):
            records += 1
            bytes_seen += size
            if record is None:
                malformed += 1
                continue
            text = ""
            session: str | None = inferred_session
            timestamp_value: Any = record.get("timestamp")
            if agent == "claude" and record.get("type") == "user":
                message = record.get("message", {})
                if isinstance(message, dict) and message.get("role") == "user":
                    text = _text_from_content(message.get("content"))
                    session = str(record.get("sessionId") or inferred_session)
            elif agent == "codex" and record.get("type") == "response_item":
                payload = record.get("payload", {})
                if isinstance(payload, dict) and payload.get("role") == "user":
                    text = _text_from_content(payload.get("content"))
            else:
                unknown += 1
                continue
            if not text:
                continue
            when = _timestamp(timestamp_value, fallback)
            if not _within_lookback(when, config.sources.lookback_days):
                continue
            event, excluded = _make_event(
                source_kind=f"{agent}_transcript_user",
                authority=Authority.REPEATED_USER_PREFERENCE,
                timestamp=when,
                session_id=session,
                scope=display_path(path.parent),
                text=text,
                locator=f"{display_path(path)}:{line_no}",
                max_chars=config.sources.max_excerpt_chars,
            )
            sensitive += int(excluded)
            if event:
                events.append(event)
    return events, SourceStats(
        files_seen=len(paths),
        bytes_seen=bytes_seen,
        records_seen=records,
        records_emitted=len(events),
        malformed_records=malformed,
        unknown_records=unknown,
        sensitive_records_excluded=sensitive,
    )


def _minimal_subprocess_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "LANG", "LC_ALL")
    return {name: os.environ[name] for name in keep if name in os.environ}


def _kindex(config: Config) -> tuple[list[EvidenceEvent], SourceStats, list[str]]:
    if not config.kindex.enabled or not shutil.which(config.kindex.command):
        return [], SourceStats(), ["kindex_unavailable"] if config.kindex.enabled else []
    events: list[EvidenceEvent] = []
    warnings: list[str] = []
    ids: set[str] = set()
    environment = _minimal_subprocess_env()
    for query in config.kindex.queries:
        command = [
            config.kindex.command,
            "search",
            query,
            "--top-k",
            str(config.kindex.max_results),
            "--json",
        ]
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )
            found = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            fail(
                "kindex_required_failed",
                "Configured Kindex is installed but a required search failed: "
                f"{type(exc).__name__}",
            )
        if isinstance(found, list):
            ids.update(
                str(item["id"]) for item in found if isinstance(item, dict) and item.get("id")
            )
    for node_id in sorted(ids):
        try:
            result = subprocess.run(
                [config.kindex.command, "show", node_id, "--json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )
            node = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            fail(
                "kindex_required_failed",
                "Configured Kindex is installed but a required node read failed: "
                f"{type(exc).__name__}",
            )
        if not isinstance(node, dict) or node.get("status", "active") != "active":
            continue
        content = node.get("content") or node.get("title")
        if not isinstance(content, str):
            continue
        event, excluded = _make_event(
            source_kind="kindex_active",
            authority=Authority.KINDEX_ACTIVE,
            timestamp=_timestamp(node.get("updated_at") or node.get("created_at")),
            session_id=None,
            scope=",".join(node.get("tags", []))
            if isinstance(node.get("tags"), list)
            else "global",
            text=content,
            locator=f"kindex:{node_id}",
            max_chars=config.sources.max_excerpt_chars,
        )
        if excluded:
            warnings.append(f"kindex_sensitive_excluded:{node_id}")
        elif event:
            events.append(event)
    return (
        events,
        SourceStats(
            files_seen=0,
            records_seen=len(ids),
            records_emitted=len(events),
            sensitive_records_excluded=sum(
                item.startswith("kindex_sensitive") for item in warnings
            ),
        ),
        warnings,
    )


def collect_events(
    config: Config,
) -> tuple[tuple[EvidenceEvent, ...], SourceStats, tuple[str, ...]]:
    events: list[EvidenceEvent] = []
    stats = SourceStats()
    warnings: list[str] = []
    for agent in config.sources.agents:
        history_events, history_stats = (
            _claude_history(config) if agent == "claude" else _codex_history(config)
        )
        events.extend(history_events)
        stats = stats.merge(history_stats)
        if config.sources.include_auto_memory:
            memory_events, memory_stats = _auto_memory(config, agent)
            events.extend(memory_events)
            stats = stats.merge(memory_stats)
        if config.sources.include_transcripts:
            transcript_events, transcript_stats = _transcripts(config, agent)
            events.extend(transcript_events)
            stats = stats.merge(transcript_stats)
    k_events, k_stats, k_warnings = _kindex(config)
    events.extend(k_events)
    stats = stats.merge(k_stats)
    warnings.extend(k_warnings)

    unique: dict[str, EvidenceEvent] = {}
    duplicate_count = 0
    for event in events:
        key = f"{event.session_id or ''}:{event.content_sha256}"
        previous = unique.get(key)
        if previous is None or event.timestamp > previous.timestamp:
            if previous is not None:
                duplicate_count += 1
            unique[key] = event
        else:
            duplicate_count += 1
    stats = replace(stats, duplicate_records=stats.duplicate_records + duplicate_count)
    ordered = tuple(
        sorted(
            (
                replace(
                    event,
                    unattended_eligible=event.id in config.apply.unattended_evidence_ids,
                )
                for event in unique.values()
            ),
            key=lambda item: (item.timestamp, item.id),
        )
    )
    return ordered, stats, tuple(sorted(set(warnings)))
