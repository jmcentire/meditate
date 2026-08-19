from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import (
    StubProvider,
    empty_compiled_directive,
    inspection,
    keep_all,
    replace_matching,
)

import meditate.plan as plan_module
import meditate.transaction as transaction
from meditate.cli import main
from meditate.models import Authority, EvidenceEvent, RunUsage
from meditate.plan import (
    PLAN_PROMPT_VERSION,
    PLAN_SCHEMA,
    SEMANTIC_VERIFICATION,
    SYSTEM_PROMPT,
    _packet,
    create_plan,
)
from meditate.provider import AnthropicProvider
from meditate.report import write_plan_report
from meditate.transaction import apply_run
from meditate.util import MeditateError, canonical_json_bytes, sha256_bytes


@pytest.fixture
def resolved_model_provider() -> StubProvider:
    class ResolvedModelProvider(StubProvider):
        model = "requested-model-alias"

        def complete(
            self,
            *,
            system: str,
            payload: str,
            schema: dict[str, Any],
        ) -> tuple[str, RunUsage]:
            response, usage = super().complete(system=system, payload=payload, schema=schema)
            return response, replace(usage, model_id="api-resolved-model-snapshot")

    return ResolvedModelProvider(keep_all)


def _event(
    event_id: str,
    text: str,
    *,
    session_id: str,
    source_kind: str = "claude_history_user",
) -> EvidenceEvent:
    return EvidenceEvent(
        id=event_id,
        source_kind=source_kind,
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id=session_id,
        scope="global",
        text=text,
        source_locator=f"fixture:{event_id}",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def _correction() -> EvidenceEvent:
    return _event(
        "evt_semantic_contract",
        "New rule: commit completed work after project-required checks pass.",
        session_id="semantic-contract-session",
    )


def _replacement_plan(config_factory: ConfigFactory):
    obsolete = (
        "Commit only when asked, even when completed work has passed all project-required "
        "checks and is ready."
    )
    original = f"# Git\n\n- {obsolete}\n\n- Preserve unrelated edits.\n"
    config, (target,) = config_factory((original,), target_names=("CLAUDE.md",))
    provider = StubProvider(
        replace_matching(
            {obsolete: ("- Commit completed work after project-required checks pass.")}
        )
    )
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (_correction(),)),
    )
    return config, target, original, plan


def _dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _assert_exposes_provenance(value: Any, expected: dict[str, Any]) -> None:
    assert any(
        all(item.get(key) == field for key, field in expected.items()) for item in _dicts(value)
    )


def test_plan_manifest_reports_and_plan_hash_bind_prompt_provenance(
    config_factory: ConfigFactory,
) -> None:
    config, _target, _original, plan = _replacement_plan(config_factory)
    run_dir = config.data_root / "runs" / plan.run_id
    plan_path = run_dir / "plan.json"
    plan_json = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "schema_version": plan_json["schema_version"],
        "model": "stub-model-v1",
        "model_id": "stub-model-v1",
        "prompt_version": PLAN_PROMPT_VERSION,
        "prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
        "semantic_verification": SEMANTIC_VERIFICATION,
    }

    for key, value in expected.items():
        assert plan_json[key] == value
        assert manifest[key] == value
    plan_core = dict(plan_json)
    plan_core.pop("plan_sha256")
    assert sha256_bytes(canonical_json_bytes(plan_core)) == plan.plan_sha256
    assert manifest["plan_sha256"] == plan.plan_sha256

    report_json_path, report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    _assert_exposes_provenance(report_json, expected)
    report_markdown = report_markdown_path.read_text(encoding="utf-8").lower()
    assert expected["model_id"].lower() in report_markdown
    assert expected["prompt_sha256"] in report_markdown
    assert expected["semantic_verification"]["method"] in report_markdown
    assert "structural validation is not behavioral qualification" in report_markdown


def test_requested_and_api_resolved_models_are_separate_and_hash_bound(
    config_factory: ConfigFactory,
    resolved_model_provider: StubProvider,
) -> None:
    config, _targets = config_factory(
        ("# Rules\n\n- Preserve hand edits.\n",),
        target_names=("CLAUDE.md",),
    )
    plan = create_plan(
        config,
        provider=resolved_model_provider,
        inspection=inspection(config, ()),
    )
    run_dir = config.data_root / "runs" / plan.run_id
    plan_json = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    expected_models = {
        "model": "requested-model-alias",
        "model_id": "api-resolved-model-snapshot",
    }
    for key, value in expected_models.items():
        assert plan_json[key] == value
        assert manifest[key] == value

    plan_core = dict(plan_json)
    plan_core.pop("plan_sha256")
    assert sha256_bytes(canonical_json_bytes(plan_core)) == plan.plan_sha256
    assert manifest["plan_sha256"] == plan.plan_sha256
    for field in expected_models:
        tampered_core = dict(plan_core)
        tampered_core[field] += "-tampered"
        assert sha256_bytes(canonical_json_bytes(tampered_core)) != plan.plan_sha256

    report_json_path, report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    _assert_exposes_provenance(report_json, expected_models)
    report_markdown = report_markdown_path.read_text(encoding="utf-8")
    assert expected_models["model"] in report_markdown
    assert expected_models["model_id"] in report_markdown


