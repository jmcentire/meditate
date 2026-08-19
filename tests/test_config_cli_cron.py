from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ConfigFactory

import meditate.cli as cli_module
from meditate.cli import main
from meditate.config import default_config_text, load_config
from meditate.cron import check_cron_environment, render_cron_entry
from meditate.provider import resolve_anthropic_key
from meditate.util import MeditateError


def test_run_apply_does_not_report_not_needed_for_unresolved_semantic_work(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, _targets = config_factory()
    monkeypatch.setattr(cli_module, "_configured", lambda _args: config)
    monkeypatch.setattr(
        cli_module,
        "_plan_payload",
        lambda _config, *, include_inspection_report: {
            "changed_targets": 0,
            "action_required": True,
            "plan_report_markdown": "/tmp/meditate-action-required.md",
        },
    )

    assert main(["run", "--apply", "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "action_required"
    assert "not_needed" not in json.dumps(error)


def test_init_writes_private_config_and_refuses_silent_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config" / "meditate.toml"
    assert main(["init", "--config", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is True
    assert path.read_text(encoding="utf-8") == default_config_text()
    assert "max_calls = 2" in path.read_text(encoding="utf-8")
    assert "max_total_input_tokens = 160000" in path.read_text(encoding="utf-8")
    assert "max_total_output_tokens = 16384" in path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert main(["init", "--config", str(path), "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "config_exists"


def minimal_config_text(target: Path, root: Path, claude_home: Path) -> str:
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
claude_home = {quote(str(claude_home))}
codex_home = {quote(str(root / "codex"))}
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


def test_inspect_cli_uses_real_shapes_but_reports_no_raw_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "CLAUDE.md"
    target.write_text("# Rules\n\n- Verify before claiming success.\n", encoding="utf-8")
    claude = tmp_path / "claude"
    claude.mkdir()
    secret_text = "Cookie: session=supersecretcookievalue"
    clean_text = "New rule: test the actual user workflow."
    records = [
        {"display": secret_text, "timestamp": 1_720_000_000_000},
        {"display": clean_text, "timestamp": 1_730_000_000_000, "sessionId": "one"},
    ]
    (claude / "history.jsonl").write_text(
        "\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8"
    )
    config_path = tmp_path / "meditate.toml"
    config_path.write_text(minimal_config_text(target, tmp_path, claude), encoding="utf-8")
    assert main(["inspect", "--config", str(config_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["events_total"] == 1
    assert payload["sources"]["sensitive_records_excluded"] == 1
    report_json = Path(payload["report_json"]).read_text(encoding="utf-8")
    report_markdown = Path(payload["report_markdown"]).read_text(encoding="utf-8")
    assert clean_text not in report_json + report_markdown
    assert secret_text not in report_json + report_markdown
    assert "supersecretcookievalue" not in report_json + report_markdown


def test_config_rejects_string_booleans(tmp_path: Path) -> None:
    target = tmp_path / "CLAUDE.md"
    target.write_text("- Rule.\n", encoding="utf-8")
    text = minimal_config_text(target, tmp_path, tmp_path / "claude").replace(
        "include_auto_memory = false", 'include_auto_memory = "false"'
    )
    path = tmp_path / "bad.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MeditateError) as caught:
        load_config(path)
    assert caught.value.code == "invalid_config"


def test_module_entrypoint_propagates_cli_failure_status(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    result = subprocess.run(
        [sys.executable, "-m", "meditate", "inspect", "--config", str(missing), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"] == "config_missing"


def test_anthropic_key_uses_only_provider_generic_name(
    config_factory: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _paths = config_factory()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-generic-value")
    secret, warnings = resolve_anthropic_key(config)
    assert secret.source == "ANTHROPIC_API_KEY"
    assert secret.value == "provider-generic-value"
    assert not warnings


def test_cron_entry_is_dry_by_default_and_never_contains_key(
    config_factory: ConfigFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _paths = config_factory()
    profile = tmp_path / "profile"
    profile.write_text("export ANTHROPIC_API_KEY=do-not-print-this\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-print-this")
    checks = check_cron_environment(config, profile=profile)
    assert checks["ok"] is True
    assert checks["anthropic_key_source"] == "ANTHROPIC_API_KEY"
    entry = render_cron_entry(
        config,
        schedule="0 3 * * 0",
        working_directory=tmp_path,
        profile=profile,
        apply=False,
    )
    assert "do-not-print-this" not in entry
    assert " run " in entry
    assert "--apply" not in entry
    assert " && " in entry
    assert str(config.config_path) in entry
    assert str(Path(os.sys.executable)) in entry


def test_cron_apply_is_explicit_in_rendered_command(
    config_factory: ConfigFactory, tmp_path: Path
) -> None:
    config, _paths = config_factory()
    entry = render_cron_entry(
        config,
        schedule="15 4 * * 1",
        working_directory=tmp_path,
        profile=None,
        apply=True,
    )
    assert "--apply" in entry


def test_invalid_cron_schedule_fails(config_factory: ConfigFactory, tmp_path: Path) -> None:
    config, _paths = config_factory()
    with pytest.raises(MeditateError) as caught:
        render_cron_entry(
            config,
            schedule="@daily",
            working_directory=tmp_path,
            profile=None,
            apply=False,
        )
    assert caught.value.code == "invalid_cron_schedule"
