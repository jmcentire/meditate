from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import (
    StubProvider,
    compiled_directive,
    inspection,
    keep_all,
    qualify_plan,
    replace_matching,
)

from meditate.cli import main
from meditate.models import Authority, EvidenceEvent, RunUsage
from meditate.plan import SYSTEM_PROMPT, create_plan
from meditate.provider import AnthropicProvider
from meditate.report import write_plan_report
from meditate.segment import segment_markdown
from meditate.transaction import apply_run
from meditate.util import MeditateError, sha256_bytes

_METRIC_ALIASES = {
    "pre_directives": ("pre_directives", "pre_directive_count"),
    "post_directives": ("post_directives", "post_directive_count"),
    "directive_delta": ("directive_delta", "directive_count_delta"),
    "pre_bytes": ("pre_bytes", "pre_byte_count"),
    "post_bytes": ("post_bytes", "post_byte_count"),
    "byte_delta": ("byte_delta", "byte_count_delta"),
    "pre_lines": ("pre_lines", "pre_line_count"),
    "post_lines": ("post_lines", "post_line_count"),
    "line_delta": ("line_delta", "line_count_delta"),
    "escalated_directives": (
        "escalated_directives",
        "escalated_directive_count",
    ),
}


def _dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _metric_value(record: dict[str, Any], name: str) -> int:
    for key in _METRIC_ALIASES[name]:
        if key in record:
            value = record[key]
            assert isinstance(value, int)
            return value
    nested = record.get("metrics")
    if isinstance(nested, dict):
        return _metric_value(nested, name)
    raise AssertionError(f"missing {name} in metric record: {sorted(record)}")


def _has_metrics(record: dict[str, Any]) -> bool:
    try:
        for name in _METRIC_ALIASES:
            _metric_value(record, name)
    except AssertionError:
        return False
    return True


def _matching_metric_record(value: Any, expected: dict[str, int]) -> dict[str, Any]:
    for record in _dicts(value):
        if not _has_metrics(record):
            continue
        if all(
            _metric_value(record, key) == expected_value for key, expected_value in expected.items()
        ):
            return record
    raise AssertionError(f"no metric record matched {expected}")


def _content_metrics(content: str, path: Path) -> dict[str, int]:
    return {
        "directives": len(segment_markdown(content, logical_path=str(path))),
        "bytes": len(content.encode("utf-8")),
        "lines": len(content.splitlines()),
    }


def _expected_metrics(before: str, after: str, path: Path, *, escalated: int = 0) -> dict[str, int]:
    pre = _content_metrics(before, path)
    post = _content_metrics(after, path)
    return {
        "pre_directives": pre["directives"],
        "post_directives": post["directives"],
        "directive_delta": post["directives"] - pre["directives"],
        "pre_bytes": pre["bytes"],
        "post_bytes": post["bytes"],
        "byte_delta": post["bytes"] - pre["bytes"],
        "pre_lines": pre["lines"],
        "post_lines": post["lines"],
        "line_delta": post["lines"] - pre["lines"],
        "escalated_directives": escalated,
    }


def _event() -> EvidenceEvent:
    text = "New rule: commit completed work after project-required checks pass."
    return EvidenceEvent(
        id="evt_metrics",
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id="metrics-session",
        scope="global",
        text=text,
        source_locator="fixture:metrics",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def test_target_and_aggregate_metrics_flow_through_plan_manifest_report_and_log(
    config_factory: ConfigFactory,
) -> None:
    originals = (
        "# Git\n\n- Commit only when asked.\n\n- Preserve unrelated edits.\n",
        "# Tests\n\n- Run focused checks.\n",
    )
    config, targets = config_factory(
        originals,
        target_names=("CLAUDE.md", "CLAUDE.local.md"),
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": (
                    "- Commit completed work after project-required checks pass."
                )
            }
        )
    )
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (_event(),)),
    )
    proposed_by_path = {str(path): content for path, content in plan.proposed_contents.items()}
    expected_targets = [
        _expected_metrics(before, proposed_by_path[str(path)], path)
        for before, path in zip(originals, targets, strict=True)
    ]
    aggregate = {
        name: sum(expected[name] for expected in expected_targets) for name in _METRIC_ALIASES
    }

    run_dir = config.data_root / "runs" / plan.run_id
    plan_json = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["targets"]) == 2
    for record, expected in zip(manifest["targets"], expected_targets, strict=True):
        for name, value in expected.items():
            assert _metric_value(record, name) == value
    _matching_metric_record(plan_json, aggregate)
    _matching_metric_record(manifest, aggregate)

    report_json_path, report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    _matching_metric_record(report_json, aggregate)
    report_markdown = report_markdown_path.read_text(encoding="utf-8").lower()
    for label in ("post", "directives", "escalated", "bytes", "lines", "delta"):
        assert label in report_markdown

    log_records: list[dict[str, Any]] = []
    log_paths = sorted(
        {
            *config.data_root.rglob("*.jsonl"),
            *config.state_root.rglob("*.jsonl"),
            *config.data_root.rglob("*log*.json"),
            *config.state_root.rglob("*log*.json"),
        }
    )
    assert log_paths
    for path in log_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("run_id") == plan.run_id:
                log_records.append(parsed)
    assert log_records
    assert any(
        all(_metric_value(record, name) == value for name, value in aggregate.items())
        for payload in log_records
        for record in _dicts(payload)
        if _has_metrics(record)
    )