def test_plan_manifest_provenance_mismatch_is_archive_corruption_before_write(
    config_factory: ConfigFactory,
) -> None:
    config, target, original, plan = _replacement_plan(config_factory)
    manifest_path = config.data_root / "runs" / plan.run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model_id"] = "different-model"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert caught.value.code == "archive_corrupt"
    assert target.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("drift", ["version", "prompt_bytes"])
def test_local_prompt_provenance_drift_fails_apply_before_write(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    config, target, original, plan = _replacement_plan(config_factory)
    if drift == "version":
        assert hasattr(plan_module, "PLAN_PROMPT_VERSION")
        monkeypatch.setattr(plan_module, "PLAN_PROMPT_VERSION", "future")
        if hasattr(transaction, "PLAN_PROMPT_VERSION"):
            monkeypatch.setattr(transaction, "PLAN_PROMPT_VERSION", "future")
    else:
        changed_prompt = SYSTEM_PROMPT + "\nsynthetic local drift"
        changed_hash = sha256_bytes(changed_prompt.encode("utf-8"))
        monkeypatch.setattr(plan_module, "SYSTEM_PROMPT", changed_prompt)
        if hasattr(transaction, "SYSTEM_PROMPT"):
            monkeypatch.setattr(transaction, "SYSTEM_PROMPT", changed_prompt)
        for module in (plan_module, transaction):
            if hasattr(module, "PROMPT_SHA256"):
                monkeypatch.setattr(module, "PROMPT_SHA256", changed_hash)

    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert "prompt" in caught.value.code
    assert "drift" in caught.value.code
    assert target.read_text(encoding="utf-8") == original


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


def test_cli_plan_json_exposes_prompt_and_semantic_verification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "project" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Rules\n\n- Preserve hand edits.\n", encoding="utf-8")
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
        raise AssertionError("the local no-candidate gate must not invoke the provider")

    monkeypatch.setattr(AnthropicProvider, "complete", complete)
    assert main(["plan", "--config", str(config_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = {
        "schema_version": 1,
        "model_id": "not-invoked",
        "prompt_version": PLAN_PROMPT_VERSION,
        "prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
        "semantic_verification": {
            "status": "not_applicable",
            "method": SEMANTIC_VERIFICATION["method"],
        },
    }
    _assert_exposes_provenance(payload, expected)
    assert payload["consolidation_preflight"]["provider_called"] is False
    assert payload["blocked_reasons"] == []
    assert payload["consolidation_preflight"]["outcome"] == "stable_noop"


def _escalation_events(*, same_group: bool = False) -> tuple[EvidenceEvent, EvidenceEvent]:
    first = _event(
        "evt_escalate_one",
        "Escalate the attended-review rule to a deterministic hook check.",
        session_id="escalation-session-one",
    )
    second = _event(
        "evt_escalate_two",
        "The attended-review rule still needs a deterministic hook-level check.",
        session_id="escalation-session-one" if same_group else "escalation-session-two",
    )
    return first, second


def _escalation_builder(
    *,
    enforcement_target: str = "hook",
    mutate: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def build(packet: dict[str, Any]) -> dict[str, Any]:
        target = packet["targets"][0]
        source = target["directives"][0]
        events = packet["evidence_events_oldest_to_newest"]
        change = {
            "action": "escalate",
            "source_ids": [source["id"]],
            "compiled_directive": empty_compiled_directive(),
            "destination_target": target["target"],
            "heading_path": source["heading_path"],
            "evidence": [{"id": event["id"], "quote": event["text"]} for event in events],
            "reason": "Independent evidence calls for deterministic enforcement review.",
            "minimum_apply_mode": "attended",
            "relocation_basis": "",
            "enforcement_target": enforcement_target,
            "deterministic_check": "Run the configured pre-operation policy check.",
        }
        if mutate is not None:
            mutate(change, packet)
        return {
            "schema_version": 1,
            "keep": [
                directive["id"]
                for candidate in packet["targets"]
                for directive in candidate["directives"]
                if directive["id"] not in change["source_ids"]
            ],
            "changes": [change],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    return build


def test_plan_schema_has_exact_five_dispositions_and_local_escalation_fields() -> None:
    properties = PLAN_SCHEMA["properties"]["changes"]["items"]["properties"]
    actions = properties["action"]["enum"]
    assert len(actions) == 4
    assert set(actions) == {"replace", "remove", "relocate", "escalate"}
    assert "keep" in PLAN_SCHEMA["properties"]
    assert "candidate_only" not in properties
    assert "lineage_depth" not in properties


@pytest.mark.parametrize("enforcement_target", ["hook", "settings"])
def test_escalation_is_report_only_preserves_exact_bytes_and_is_locally_enriched(
    config_factory: ConfigFactory,
    enforcement_target: str,
) -> None:
    original = b"# Review\r\n\r\n- Require attended review before mutating instruction files.  \r\n"
    config, (target,) = config_factory((None,), target_names=("CLAUDE.md",))
    target.write_bytes(original)
    plan = create_plan(
        config,
        provider=StubProvider(_escalation_builder(enforcement_target=enforcement_target)),
        inspection=inspection(config, _escalation_events()),
    )

    assert plan.changed_directive_count == 0
    assert plan.escalated_directive_count == 1
    assert target.read_bytes() == original
    assert next(iter(plan.proposed_contents.values())).encode("utf-8") == original
    change = plan.raw_plan["changes"][0]
    assert change["enforcement_target"] == enforcement_target
    assert change["deterministic_check"] == "Run the configured pre-operation policy check."
    assert change["candidate_only"] is True
    assert change["lineage_depth"] == 2

    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    target_record = manifest["targets"][0]
    assert target_record["changed"] is False
    assert target_record["changed_directives"] == 0
    assert target_record["directive_delta"] == 0
    assert target_record["byte_delta"] == 0
    assert target_record["line_delta"] == 0
    assert (run_dir / target_record["pre_blob"]).read_bytes() == original
    assert (run_dir / target_record["post_blob"]).read_bytes() == original
    report_json_path, _report_markdown_path = write_plan_report(config, plan)
    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert any(item.get("candidate_only") is True for item in _dicts(report))
    assert not any(item.get("apply_command") for item in _dicts(report) if "apply_command" in item)

    with pytest.raises(MeditateError) as caught:
        apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert caught.value.code == "no_changes"


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("replacement", lambda change, _packet: change.update(replacement="- Changed.")),
        (
            "destination",
            lambda change, packet: change.update(destination_target=packet["targets"][1]["target"]),
        ),
        ("heading", lambda change, _packet: change.update(heading_path=["Other"])),
        ("target", lambda change, _packet: change.update(enforcement_target="file")),
        ("check", lambda change, _packet: change.update(deterministic_check="")),
        ("one_evidence", lambda change, _packet: change.update(evidence=change["evidence"][:1])),
    ],
)
def test_invalid_escalations_fail_closed(
    config_factory: ConfigFactory,
    case: str,
    mutate: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    del case
    contents = (
        "# Review\n\n- Require attended review before mutation.\n",
        "# Other\n\n- Preserve this separate target.\n",
    )
    config, _targets = config_factory(
        contents,
        target_names=("CLAUDE.md", "CLAUDE.local.md"),
    )
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=StubProvider(_escalation_builder(mutate=mutate)),
            inspection=inspection(config, _escalation_events()),
        )
    assert not (config.data_root / "runs").exists()


def test_escalation_evidence_must_span_independent_provenance_groups(
    config_factory: ConfigFactory,
) -> None:
    config, _targets = config_factory(
        ("# Review\n\n- Require attended review before mutation.\n",),
        target_names=("CLAUDE.md",),
    )
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=StubProvider(_escalation_builder()),
            inspection=inspection(config, _escalation_events(same_group=True)),
        )
    assert not (config.data_root / "runs").exists()


@pytest.mark.parametrize(
    ("enforcement_target", "deterministic_check"),
    [("hook", ""), ("", "Run the configured pre-operation policy check.")],
)
def test_non_escalate_operations_reject_enforcement_fields(
    config_factory: ConfigFactory,
    enforcement_target: str,
    deterministic_check: str,
) -> None:
    config, _targets = config_factory(
        ("# Git\n\n- Commit only when asked.\n",),
        target_names=("CLAUDE.md",),
    )

    def build(packet: dict[str, Any]) -> dict[str, Any]:
        plan = replace_matching(
            {
                "Commit only when asked": (
                    "- Commit completed work after project-required checks pass."
                )
            }
        )(packet)
        plan["changes"][0].update(
            enforcement_target=enforcement_target,
            deterministic_check=deterministic_check,
        )
        return plan

    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=StubProvider(build),
            inspection=inspection(config, (_correction(),)),
        )


@pytest.mark.parametrize(
    "heading_component",
    ["line\nbreak", "carriage\rreturn", "nul\x00byte", ""],
    ids=("newline", "carriage-return", "nul", "empty"),
)
def test_invalid_heading_components_fail_closed_without_archiving(
    config_factory: ConfigFactory,
    heading_component: str,
) -> None:
    config, _targets = config_factory(
        ("# Git\n\n- Commit only when asked.\n",),
        target_names=("CLAUDE.md",),
    )

    def build(packet: dict[str, Any]) -> dict[str, Any]:
        raw_plan = replace_matching(
            {
                "Commit only when asked": (
                    "- Commit completed work after project-required checks pass."
                )
            }
        )(packet)
        raw_plan["changes"][0]["heading_path"] = [heading_component]
        return raw_plan

    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=StubProvider(build),
            inspection=inspection(config, (_correction(),)),
        )
    assert not (config.data_root / "runs").exists()


def _contextual_config(
    config_factory: ConfigFactory,
    tmp_path: Path,
    *,
    destination_kind: str = "scoped_rule",
):
    config, _unused = config_factory()
    project = tmp_path / "contextual-project"
    root = project / "CLAUDE.md"
    root.parent.mkdir(parents=True, exist_ok=True)
    root.write_text("# Python\n\n- Run the project Python check.\n", encoding="utf-8")
    if destination_kind == "non_rule":
        destination = project / "policies" / "python.md"
    else:
        destination = project / ".claude" / "rules" / "python.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        '---\npaths:\n  - "src/**/*.py"\n  - "tests/**/*.py"\n---\n\n'
        if destination_kind != "unscoped_rule"
        else ""
    )
    destination.write_text(
        frontmatter + "# Python\n\n- Keep existing scoped guidance.\n",
        encoding="utf-8",
    )
    return replace(config, targets=(root, destination)), root, destination


