from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import StubProvider, inspection, keep_all, replace_matching

import meditate.transaction as transaction
from meditate.cli import main
from meditate.models import Authority, EvidenceEvent
from meditate.plan import create_plan
from meditate.transaction import apply_run
from meditate.util import MeditateError, sha256_bytes


def _event() -> EvidenceEvent:
    text = "New rule: commit completed work after project-required checks pass."
    return EvidenceEvent(
        id="evt_import_graph",
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id="import-graph-session",
        scope="global",
        text=text,
        source_locator="fixture:import-graph",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def _config_with_root(
    config_factory: ConfigFactory,
    tmp_path: Path,
    content: str,
    *,
    name: str = "CLAUDE.md",
):
    config, _unused = config_factory()
    root = tmp_path / "import-project" / name
    root.parent.mkdir(parents=True, exist_ok=True)
    root.write_text(content, encoding="utf-8")
    return replace(config, targets=(root,)), root


def _dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _graph_objects(value: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in _dicts(value)
        if isinstance(item.get("nodes"), list)
        and isinstance(item.get("edges"), list)
        and isinstance(item.get("digest"), str)
    ]


def test_relative_absolute_and_home_imports_are_recursive_sanitized_immutable_context(
    config_factory: ConfigFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "synthetic-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    absolute = tmp_path / "absolute-context.md"
    absolute.write_text("# Absolute\n\n- Absolute import context.\n", encoding="utf-8")
    home_import = home / "home-context.md"
    home_import.write_text("# Home\n\n- Home import context.\n", encoding="utf-8")
    root_text = f"""# Root

- Root mutable directive.

`@missing-inline.md`

```text
@missing-fenced.md
```

@relative.md
@{absolute}
@~/home-context.md
"""
    config, root = _config_with_root(config_factory, tmp_path, root_text)
    relative = root.parent / "relative.md"
    nested = root.parent / "nested.md"
    relative.write_text(
        "# Relative\n\n- Relative import context.\n\n@nested.md\n",
        encoding="utf-8",
    )
    raw_secret = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
    nested.write_text(
        f"# Nested\n\n- Nested import context.\n\n{raw_secret}\n",
        encoding="utf-8",
    )

    provider = StubProvider(keep_all)
    create_plan(config, provider=provider, inspection=inspection(config, ()))
    assert provider.last_packet is not None
    packet = provider.last_packet
    serialized = json.dumps(packet, sort_keys=True)
    assert packet["allowed_targets"] == [str(root)]
    assert [item["target"] for item in packet["targets"]] == [str(root)]
    assert raw_secret not in serialized
    for phrase in (
        "Relative import context",
        "Nested import context",
        "Absolute import context",
        "Home import context",
    ):
        assert phrase in serialized
        assert any(
            item.get("mutable") is False and phrase in json.dumps(item) for item in _dicts(packet)
        )
    assert not any(
        item.get("mutable") is False
        and ("missing-inline.md" in json.dumps(item) or "missing-fenced.md" in json.dumps(item))
        for item in _dicts(packet)
    )


def test_import_is_mutable_and_in_total_disposition_only_when_separately_configured(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, root = _config_with_root(
        config_factory,
        tmp_path,
        "# Root\n\n- Root directive.\n\n@shared.md\n",
    )
    shared = root.parent / "shared.md"
    shared.write_text("# Shared\n\n- Separately configured directive.\n", encoding="utf-8")
    config = replace(config, targets=(root, shared))
    provider = StubProvider(keep_all)
    create_plan(config, provider=provider, inspection=inspection(config, ()))
    assert provider.last_packet is not None
    packet = provider.last_packet
    assert packet["allowed_targets"] == [str(root), str(shared)]
    target = next(item for item in packet["targets"] if item["target"] == str(shared))
    assert any("Separately configured directive" in item["text"] for item in target["directives"])


def test_import_depth_of_four_hops_is_accepted(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, root = _config_with_root(
        config_factory,
        tmp_path,
        "# Root\n\n- Root directive.\n\n@hop-1.md\n",
    )
    for hop in range(1, 5):
        suffix = f"\n\n@hop-{hop + 1}.md\n" if hop < 4 else "\n"
        (root.parent / f"hop-{hop}.md").write_text(
            f"# Hop {hop}\n\n- Context at hop {hop}.{suffix}",
            encoding="utf-8",
        )
    provider = StubProvider(keep_all)
    create_plan(config, provider=provider, inspection=inspection(config, ()))
    assert provider.calls == 1
    assert provider.last_packet is not None
    for hop in range(1, 5):
        assert f"Context at hop {hop}" in json.dumps(provider.last_packet)


def test_import_drift_between_inspection_and_plan_fails_before_provider_or_archive(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, root = _config_with_root(
        config_factory,
        tmp_path,
        "# Root\n\n- Root directive.\n\n@context.md\n",
    )
    imported = root.parent / "context.md"
    imported.write_text("# Context\n\n- Original imported context.\n", encoding="utf-8")
    inspected = inspection(config, ())
    imported.write_text("# Context\n\n- Drifted imported context.\n", encoding="utf-8")

    provider = StubProvider(keep_all)
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspected)
    assert caught.value.code == "import_graph_drift"
    assert provider.calls == 0
    assert not (config.data_root / "runs").exists()


@pytest.mark.parametrize(
    "failure",
    ["dangling", "circular", "over_depth", "nonregular", "non_utf8"],
)
def test_invalid_import_graphs_fail_before_provider_call(
    config_factory: ConfigFactory,
    tmp_path: Path,
    failure: str,
) -> None:
    config, root = _config_with_root(
        config_factory,
        tmp_path,
        "# Root\n\n- Root directive.\n\n@first.md\n",
    )
    first = root.parent / "first.md"
    if failure == "dangling":
        pass
    elif failure == "circular":
        first.write_text("# First\n\n@CLAUDE.md\n", encoding="utf-8")
    elif failure == "over_depth":
        first.write_text("# Hop 1\n\n@hop-2.md\n", encoding="utf-8")
        for hop in range(2, 6):
            suffix = f"\n@hop-{hop + 1}.md\n" if hop < 5 else "\n"
            (root.parent / f"hop-{hop}.md").write_text(f"# Hop {hop}{suffix}", encoding="utf-8")
    elif failure == "nonregular":
        first.mkdir()
    else:
        first.write_bytes(b"# Invalid UTF-8\n\xff\xfe\n")

    provider = StubProvider(keep_all)
    with pytest.raises(MeditateError):
        create_plan(config, provider=provider, inspection=inspection(config, ()))
    assert provider.calls == 0
    assert not (config.data_root / "runs").exists()


def _minimal_config_text(target: Path, root: Path) -> str:
    quote = json.dumps
    return f"""schema_version = 1
targets = [{quote(str(target))}]
env_file = ""

[paths]
data_root = {quote(str(root / "data"))}
state_root = {quote(str(root / "state"))}
cache_root = {quote(str(root / "cache"))}

[sources]
agents = ["claude"]
claude_home = {quote(str(root / "claude-home"))}
codex_home = {quote(str(root / "codex-home"))}
include_auto_memory = false
include_transcripts = false
max_events = 20
max_excerpt_chars = 500
max_jsonl_line_bytes = 100000
max_transcript_files = 2
lookback_days = 0

[kindex]
enabled = false
command = "kin"
queries = []
max_results = 5

[llm]
provider = "anthropic"
model = "claude-sonnet-4-6"
effort = "high"
max_input_tokens = 50000
max_output_tokens = 4096
max_total_input_tokens = 50000
max_total_output_tokens = 4096
max_calls = 1
timeout_seconds = 60

[safety]
protected_headings = []
size_floor_ratio = 0.2
size_ceiling_ratio = 2.0
max_churn_ratio = 1.0
max_malformed_ratio = 0.2
minimum_free_bytes = 1

[apply]
allow_unattended_apply = false
minimum_attended_applies = 3
unattended_evidence_ids = []

[retention]
derived_days = 30
"""


def test_inspection_json_exposes_text_free_import_graph(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "project" / "CLAUDE.local.md"
    root.parent.mkdir(parents=True)
    imported = root.parent / "context.md"
    imported_text = "# Context\n\n- Raw imported instruction must not enter graph metadata.\n"
    imported.write_text(imported_text, encoding="utf-8")
    root.write_text("# Root\n\n- Root directive.\n\n@context.md\n", encoding="utf-8")
    config_path = tmp_path / "meditate.toml"
    config_path.write_text(_minimal_config_text(root, tmp_path), encoding="utf-8")

    assert main(["inspect", "--config", str(config_path), "--json"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    report = json.loads(Path(cli_payload["report_json"]).read_text(encoding="utf-8"))
    graphs = _graph_objects(report)
    assert graphs
    graph = graphs[0]
    assert len(graph["digest"]) == 64
    assert graph["nodes"]
    assert graph["edges"]
    assert imported_text.strip() not in json.dumps(graph, sort_keys=True)
    assert "Raw imported instruction" not in json.dumps(graph, sort_keys=True)


def _replacement_plan_with_import(config_factory: ConfigFactory, tmp_path: Path):
    obsolete = (
        "Commit only when asked, even when completed work has passed all project-required "
        "checks and is ready."
    )
    original = f"# Git\n\n- {obsolete}\n\n@context.md\n\n- Preserve unrelated edits.\n"
    config, root = _config_with_root(config_factory, tmp_path, original)
    imported = root.parent / "context.md"
    imported.write_text("# Context\n\n- Preserve imported context.\n", encoding="utf-8")
    provider = StubProvider(
        replace_matching(
            {obsolete: ("- Commit completed work after project-required checks pass.")}
        )
    )
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (_event(),)),
    )
    return config, root, imported, original, plan


def test_plan_and_manifest_bind_before_and_after_import_graphs(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, _root, _imported, _original, plan = _replacement_plan_with_import(
        config_factory, tmp_path
    )
    run_dir = config.data_root / "runs" / plan.run_id
    for name in ("plan.json", "manifest.json"):
        payload = json.loads((run_dir / name).read_text(encoding="utf-8"))
        graphs = _graph_objects(payload)
        assert len(graphs) >= 2, f"{name} must bind both before and after import graphs"
        assert all(len(graph["digest"]) == 64 for graph in graphs)
        before, after = graphs[:2]
        assert before["digest"] != after["digest"]
        assert before["edges"] == after["edges"]


def test_pre_apply_import_drift_fails_before_target_write(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, root, imported, original, plan = _replacement_plan_with_import(config_factory, tmp_path)
    imported.write_text("# Context\n\n- Drifted after planning.\n", encoding="utf-8")
    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert caught.value.code == "import_graph_drift"
    assert root.read_text(encoding="utf-8") == original
    state = json.loads(
        (config.data_root / "runs" / plan.run_id / "state.json").read_text(encoding="utf-8")
    )
    assert state["state"] == "planned"
    assert state["consumed"] is False


def test_post_write_import_graph_mismatch_rolls_back_changed_targets(
    config_factory: ConfigFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, root, imported, original, plan = _replacement_plan_with_import(config_factory, tmp_path)
    actual_replace = transaction._replace_target
    injected = False

    def drift_import_after_target_write(
        path: Path,
        data: bytes,
        mode: int,
        *,
        expected_exists: bool,
        expected_sha256: str,
    ) -> None:
        nonlocal injected
        actual_replace(
            path,
            data,
            mode,
            expected_exists=expected_exists,
            expected_sha256=expected_sha256,
        )
        if path == root and b"Commit completed work" in data and not injected:
            injected = True
            imported.write_text("# Context\n\n- Drifted during apply.\n", encoding="utf-8")

    monkeypatch.setattr(transaction, "_replace_target", drift_import_after_target_write)
    with pytest.raises(MeditateError):
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert root.read_text(encoding="utf-8") == original
    state = json.loads(
        (config.data_root / "runs" / plan.run_id / "state.json").read_text(encoding="utf-8")
    )
    assert state["state"] == "rolled_back"