def test_justified_aggregate_byte_growth_is_telemetry_not_a_failure(
    config_factory: ConfigFactory,
) -> None:
    original = "# Reports\n\n- Keep reports concise.\n"
    replacement = "- Keep reports concise and include useful diagnostic context."
    evidence_text = "New rule: keep reports concise and include useful diagnostic context."
    evidence = replace(
        _event(),
        id="evt_compression_growth",
        text=evidence_text,
        session_id="compression-growth-session",
        source_locator="fixture:compression-growth",
        content_sha256=sha256_bytes(evidence_text.encode("utf-8")),
    )
    config, (target,) = config_factory((original,), target_names=("CLAUDE.md",))
    config = replace(
        config,
        safety=replace(config.safety, size_ceiling_ratio=5.0),
    )
    provider = StubProvider(replace_matching({"Keep reports concise": replacement}))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    plan = create_plan(config, provider=provider, inspection=inspection(config, (evidence,)))

    assert plan.blocked_reasons == ()
    run_dir = config.data_root / "runs" / plan.run_id
    plan_json = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert plan_json["blocked_reasons"] == []
    assert manifest["blocked_reasons"] == []
    assert sum(_metric_value(record, "byte_delta") for record in manifest["targets"]) > 0

    report_json_path, report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    for surface in (plan_json, manifest, report_json):
        assert not any(
            item.get("apply_command") for item in _dicts(surface) if "apply_command" in item
        )
    assert "meditate apply" not in report_markdown_path.read_text(encoding="utf-8").lower()

    qualify_plan(config, plan.run_id)
    receipt = apply_run(
        config,
        plan.run_id,
        mode="attended",
        approval_sha256=plan.plan_sha256,
    )
    assert receipt["state"] == "applied"
    assert target.read_text(encoding="utf-8") != original
    assert "useful diagnostic context" in target.read_text(encoding="utf-8")


