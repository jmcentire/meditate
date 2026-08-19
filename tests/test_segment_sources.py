from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ConfigFactory

import meditate.sources as sources_module
from meditate.config import KindexConfig, SourceConfig
from meditate.segment import segment_markdown
from meditate.sources import collect_events
from meditate.util import MeditateError


def test_segmenter_preserves_ranges_nested_lists_fences_and_protection() -> None:
    content = """# Workflow

- First rule.
  - Nested detail remains attached.

Paragraph rule spans
two lines.

```text
- This is opaque.
```

<!-- meditate:protect:start -->
- Never rewrite this.
<!-- meditate:protect:end -->
"""
    directives = segment_markdown(content, logical_path="~/CLAUDE.md")
    assert [item.kind for item in directives] == [
        "list_item",
        "paragraph",
        "code_fence",
        "protected",
    ]
    assert "Nested detail" in directives[0].raw
    assert directives[-1].protected
    for directive in directives:
        assert content[directive.start : directive.end] == directive.raw


def test_segmenter_ids_are_stable_and_duplicate_directives_are_distinct() -> None:
    content = "# Rules\n\n- Same.\n"
    first = segment_markdown(content, logical_path="~/CLAUDE.md")
    second = segment_markdown(content, logical_path="~/CLAUDE.md")
    assert [item.id for item in first] == [item.id for item in second]
    duplicates = segment_markdown("# Rules\n\n- Same.\n- Same.\n", logical_path="~/CLAUDE.md")
    repeated = segment_markdown("# Rules\n\n- Same.\n- Same.\n", logical_path="~/CLAUDE.md")
    assert len({item.id for item in duplicates}) == 2
    assert [item.id for item in duplicates] == [item.id for item in repeated]


def test_claude_history_is_streamed_ordered_and_secret_records_are_excluded(
    config_factory: ConfigFactory, tmp_path: Path
) -> None:
    claude = tmp_path / "claude"
    claude.mkdir()
    history = claude / "history.jsonl"
    records = [
        {
            "display": "Older rule: verify before claiming done.",
            "timestamp": 1_700_000_000_000,
            "sessionId": "session-old",
            "project": "/repo/a",
        },
        {"display": "Cookie: session=abcdefghijklmnop", "timestamp": 1_710_000_000_000},
        {
            "display": "New rule: commit completed changes by default.",
            "timestamp": 1_720_000_000_000,
            "sessionId": "session-new",
            "project": "/repo/b",
        },
    ]
    history.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n{broken json\n",
        encoding="utf-8",
    )
    source = SourceConfig(
        agents=("claude",),
        claude_home=claude,
        codex_home=tmp_path / "codex",
        include_auto_memory=False,
        max_events=20,
        max_excerpt_chars=500,
    )
    config, _paths = config_factory(sources=source)
    events, stats, warnings = collect_events(config)
    assert [event.session_id for event in events] == ["session-old", "session-new"]
    assert stats.records_seen == 4
    assert stats.records_emitted == 2
    assert stats.sensitive_records_excluded == 1
    assert stats.malformed_records == 1
    assert not warnings
    assert all("abcdefghijklmnop" not in event.text for event in events)
    reviewed_id = events[-1].id
    reviewed_config = replace(
        config,
        apply=replace(config.apply, unattended_evidence_ids=(reviewed_id,)),
    )
    reviewed_events, _stats, _warnings = collect_events(reviewed_config)
    assert next(event for event in reviewed_events if event.id == reviewed_id).unattended_eligible
    assert not next(
        event for event in reviewed_events if event.id != reviewed_id
    ).unattended_eligible


def test_codex_history_shape_and_duplicate_accounting(
    config_factory: ConfigFactory, tmp_path: Path
) -> None:
    codex = tmp_path / "codex"
    codex.mkdir()
    history = codex / "history.jsonl"
    line = {"session_id": "one", "text": "Always run the exact test.", "ts": 1_720_000_000}
    history.write_text(json.dumps(line) + "\n" + json.dumps(line) + "\n", encoding="utf-8")
    source = SourceConfig(
        agents=("codex",),
        claude_home=tmp_path / "claude",
        codex_home=codex,
        include_auto_memory=False,
        max_events=20,
        max_excerpt_chars=500,
    )
    config, _paths = config_factory(sources=source)
    events, stats, _warnings = collect_events(config)
    assert len(events) == 1
    assert events[0].session_id == "one"
    assert stats.duplicate_records == 1


def test_transcript_ingestion_is_opt_in(config_factory: ConfigFactory, tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    transcript = claude / "projects" / "repo" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "transcript-session",
                "timestamp": "2026-08-18T12:00:00Z",
                "message": {"role": "user", "content": "Never erase unrelated changes."},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    base = SourceConfig(
        agents=("claude",),
        claude_home=claude,
        codex_home=tmp_path / "codex",
        include_auto_memory=False,
        include_transcripts=False,
        max_events=20,
        max_excerpt_chars=500,
    )
    config, _paths = config_factory(sources=base)
    events, _stats, _warnings = collect_events(config)
    assert not events
    enabled = replace(config, sources=replace(base, include_transcripts=True))
    events, _stats, _warnings = collect_events(enabled)
    assert [event.session_id for event in events] == ["transcript-session"]


def test_installed_enabled_kindex_is_a_required_evidence_source(
    config_factory: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _targets = config_factory()
    config = replace(
        config,
        kindex=KindexConfig(enabled=True, queries=("durable preferences",)),
    )
    monkeypatch.setattr(sources_module.shutil, "which", lambda _command: "/usr/bin/kin")

    def fail_search(*_args: object, **_kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, ["kin", "search"])

    monkeypatch.setattr(sources_module.subprocess, "run", fail_search)
    with pytest.raises(MeditateError) as caught:
        collect_events(config)
    assert caught.value.code == "kindex_required_failed"


def test_installed_enabled_kindex_executes_every_configured_query(
    config_factory: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _targets = config_factory()
    queries = ("durable preferences", "instruction adherence")
    config = replace(config, kindex=KindexConfig(enabled=True, queries=queries))
    monkeypatch.setattr(sources_module.shutil, "which", lambda _command: "/usr/bin/kin")
    calls: list[list[str]] = []

    def successful_search(argv: list[str], **_kwargs: object) -> object:
        calls.append(argv)
        return SimpleNamespace(stdout="[]")

    monkeypatch.setattr(sources_module.subprocess, "run", successful_search)
    events, _stats, warnings = collect_events(config)
    assert not events
    assert not warnings
    assert [call[2] for call in calls] == list(queries)