def _contextual_relocation_builder(
    *, destination_override: str | None = None
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def build(packet: dict[str, Any]) -> dict[str, Any]:
        source_target, destination_target = packet["targets"]
        source = source_target["directives"][0]
        event = packet["evidence_events_oldest_to_newest"][0]
        return {
            "schema_version": 1,
            "keep": [directive["id"] for directive in destination_target["directives"]],
            "changes": [
                {
                    "action": "relocate",
                    "source_ids": [source["id"]],
                    "compiled_directive": empty_compiled_directive(),
                    "destination_target": destination_override or destination_target["target"],
                    "heading_path": ["Python"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "The exact configured rule scope is the contextual destination.",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "contextual",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    return build


def _relocation_evidence() -> EvidenceEvent:
    return _event(
        "evt_contextual_relocation",
        "Move the project Python check into the configured scoped Python rule.",
        session_id="contextual-relocation-session",
    )


def test_configured_rule_paths_are_in_packet_and_contextual_relocation_uses_exact_target(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, root, destination = _contextual_config(config_factory, tmp_path)
    inspected = inspection(config, (_relocation_evidence(),))
    packet, _payload, _schema, _estimate, _dropped = _packet(inspected, config)
    scoped = next(item for item in packet["targets"] if item["target"] == str(destination))
    assert scoped["scope"]["paths"] == ["src/**/*.py", "tests/**/*.py"]
    assert packet["allowed_targets"] == [str(root), str(destination)]

    plan = create_plan(
        config,
        provider=StubProvider(_contextual_relocation_builder()),
        inspection=inspected,
    )
    proposed = {str(path): content for path, content in plan.proposed_contents.items()}
    assert "Run the project Python check" not in proposed[str(root)]
    assert "Run the project Python check" in proposed[str(destination)]


@pytest.mark.parametrize("destination_kind", ["unscoped_rule", "non_rule"])
def test_contextual_relocation_rejects_unscoped_or_non_rule_destination(
    config_factory: ConfigFactory,
    tmp_path: Path,
    destination_kind: str,
) -> None:
    config, _root, _destination = _contextual_config(
        config_factory,
        tmp_path,
        destination_kind=destination_kind,
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(
            config,
            provider=StubProvider(_contextual_relocation_builder()),
            inspection=inspection(config, (_relocation_evidence(),)),
        )
    assert caught.value.code == "unscoped_contextual_relocation"


def test_contextual_relocation_cannot_invent_an_unconfigured_target(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, _root, _destination = _contextual_config(config_factory, tmp_path)
    invented = tmp_path / "contextual-project" / ".claude" / "rules" / "invented.md"
    provider = StubProvider(_contextual_relocation_builder(destination_override=str(invented)))
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, (_relocation_evidence(),)),
        )
    assert not invented.exists()
    assert not (config.data_root / "runs").exists()
    assert provider.last_schema is not None
    destination_schema = provider.last_schema["properties"]["changes"]["items"]["properties"][
        "destination_target"
    ]
    assert "enum" not in destination_schema