def test_compiled_rationales_may_grow_multiple_targets_as_reported_telemetry(
    config_factory: ConfigFactory,
) -> None:
    originals = (
        "# Logs\n\n- Keep logs.\n",
        (
            "# Reports\n\n"
            "- Always include verbose step-by-step diagnostic details and repeated context in "
            "every routine report.\n"
        ),
    )
    replacements = (
        "- Keep logs and retain useful diagnostic context.",
        "- Keep routine reports concise.",
    )
    evidence_texts = (
        "New rule: keep logs and retain useful diagnostic context.",
        "New rule: keep routine reports concise.",
    )
    events = tuple(
        replace(
            _event(),
            id=f"evt_aggregate_{index}",
            text=text,
            session_id=f"aggregate-session-{index}",
            source_locator=f"fixture:aggregate:{index}",
            content_sha256=sha256_bytes(text.encode("utf-8")),
        )
        for index, text in enumerate(evidence_texts)
    )
    config, _targets = config_factory(
        originals,
        target_names=("CLAUDE.md", "CLAUDE.local.md"),
    )
    config = replace(
        config,
        safety=replace(
            config.safety,
            size_floor_ratio=0.1,
            size_ceiling_ratio=5.0,
        ),
    )

    def builder(packet: dict[str, Any]) -> dict[str, Any]:
        evidence_by_id = {
            event["id"]: event for event in packet["evidence_events_oldest_to_newest"]
        }
        changes = []
        for index, target in enumerate(packet["targets"]):
            source = target["directives"][0]
            event = evidence_by_id[f"evt_aggregate_{index}"]
            changes.append(
                {
                    "action": "replace",
                    "source_ids": [source["id"]],
                    "compiled_directive": compiled_directive(replacements[index]),
                    "destination_target": target["target"],
                    "heading_path": source["heading_path"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "The cited rule replaces the prior reporting preference.",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            )
        return {
            "schema_version": 1,
            "keep": [],
            "changes": changes,
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StubProvider(builder)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    plan = create_plan(config, provider=provider, inspection=inspection(config, events))
    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    byte_deltas = [_metric_value(record, "byte_delta") for record in manifest["targets"]]
    assert any(delta > 0 for delta in byte_deltas)
    assert sum(byte_deltas) > 0
    assert "compression_regression" not in plan.blocked_reasons
    assert plan.changed_directive_count == 2


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


def test_cli_plan_json_exposes_metrics_and_configured_target_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "project" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    content = "# Rules\n\n- Preserve hand edits.\n"
    target.write_text(content, encoding="utf-8")
    config_path = tmp_path / "meditate.toml"
    config_path.write_text(_minimal_config_text(target, tmp_path), encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")

    def complete(
        _provider: AnthropicProvider,
        *,
        system: str,
        payload: str,
        schema: dict[str, Any],
    ) -> tuple[str, RunUsage]:
        assert system == SYSTEM_PROMPT
        packet = json.loads(payload)
        return json.dumps(keep_all(packet)), RunUsage(
            calls=1,
            actual_input_tokens=1,
            actual_output_tokens=1,
            stop_reason="end_turn",
        )

    monkeypatch.setattr(AnthropicProvider, "complete", complete)
    assert main(["plan", "--config", str(config_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = _expected_metrics(content, content, target)
    record = _matching_metric_record(payload, expected)
    assert any("configured_targets_only" in item.values() for item in _dicts(record)) or any(
        "configured_targets_only" in item.values() for item in _dicts(payload)
    )


def test_claude_over_200_post_lines_is_structured_guidance_not_a_hard_limit(
    config_factory: ConfigFactory,
) -> None:
    content = "# Rules\n\n" + "".join(f"- Synthetic rule {index}.\n" for index in range(201))
    config, _targets = config_factory((content,), target_names=("CLAUDE.md",))
    config = replace(
        config,
        llm=replace(
            config.llm,
            max_input_tokens=500_000,
            max_total_input_tokens=500_000,
        ),
    )
    plan = create_plan(
        config,
        provider=StubProvider(keep_all),
        inspection=inspection(config, ()),
    )
    run_dir = config.data_root / "runs" / plan.run_id
    plan_json = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    report_json_path, report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    warnings = [
        item
        for surface in (plan_json, report_json)
        for item in _dicts(surface)
        if item.get("status") == "warning" and "200" in json.dumps(item)
    ]
    assert warnings
    markdown = report_markdown_path.read_text(encoding="utf-8").lower()
    assert "200" in markdown
    assert "guidance" in markdown
    assert "not a hard" in markdown


def _markdown_with_exact_bytes(size: int, *, label: str) -> str:
    prefix = f"# {label}\n\n- "
    suffix = "\n"
    remaining = size - len((prefix + suffix).encode("utf-8"))
    assert remaining >= 0
    content = prefix + ("x" * remaining) + suffix
    assert len(content.encode("utf-8")) == size
    return content


def _codex_config(
    config_factory: ConfigFactory,
    *,
    sizes: tuple[int, int],
    override: int | None,
):
    contents = tuple(
        _markdown_with_exact_bytes(size, label=f"Rules {index}") for index, size in enumerate(sizes)
    )
    config, _targets = config_factory(
        contents,
        target_names=("AGENTS.md", "AGENTS.local.md"),
    )
    codex_home = config.sources.codex_home
    codex_home.mkdir(parents=True, exist_ok=True)
    if override is not None:
        (codex_home / "config.toml").write_text(
            f"project_doc_max_bytes = {override}\n",
            encoding="utf-8",
        )
    config = replace(config, sources=replace(config.sources, agents=("codex",)))
    config = replace(
        config,
        llm=replace(
            config.llm,
            max_input_tokens=200_000,
            max_total_input_tokens=200_000,
        ),
    )
    return config


@pytest.mark.parametrize(
    ("override", "effective_limit"),
    [(None, 32_768), (40_000, 40_000)],
)
def test_codex_instruction_budget_accepts_exact_aggregate_boundary_and_reports_source(
    config_factory: ConfigFactory,
    override: int | None,
    effective_limit: int,
) -> None:
    first = effective_limit // 2
    config = _codex_config(
        config_factory,
        sizes=(first, effective_limit - first),
        override=override,
    )
    plan = create_plan(
        config,
        provider=StubProvider(keep_all),
        inspection=inspection(config, ()),
    )
    run_dir = config.data_root / "runs" / plan.run_id
    plan_json = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    report_json_path, _report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    for surface in (plan_json, report_json):
        assert any(
            (
                item.get("effective_project_doc_max_bytes") == effective_limit
                or item.get("project_doc_max_bytes") == effective_limit
            )
            and "configured_targets_only" in item.values()
            for item in _dicts(surface)
        )


@pytest.mark.parametrize(
    ("override", "effective_limit"),
    [(None, 32_768), (40_000, 40_000)],
)
def test_codex_instruction_budget_fails_one_byte_over_effective_post_plan_aggregate(
    config_factory: ConfigFactory,
    override: int | None,
    effective_limit: int,
) -> None:
    first = effective_limit // 2
    config = _codex_config(
        config_factory,
        sizes=(first, effective_limit - first + 1),
        override=override,
    )
    provider = StubProvider(keep_all)
    with pytest.raises(MeditateError) as caught:
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, ()),
        )
    assert caught.value.code == "codex_instruction_budget"
    assert not (config.data_root / "runs").exists()
