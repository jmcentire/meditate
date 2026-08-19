from __future__ import annotations

import io
import json
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import StubProvider, compiled_directive, inspection, keep_all

import meditate.cli as cli
import meditate.decisions as decisions
import meditate.plan as plan_module
import meditate.transaction as transaction
from meditate.cli import main
from meditate.config import Config
from meditate.models import Authority, EvidenceEvent, RunUsage
from meditate.plan import PLAN_SCHEMA, create_plan
from meditate.provider import AnthropicProvider
from meditate.report import write_plan_report
from meditate.transaction import apply_run, purge_run
from meditate.util import MeditateError, sha256_bytes

SUBJECT_A = "automatic deployment after release"
SUBJECT_B = "operator handoff before deployment"
OPTION_A = "Deploy automatically after release"
OPTION_B = "Require an operator handoff before deployment"
OPTION_C = "Follow repository policy for deployment authority"


@dataclass(frozen=True)
class DecisionArchive:
    config: Config
    target: Path
    original: bytes
    plan: Any
    request: dict[str, Any]
    directive_ids: frozenset[str]
    events: tuple[EvidenceEvent, ...]
    imported: Path | None = None


def _event(event_id: str, text: str, *, session_id: str) -> EvidenceEvent:
    return EvidenceEvent(
        id=event_id,
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id=session_id,
        scope="global",
        text=text,
        source_locator=f"fixture:{event_id}",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def _conflicting_events() -> tuple[EvidenceEvent, EvidenceEvent]:
    return (
        _event(
            "evt_auto_deploy",
            "Always deploy automatically after release.",
            session_id="authority-session-a",
        ),
        _event(
            "evt_operator_handoff",
            "Never deploy automatically; require an operator handoff before deployment.",
            session_id="authority-session-b",
        ),
    )


def _request_from_packet(
    packet: dict[str, Any],
    *,
    subject_a: str = SUBJECT_A,
    subject_b: str = SUBJECT_B,
    labels: tuple[str, str, str] = (OPTION_A, OPTION_B, OPTION_C),
) -> dict[str, Any]:
    directives = [directive for target in packet["targets"] for directive in target["directives"]]
    evidence = packet["evidence_events_oldest_to_newest"]
    assert len(directives) >= 2
    assert len(evidence) >= 2
    return {
        "subject_a": subject_a,
        "subject_b": subject_b,
        "directive_ids": [directives[0]["id"], directives[1]["id"]],
        "evidence_ids": [evidence[0]["id"], evidence[1]["id"]],
        "options": [
            {
                "label": labels[0],
                "consequence": "Completed releases proceed to deployment automatically.",
                "rationale": "The first cited directive and evidence require automatic deploys.",
                "evidence_ids": [evidence[0]["id"]],
            },
            {
                "label": labels[1],
                "consequence": "Deployment pauses for an explicit operator handoff.",
                "rationale": "The second cited directive and evidence require a handoff.",
                "evidence_ids": [evidence[1]["id"]],
            },
            {
                "label": labels[2],
                "consequence": "Loaded repository policy determines deployment authority.",
                "rationale": (
                    "This preserves both cited constraints until scoped policy resolves them."
                ),
                "evidence_ids": [evidence[0]["id"], evidence[1]["id"]],
            },
        ],
        "recommendation_rationale": (
            "Automatic deployment is recommended because it is the first equally authoritative "
            "owner preference presented for resolution."
        ),
    }


def _decision_plan(
    packet: dict[str, Any],
    *,
    mutate: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    request_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = _request_from_packet(packet, **(request_kwargs or {}))
    if mutate is not None:
        mutate(request, packet)
    return {
        "schema_version": 1,
        "keep": [
            directive["id"] for target in packet["targets"] for directive in target["directives"]
        ],
        "changes": [],
        "new_rule_suggestions": [],
        "decision_request": request,
        "unresolved_conflicts": [],
    }


def _create_decision_archive(
    config_factory: ConfigFactory,
    *,
    with_import: bool = False,
    tricky_config_path: bool = False,
) -> DecisionArchive:
    original_text = (
        "# Deployment\n\n"
        "- Deploy automatically after release.\n\n"
        "- Never deploy automatically; require an operator handoff before deployment.\n"
    )
    if with_import:
        original_text += "\n@deployment-context.md\n"
    config, (target,) = config_factory(
        (original_text,),
        target_names=("CLAUDE.md",),
    )
    if tricky_config_path:
        config = replace(
            config,
            config_path=target.parent / "config path" / "owner's meditate.toml",
        )
    imported = None
    if with_import:
        imported = target.parent / "deployment-context.md"
        imported.write_text(
            "# Context\n\n- Preserve the loaded deployment boundary.\n",
            encoding="utf-8",
        )
    events = _conflicting_events()
    provider = StubProvider(_decision_plan)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    inspected = inspection(config, events)
    directive_ids = frozenset(
        directive.id
        for target_record in inspected.targets
        for directive in target_record.directives
    )
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspected,
    )
    return DecisionArchive(
        config=config,
        target=target,
        original=original_text.encode("utf-8"),
        plan=plan,
        request=plan.raw_plan["decision_request"],
        directive_ids=directive_ids,
        events=events,
        imported=imported,
    )


def _dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _lists(value: Any) -> Iterator[list[Any]]:
    if isinstance(value, dict):
        for child in value.values():
            yield from _lists(child)
    elif isinstance(value, list):
        yield value
        for child in value:
            yield from _lists(child)


def _markdown_outside_literal_regions(markdown: str) -> str:
    without_fences = re.sub(r"```.*?```|~~~.*?~~~", "", markdown, flags=re.DOTALL)
    without_html_code = re.sub(
        r"<(?:pre|code)\b[^>]*>.*?</(?:pre|code)>",
        "",
        without_fences,
        flags=re.DOTALL | re.IGNORECASE,
    )
    without_indented_code = re.sub(r"(?m)^(?: {4}|\t).*$", "", without_html_code)
    without_inline_code = re.sub(
        r"\\`[^`\n]*\\`|`[^`\n]*`",
        "",
        without_indented_code,
    )
    return re.sub(
        r"(?:&#96;|&#x60;).*?(?:&#96;|&#x60;)",
        "",
        without_inline_code,
        flags=re.IGNORECASE,
    )


def _run_ids(config: Config) -> set[str]:
    root = config.data_root / "runs"
    if not root.exists():
        return set()
    return {path.name for path in root.iterdir() if path.is_dir()}


def _invoke_main(arguments: list[str]) -> int:
    try:
        return main(arguments)
    except SystemExit as caught:
        return int(caught.code)


def _bind_cli_config(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    monkeypatch.setattr(cli, "load_config", lambda _path: config)


def _patch_cli_provider(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    model_id: str,
) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []

    def complete(
        _provider: AnthropicProvider,
        *,
        system: str,
        payload: str,
        schema: dict[str, Any],
    ) -> tuple[str, RunUsage]:
        assert system
        assert schema["type"] == "object"
        packet = json.loads(payload)
        packets.append(packet)
        return json.dumps(builder(packet)), RunUsage(
            calls=1,
            actual_input_tokens=1,
            actual_output_tokens=1,
            stop_reason="end_turn",
            model_id=model_id,
        )

    monkeypatch.setattr(AnthropicProvider, "complete", complete)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    return packets


def _matching_request(payload: Any, request_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in _dicts(payload)
        if item.get("request_id") == request_id and "options" in item and "question" in item
    ]
    assert matches, f"request {request_id} is missing"
    return matches[0]


def _successor_run_id(
    payload: Any,
    *,
    parent_run_id: str,
    before_run_ids: set[str],
    config: Config,
) -> str:
    new_run_ids = _run_ids(config) - before_run_ids
    assert len(new_run_ids) == 1
    successor = new_run_ids.pop()
    assert successor != parent_run_id
    assert any(
        item.get("run_id") == successor or item.get("successor_run_id") == successor
        for item in _dicts(payload)
    )
    return successor


def _operator_decision(payload: Any, request_id: str) -> dict[str, Any]:
    required = {
        "parent_run_id",
        "parent_plan_sha256",
        "parent_packet_sha256",
        "request_id",
        "conflict_fingerprint",
        "response_kind",
        "response_text",
        "response_sha256",
    }
    matches = [
        item
        for item in _dicts(payload)
        if item.get("request_id") == request_id and required <= set(item)
    ]
    assert matches, "operator_decision is missing required lineage fields"
    return matches[0]


def _assert_operator_asserted_not_identity_attested(decision: dict[str, Any]) -> None:
    authority_values = [
        str(value).lower()
        for item in _dicts(decision)
        for key, value in item.items()
        if "authority" in key.lower() or key.lower() == "kind"
    ]
    assert any("operator" in value and "assert" in value for value in authority_values)
    identity_markers = {
        key: value
        for item in _dicts(decision)
        for key, value in item.items()
        if "identity" in key.lower() or "authenticated" in key.lower()
    }
    explicit_negative_identity = any(
        value is False
        or "not_attested" in str(value).lower()
        or "not_authenticated" in str(value).lower()
        or str(value).lower() == "not_provided"
        for value in identity_markers.values()
    )
    combined_authority = " ".join(authority_values)
    assert explicit_negative_identity or (
        "identity" in combined_authority
        and ("not" in combined_authority or "unattested" in combined_authority)
    )


def _jsonl_records(config: Config) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in config.state_root.rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _assert_decision_jsonl_contains_no_raw_text(
    records: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    response_text: str | None = None,
) -> None:
    serialized = "\n".join(json.dumps(record, sort_keys=True) for record in records)
    forbidden_text = [
        request["subject_a"],
        request["subject_b"],
        request["question"],
        request["recommendation_rationale"],
        *[
            option[field]
            for option in request["options"]
            for field in ("label", "consequence", "rationale")
        ],
    ]
    if response_text is not None:
        forbidden_text.append(response_text)
    for raw_text in forbidden_text:
        assert raw_text not in serialized
    assert not any(
        "question" in item or "options" in item or "response_text" in item
        for record in records
        for item in _dicts(record)
    )


def _decision_object_schema() -> dict[str, Any]:
    schema = PLAN_SCHEMA["properties"]["decision_request"]
    schema_type = schema.get("type")
    if schema_type == "object" or (isinstance(schema_type, list) and "object" in schema_type):
        return schema
    for keyword in ("oneOf", "anyOf"):
        for branch in schema.get(keyword, []):
            if branch.get("type") == "object":
                return branch
    raise AssertionError("decision_request must have a nullable object schema")


def test_equal_authority_conflict_creates_one_local_bounded_decision_without_changes(
    config_factory: ConfigFactory,
) -> None:
    archive = _create_decision_archive(config_factory)
    request = archive.request
    known_directive_ids = archive.directive_ids
    known_evidence_ids = {event.id for event in archive.events}

    assert request["request_id"]
    assert len(request["conflict_fingerprint"]) == 64
    assert set(request["directive_ids"]) <= known_directive_ids
    assert set(request["evidence_ids"]) <= known_evidence_ids
    assert len(request["options"]) == 3
    assert [option["key"] for option in request["options"]] == ["a", "b", "c"]
    assert request["options"][0]["recommended"] is True
    assert all("recommended" not in option for option in request["options"][1:])
    assert len({option["label"] for option in request["options"]}) == 3
    assert set(request["custom"]) == {"key", "label", "max_chars"}
    assert request["custom"]["key"] == "custom"
    assert request["custom"]["label"].strip()
    assert request["custom"]["max_chars"] == 2_000
    assert request["question"] == (
        f"I’m trying to resolve {SUBJECT_A} and {SUBJECT_B}. Would you prefer "
        f"{OPTION_A} (recommended), {OPTION_B}, {OPTION_C}, or something else?"
    )

    assert archive.plan.changed_directive_count == 0
    assert archive.target.read_bytes() == archive.original
    assert next(iter(archive.plan.proposed_contents.values())).encode("utf-8") == archive.original
    assert set(archive.plan.raw_plan["keep"]) == known_directive_ids

    run_dir = archive.config.data_root / "runs" / archive.plan.run_id
    assert "decision_required" in archive.plan.blocked_reasons
    archived_plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    archived_requests = [
        item
        for item in _dicts(archived_plan)
        if "request_id" in item and "options" in item and "question" in item
    ]
    assert archived_requests == [request]
    assert "decision_required" in archived_plan["blocked_reasons"]
    assert "decision_required" in manifest["blocked_reasons"]
    target_record = manifest["targets"][0]
    assert target_record["changed"] is False
    assert target_record["changed_directives"] == 0
    assert target_record["directive_delta"] == 0
    assert target_record["byte_delta"] == 0
    assert target_record["line_delta"] == 0
    assert (run_dir / target_record["pre_blob"]).read_bytes() == archive.original
    assert (run_dir / target_record["post_blob"]).read_bytes() == archive.original

    report_json_path, _report_markdown_path = write_plan_report(archive.config, archive.plan)
    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert any(item.get("request_id") == request["request_id"] for item in _dicts(report))
    assert not any(item.get("apply_command") for item in _dicts(report) if "apply_command" in item)
    with pytest.raises(MeditateError) as caught:
        apply_run(
            archive.config,
            archive.plan.run_id,
            mode="attended",
            approval_sha256=archive.plan.plan_sha256,
        )
    assert caught.value.code == "decision_required"


def test_model_decision_schema_is_advisory_and_locally_enriched() -> None:
    assert "decision_request" in PLAN_SCHEMA["required"]
    schema = _decision_object_schema()
    nullable_schema = PLAN_SCHEMA["properties"]["decision_request"]
    nullable_type = nullable_schema.get("type")
    assert (
        isinstance(nullable_type, list)
        and "null" in nullable_type
        or any(
            branch.get("type") == "null"
            for keyword in ("oneOf", "anyOf")
            for branch in nullable_schema.get(keyword, [])
        )
    )
    expected_fields = {
        "subject_a",
        "subject_b",
        "directive_ids",
        "evidence_ids",
        "options",
        "recommendation_rationale",
    }
    assert set(schema["properties"]) == expected_fields
    assert set(schema["required"]) == expected_fields
    assert schema["additionalProperties"] is False
    option_schema = schema["properties"]["options"]
    assert {"minItems", "maxItems"}.isdisjoint(option_schema)
    assert set(option_schema["items"]["properties"]) == {
        "label",
        "consequence",
        "rationale",
        "evidence_ids",
    }
    assert set(option_schema["items"]["required"]) == {
        "label",
        "consequence",
        "rationale",
        "evidence_ids",
    }
    assert option_schema["items"]["additionalProperties"] is False
    for field in ("label", "consequence", "rationale"):
        field_schema = option_schema["items"]["properties"][field]
        assert {"minLength", "maxLength"}.isdisjoint(field_schema)
    for field_schema in (
        option_schema["items"]["properties"]["evidence_ids"],
        schema["properties"]["directive_ids"],
        schema["properties"]["evidence_ids"],
    ):
        assert {"minItems", "maxItems"}.isdisjoint(field_schema)
    for field in ("subject_a", "subject_b", "recommendation_rationale"):
        assert {"minLength", "maxLength"}.isdisjoint(schema["properties"][field])

    forbidden = {
        "answer",
        "selection",
        "status",
        "key",
        "recommended",
        "recommended_index",
        "request_id",
        "fingerprint",
        "conflict_fingerprint",
        "question",
        "custom",
    }
    schema_property_names = {name for item in _dicts(schema) for name in item.get("properties", {})}
    assert schema_property_names.isdisjoint(forbidden)


def test_provider_schema_omits_anthropic_unsupported_validation_keywords(
    config_factory: ConfigFactory,
) -> None:
    config, _targets = config_factory(
        ("# Rules\n\n- Preserve hand edits.\n",),
        target_names=("CLAUDE.md",),
    )
    provider = StubProvider(keep_all)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    create_plan(config, provider=provider, inspection=inspection(config, ()))

    assert provider.calls == 1
    assert provider.last_schema is not None
    unsupported_keywords = {
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
    }
    schema_nodes = list(_dicts(provider.last_schema))
    assert schema_nodes
    for schema_node in schema_nodes:
        assert unsupported_keywords.isdisjoint(schema_node), schema_node


@pytest.mark.parametrize(
    "case",
    [
        "answer",
        "selection",
        "status",
        "request_id",
        "fingerprint",
        "question",
        "custom",
        "option_key",
        "option_recommended",
        "unknown_directive",
        "unknown_evidence",
        "option_unknown_evidence",
        "one_directive",
        "one_evidence",
        "ungrounded_subject",
        "secret_subject",
        "secret_recommendation",
        "secret_option",
        "two_options",
        "four_options",
        "duplicate_options",
        "empty_subject",
        "empty_label",
        "empty_rationale",
        "empty_option_evidence",
        "overlong_label",
        "overlong_recommendation",
    ],
)
def test_invalid_model_decision_requests_fail_before_archive(
    config_factory: ConfigFactory,
    case: str,
) -> None:
    config, _targets = config_factory(
        (
            "# Deployment\n\n"
            "- Deploy automatically after release.\n\n"
            "- Never deploy automatically; require an operator handoff before deployment.\n",
        ),
        target_names=("CLAUDE.md",),
    )

    def mutate(request: dict[str, Any], _packet: dict[str, Any]) -> None:
        if case in {"answer", "selection", "status", "request_id", "fingerprint", "question"}:
            request[case] = "model-authored-forbidden-value"
        elif case == "custom":
            request["custom"] = True
        elif case == "option_key":
            request["options"][0]["key"] = "a"
        elif case == "option_recommended":
            request["options"][0]["recommended"] = True
        elif case == "unknown_directive":
            request["directive_ids"][0] = "dir_unknown"
        elif case == "unknown_evidence":
            request["evidence_ids"][0] = "evt_unknown"
        elif case == "option_unknown_evidence":
            request["options"][0]["evidence_ids"] = ["evt_unknown"]
        elif case == "one_directive":
            request["directive_ids"] = request["directive_ids"][:1]
        elif case == "one_evidence":
            request["evidence_ids"] = request["evidence_ids"][:1]
        elif case == "ungrounded_subject":
            request["subject_a"] = "unrelated database engine selection"
        elif case == "secret_subject":
            request["subject_a"] = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
        elif case == "secret_recommendation":
            request["recommendation_rationale"] = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
        elif case == "secret_option":
            request["options"][0]["consequence"] = (
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
            )
        elif case == "two_options":
            request["options"] = request["options"][:2]
        elif case == "four_options":
            request["options"].append(dict(request["options"][0]))
        elif case == "duplicate_options":
            request["options"][1] = dict(request["options"][0])
        elif case == "empty_subject":
            request["subject_a"] = ""
        elif case == "empty_label":
            request["options"][0]["label"] = ""
        elif case == "empty_rationale":
            request["options"][0]["rationale"] = ""
        elif case == "empty_option_evidence":
            request["options"][0]["evidence_ids"] = []
        elif case == "overlong_label":
            request["options"][0]["label"] = "x" * 2_001
        elif case == "overlong_recommendation":
            request["recommendation_rationale"] = "x" * 2_001
        else:
            raise AssertionError(case)

    provider = StubProvider(lambda packet: _decision_plan(packet, mutate=mutate))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, _conflicting_events()),
        )
    assert not (config.data_root / "runs").exists()


@pytest.mark.parametrize("line_control", ["\n", "\r"], ids=["lf", "cr"])
@pytest.mark.parametrize(
    "display_field",
    [
        "subject_a",
        "subject_b",
        "option_label",
        "option_consequence",
        "option_rationale",
        "recommendation_rationale",
    ],
)
def test_model_decision_display_fields_reject_cr_or_lf_before_archive(
    config_factory: ConfigFactory,
    display_field: str,
    line_control: str,
) -> None:
    config, _targets = config_factory(
        (
            "# Deployment\n\n"
            "- Deploy automatically after release.\n\n"
            "- Never deploy automatically; require an operator handoff before deployment.\n",
        ),
        target_names=("CLAUDE.md",),
    )

    def mutate(request: dict[str, Any], _packet: dict[str, Any]) -> None:
        if display_field.startswith("option_"):
            option_field = display_field.removeprefix("option_")
            request["options"][0][option_field] += line_control + "injected display line"
        else:
            request[display_field] += line_control + "injected display line"

    provider = StubProvider(lambda packet: _decision_plan(packet, mutate=mutate))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, _conflicting_events()),
        )
    assert provider.calls == 1
    assert not (config.data_root / "runs").exists()


def test_compatible_directives_cannot_be_promoted_to_a_decision_request(
    config_factory: ConfigFactory,
) -> None:
    config, _targets = config_factory(
        (
            "# Reports\n\n"
            "- Keep the main report concise.\n\n"
            "- Include full diagnostics in an appendix.\n",
        ),
        target_names=("CLAUDE.md",),
    )
    events = (
        _event(
            "evt_concise_report",
            "Keep the main report concise.",
            session_id="report-session-a",
        ),
        _event(
            "evt_diagnostic_appendix",
            "Include full diagnostics in an appendix.",
            session_id="report-session-b",
        ),
    )
    kwargs = {
        "subject_a": "a concise main report",
        "subject_b": "a full diagnostic appendix",
        "labels": (
            "Keep the main report concise",
            "Include full diagnostics in an appendix",
            "Use a concise report with a diagnostic appendix",
        ),
    }
    provider = StubProvider(lambda packet: _decision_plan(packet, request_kwargs=kwargs))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(config, provider=provider, inspection=inspection(config, events))
    assert not (config.data_root / "runs").exists()


def test_generic_positive_negative_action_overlap_is_not_a_true_decision_conflict(
    config_factory: ConfigFactory,
) -> None:
    config, _targets = config_factory(
        (
            "# Staging\n\n"
            "- Deploy completed builds to staging.\n\n"
            "- Never deploy without required tests.\n",
        ),
        target_names=("CLAUDE.md",),
    )
    events = (
        _event(
            "evt_deploy_staging",
            "Deploy completed builds to staging.",
            session_id="staging-session-a",
        ),
        _event(
            "evt_deploy_after_tests",
            "Never deploy without required tests.",
            session_id="staging-session-b",
        ),
    )
    assert events[0].authority == events[1].authority
    assert events[0].scope == events[1].scope
    assert events[0].timestamp == events[1].timestamp

    def compatible_request(packet: dict[str, Any]) -> dict[str, Any]:
        result = _decision_plan(
            packet,
            request_kwargs={
                "subject_a": "deploy completed builds to staging",
                "subject_b": "never deploy without required tests",
                "labels": (
                    "Deploy completed builds to staging",
                    "Require tests before deployment",
                    "Deploy tested builds to staging",
                ),
            },
        )
        request = result["decision_request"]
        request["options"][0].update(
            {
                "consequence": "Completed builds are deployed to staging.",
                "rationale": "The cited staging-deployment evidence is followed.",
            }
        )
        request["options"][1].update(
            {
                "consequence": "Deployment waits until required tests complete.",
                "rationale": "The cited test prerequisite is followed.",
            }
        )
        request["options"][2].update(
            {
                "consequence": "Tested completed builds are deployed to staging.",
                "rationale": "Both cited directives are followed together.",
            }
        )
        request["recommendation_rationale"] = (
            "Deploying tested completed builds satisfies both cited directives."
        )
        return result

    provider = StubProvider(compatible_request)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(config, provider=provider, inspection=inspection(config, events))
    assert provider.calls == 1
    assert not (config.data_root / "runs").exists()


def test_decisions_cli_returns_exact_archived_request_and_rejects_tampering(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)

    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert _matching_request(payload, archive.request["request_id"]) == archive.request
    assert not any(item.get("apply_command") for item in _dicts(payload) if "apply_command" in item)
    assert not any(
        item.get("request_id") == archive.request["request_id"] and "response_text" in item
        for item in _dicts(payload)
    )

    plan_path = archive.config.data_root / "runs" / archive.plan.run_id / "plan.json"
    plan_path.write_bytes(plan_path.read_bytes() + b" ")
    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert archive.target.read_bytes() == archive.original


def test_plain_decisions_labels_model_framing_and_recommendation_as_untrusted_advice(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
            ]
        )
        == 0
    )
    rendered_lines = [
        " ".join(line.lower().split()) for line in capsys.readouterr().out.splitlines()
    ]
    assert any(
        "framing" in line and re.search(r"model[- ]authored", line) and "untrusted" in line
        for line in rendered_lines
    )
    assert any(
        "recommendation" in line and re.search(r"model[- ]authored", line) and "advisory" in line
        for line in rendered_lines
    )


def test_decisions_json_exposes_executable_response_argv_with_exact_config_path(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory, tricky_config_path=True)
    _bind_cli_config(monkeypatch, archive.config)
    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    argv_arrays = [
        [str(part) for part in value]
        for value in _lists(payload)
        if value and all(isinstance(part, str) for part in value)
    ]
    choice_argvs = [argv for argv in argv_arrays if "--choice" in argv]
    custom_argv = next(argv for argv in argv_arrays if "--custom" in argv)
    choices = {argv[argv.index("--choice") + 1]: argv for argv in choice_argvs}
    assert set(choices) == {"a", "b", "c"}
    assert len(choice_argvs) == 3
    for argv in (*choice_argvs, custom_argv):
        assert argv[0:2] == ["meditate", "decide"]
        assert archive.plan.run_id in argv
        assert archive.request["request_id"] in argv
        assert argv[argv.index("--config") + 1] == str(archive.config.config_path)
    assert custom_argv[custom_argv.index("--custom") + 1] == "TEXT"
    custom_command = shlex.join(custom_argv)
    assert shlex.quote(str(archive.config.config_path)) in custom_command
    for model_text in (
        SUBJECT_A,
        SUBJECT_B,
        OPTION_A,
        OPTION_B,
        OPTION_C,
        archive.request["recommendation_rationale"],
    ):
        assert model_text not in " ".join(custom_argv)

    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
            ]
        )
        == 0
    )
    rendered = capsys.readouterr().out
    assert "meditate decide" in rendered
    rendered_argvs: list[list[str]] = []
    for line in rendered.splitlines():
        if "meditate decide" not in line:
            continue
        fragment = line[line.index("meditate decide") :].strip().strip("`")
        rendered_argvs.append(shlex.split(fragment))
    assert rendered_argvs
    rendered_choice_argvs = [argv for argv in rendered_argvs if "--choice" in argv]
    assert {argv[argv.index("--choice") + 1] for argv in rendered_choice_argvs} == {"a", "b", "c"}
    assert len(rendered_choice_argvs) == 3
    assert any("--custom" in argv and "TEXT" in argv for argv in rendered_argvs)
    assert all(
        argv[argv.index("--config") + 1] == str(archive.config.config_path)
        for argv in rendered_argvs
    )
    rendered_custom_argv = next(argv for argv in rendered_argvs if "--custom" in argv)
    assert rendered_custom_argv[rendered_custom_argv.index("--custom") + 1] == "TEXT"
    for model_text in (SUBJECT_A, SUBJECT_B, OPTION_A, OPTION_B, OPTION_C):
        assert model_text not in " ".join(rendered_custom_argv)


@pytest.mark.parametrize(
    "response_arguments",
    [
        (),
        ("--choice", "a", "--custom", "Use a custom response."),
        ("--choice", "d"),
        ("--custom", "x" * 2_001),
        ("--custom", "contains\x00nul"),
        ("--custom", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"),
    ],
)
def test_decide_cli_rejects_missing_conflicting_invalid_or_unsafe_responses(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response_arguments: tuple[str, ...],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    before_run_ids = _run_ids(archive.config)

    code = _invoke_main(
        [
            "decide",
            archive.plan.run_id,
            archive.request["request_id"],
            *response_arguments,
            "--config",
            str(archive.config.config_path),
            "--json",
        ]
    )
    capsys.readouterr()
    assert code == 2
    assert packets == []
    assert _run_ids(archive.config) == before_run_ids
    assert archive.target.read_bytes() == archive.original


def test_decide_cli_rejects_unknown_request_before_provider_call(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                "request_unknown",
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert packets == []
    assert _run_ids(archive.config) == before_run_ids


@pytest.mark.parametrize(
    ("response_arguments", "response_kind", "choice_key", "response_text"),
    [
        (("--choice", "a"), "choice", "a", OPTION_A),
        (
            ("--custom", "Wait for the release operator's written authorization."),
            "custom",
            None,
            "Wait for the release operator's written authorization.",
        ),
    ],
)
def test_decide_creates_immutable_hash_bound_successor_with_exact_response(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response_arguments: tuple[str, ...],
    response_kind: str,
    choice_key: str | None,
    response_text: str,
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    parent_run_dir = archive.config.data_root / "runs" / archive.plan.run_id
    parent_snapshot = {
        path.relative_to(parent_run_dir): path.read_bytes()
        for path in parent_run_dir.rglob("*")
        if path.is_file()
    }
    before_run_ids = _run_ids(archive.config)

    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                *response_arguments,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    successor_run_id = _successor_run_id(
        cli_payload,
        parent_run_id=archive.plan.run_id,
        before_run_ids=before_run_ids,
        config=archive.config,
    )
    assert packets
    decision = _operator_decision(packets[-1], archive.request["request_id"])
    parent_packet_path = parent_run_dir / "evidence.json"
    assert decision["parent_run_id"] == archive.plan.run_id
    assert decision["parent_plan_sha256"] == archive.plan.plan_sha256
    assert decision["parent_packet_sha256"] == sha256_bytes(parent_packet_path.read_bytes())
    assert decision["request_id"] == archive.request["request_id"]
    assert decision["conflict_fingerprint"] == archive.request["conflict_fingerprint"]
    assert decision["response_kind"] == response_kind
    assert decision["response_text"] == response_text
    assert decision["response_sha256"] == sha256_bytes(response_text.encode("utf-8"))
    if choice_key is None:
        assert decision.get("choice_key") in (None, "")
    else:
        assert decision["choice_key"] == choice_key
    _assert_operator_asserted_not_identity_attested(decision)

    assert archive.target.read_bytes() == archive.original
    assert {
        path.relative_to(parent_run_dir): path.read_bytes()
        for path in parent_run_dir.rglob("*")
        if path.is_file()
    } == parent_snapshot

    successor_run_dir = archive.config.data_root / "runs" / successor_run_id
    successor_surfaces = [
        json.loads((successor_run_dir / name).read_text(encoding="utf-8"))
        for name in ("evidence.json", "plan.json", "manifest.json")
    ]
    report_json_path = Path(cli_payload["plan_report_json"])
    report_markdown_path = Path(cli_payload["plan_report_markdown"])
    successor_surfaces.append(json.loads(report_json_path.read_text(encoding="utf-8")))
    for surface in successor_surfaces:
        assert decision in list(_dicts(surface))
    markdown = report_markdown_path.read_text(encoding="utf-8")
    for marker in (
        archive.plan.plan_sha256,
        archive.request["request_id"],
        archive.request["conflict_fingerprint"],
        response_text,
        decision["response_sha256"],
    ):
        assert marker in markdown

    log_records = _jsonl_records(archive.config)
    _assert_decision_jsonl_contains_no_raw_text(
        log_records,
        archive.request,
        response_text=response_text,
    )
    assert any(
        all(
            marker in json.dumps(record, sort_keys=True)
            for marker in (
                successor_run_id,
                archive.plan.run_id,
                archive.plan.plan_sha256,
                archive.request["request_id"],
                archive.request["conflict_fingerprint"],
                decision["response_sha256"],
            )
        )
        for record in log_records
    )

    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    decisions_payload = json.loads(capsys.readouterr().out)
    assert _matching_request(decisions_payload, archive.request["request_id"]) == archive.request
    assert decision in list(_dicts(decisions_payload))


def test_markdown_metacharacter_custom_response_is_exact_in_json_and_literal_in_report(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    custom_response = (
        "# [Review](https://example.invalid/operator-choice)\n\n`meditate apply --unattended`"
    )
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--custom",
                custom_response,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    successor_run_id = _successor_run_id(
        cli_payload,
        parent_run_id=archive.plan.run_id,
        before_run_ids=before_run_ids,
        config=archive.config,
    )
    response_sha256 = sha256_bytes(custom_response.encode("utf-8"))
    decision = _operator_decision(packets[-1], archive.request["request_id"])
    assert decision["response_text"] == custom_response
    assert decision["response_sha256"] == response_sha256

    successor_run_dir = archive.config.data_root / "runs" / successor_run_id
    private_json = [
        json.loads((successor_run_dir / name).read_text(encoding="utf-8"))
        for name in ("evidence.json", "plan.json", "manifest.json")
    ]
    report_json_path = Path(cli_payload["plan_report_json"])
    report_markdown_path = Path(cli_payload["plan_report_markdown"])
    private_json.append(json.loads(report_json_path.read_text(encoding="utf-8")))
    for payload in private_json:
        stored = _operator_decision(payload, archive.request["request_id"])
        assert stored["response_text"] == custom_response
        assert stored["response_sha256"] == response_sha256

    markdown = report_markdown_path.read_text(encoding="utf-8")
    assert "Review" in markdown
    assert "https://example.invalid/operator-choice" in markdown
    assert "meditate apply --unattended" in markdown
    outside_literals = _markdown_outside_literal_regions(markdown)
    assert not re.search(
        r"(?m)^\s{0,3}#{1,6}\s+\[Review\]",
        outside_literals,
    )
    assert not re.search(
        r"(?<!\\)\[Review\]\(https://example\.invalid/operator-choice\)",
        outside_literals,
    )
    assert "meditate apply --unattended" not in outside_literals
    assert archive.target.read_bytes() == archive.original


def test_decide_replay_is_rejected_without_mutating_parent_or_target(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    _patch_cli_provider(monkeypatch, keep_all, model_id=archive.config.llm.model)
    arguments = [
        "decide",
        archive.plan.run_id,
        archive.request["request_id"],
        "--choice",
        "a",
        "--config",
        str(archive.config.config_path),
        "--json",
    ]
    assert _invoke_main(arguments) == 0
    capsys.readouterr()
    after_first = _run_ids(archive.config)
    assert _invoke_main(arguments) == 2
    capsys.readouterr()
    assert _run_ids(archive.config) == after_first
    assert archive.target.read_bytes() == archive.original


def test_purging_successor_preserves_hash_only_single_use_decision_marker(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    custom_response = "Use the synthetic operator-only deployment resolution."
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--custom",
                custom_response,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    resolved_payload = json.loads(capsys.readouterr().out)
    successor_run_id = _successor_run_id(
        resolved_payload,
        parent_run_id=archive.plan.run_id,
        before_run_ids=before_run_ids,
        config=archive.config,
    )
    successor_run_dir = archive.config.data_root / "runs" / successor_run_id
    successor_plan = json.loads((successor_run_dir / "plan.json").read_text(encoding="utf-8"))
    successor_plan_sha256 = successor_plan["plan_sha256"]
    successor_report_paths = (
        Path(resolved_payload["plan_report_json"]),
        Path(resolved_payload["plan_report_markdown"]),
    )
    assert all(path.is_file() for path in successor_report_paths)
    decision = _operator_decision(packets[-1], archive.request["request_id"])
    response_sha256 = sha256_bytes(custom_response.encode("utf-8"))
    assert decision["response_text"] == custom_response
    assert decision["response_sha256"] == response_sha256

    purge_result = purge_run(archive.config, successor_run_id, execute=True)
    assert purge_result["executed"] is True
    assert not successor_run_dir.exists()
    assert all(not path.exists() for path in successor_report_paths)
    tombstone = archive.config.data_root / "tombstones" / f"{successor_run_id}.json"
    assert tombstone.is_file()
    tombstone_text = tombstone.read_text(encoding="utf-8")
    assert custom_response not in tombstone_text
    assert archive.request["question"] not in tombstone_text
    for option in archive.request["options"]:
        for field in ("label", "consequence", "rationale"):
            assert option[field] not in tombstone_text

    remaining_log_records = _jsonl_records(archive.config)
    _assert_decision_jsonl_contains_no_raw_text(
        remaining_log_records,
        archive.request,
        response_text=custom_response,
    )
    assert response_sha256 in json.dumps(remaining_log_records, sort_keys=True)

    runs_after_purge = _run_ids(archive.config)
    provider_calls_after_resolution = len(packets)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert len(packets) == provider_calls_after_resolution
    assert _run_ids(archive.config) == runs_after_purge

    assert (
        _invoke_main(
            [
                "decisions",
                archive.plan.run_id,
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    decisions_payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(decisions_payload, sort_keys=True)
    assert "resolved" in serialized.lower()
    assert "purged" in serialized.lower()
    assert custom_response not in serialized
    assert "meditate decide" not in serialized
    assert "--choice" not in serialized
    assert "--custom" not in serialized
    assert not any(
        "response_text" in item
        or any("response_form" in key or key.endswith("_argv") for key in item)
        for item in _dicts(decisions_payload)
    )
    assert not any(
        "--choice" in value or "--custom" in value
        for value in _lists(decisions_payload)
        if all(isinstance(part, str) for part in value)
    )
    durable_markers = [
        item
        for item in _dicts(decisions_payload)
        if item.get("request_id") == archive.request["request_id"]
        and item.get("response_sha256") == response_sha256
    ]
    assert len(durable_markers) == 1
    marker = durable_markers[0]
    assert marker["parent_run_id"] == archive.plan.run_id
    assert marker["parent_plan_sha256"] == archive.plan.plan_sha256
    assert marker["conflict_fingerprint"] == archive.request["conflict_fingerprint"]
    assert marker["successor_run_id"] == successor_run_id
    assert marker["successor_plan_sha256"] == successor_plan_sha256
    forbidden_marker_fields = {
        "choice_key",
        "response_kind",
        "response_text",
        "custom",
        "custom_text",
        "option",
        "option_label",
        "rationale",
        "consequence",
    }
    assert set(marker).isdisjoint(forbidden_marker_fields)
    assert archive.target.read_bytes() == archive.original


def test_decide_replays_frozen_sanitized_evidence_and_ignores_appended_history(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    history = archive.config.sources.claude_home / "history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    appended_text = "This history record was appended after the parent plan was archived."
    history.write_text(
        json.dumps(
            {
                "display": appended_text,
                "timestamp": 1_776_510_000_000,
                "sessionId": "later-live-history",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    parent_packet = json.loads(
        (archive.config.data_root / "runs" / archive.plan.run_id / "evidence.json").read_text(
            encoding="utf-8"
        )
    )
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    before_run_ids = _run_ids(archive.config)

    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    successor_run_id = _successor_run_id(
        cli_payload,
        parent_run_id=archive.plan.run_id,
        before_run_ids=before_run_ids,
        config=archive.config,
    )
    assert len(packets) == 1
    successor_packet = packets[0]
    for event in parent_packet["evidence_events_oldest_to_newest"]:
        assert event in successor_packet["evidence_events_oldest_to_newest"]
    assert appended_text not in json.dumps(successor_packet)
    archived_successor_packet = (
        archive.config.data_root / "runs" / successor_run_id / "evidence.json"
    ).read_text(encoding="utf-8")
    assert appended_text not in archived_successor_packet
    assert archive.target.read_bytes() == archive.original


@pytest.mark.parametrize(
    "drift",
    ["target", "import_graph", "config", "prompt", "parser", "resolved_model"],
)
def test_decide_requires_unchanged_structural_context_but_not_live_history(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    drift: str,
) -> None:
    archive = _create_decision_archive(
        config_factory,
        with_import=drift == "import_graph",
    )
    live_config = archive.config
    if drift == "target":
        archive.target.write_text(
            archive.original.decode("utf-8") + "\n- Drifted target bytes.\n",
            encoding="utf-8",
        )
    elif drift == "import_graph":
        assert archive.imported is not None
        archive.imported.write_text(
            "# Context\n\n- Drifted imported context.\n",
            encoding="utf-8",
        )
    elif drift == "config":
        live_config = replace(archive.config, raw_bytes=b"synthetic-config-drift\n")
    elif drift == "prompt":
        patched = False
        for module in (plan_module, transaction, cli, decisions):
            if hasattr(module, "PLAN_PROMPT_VERSION"):
                monkeypatch.setattr(module, "PLAN_PROMPT_VERSION", "future-prompt")
                patched = True
        assert patched
    elif drift == "parser":
        patched = False
        for module in (plan_module, transaction, cli, decisions):
            if hasattr(module, "PARSER_VERSION"):
                monkeypatch.setattr(module, "PARSER_VERSION", "future-parser")
                patched = True
        assert patched
    elif drift != "resolved_model":
        raise AssertionError(drift)

    _bind_cli_config(monkeypatch, live_config)
    model_id = "api-resolved-model-drift" if drift == "resolved_model" else archive.config.llm.model
    packets = _patch_cli_provider(monkeypatch, keep_all, model_id=model_id)
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    if drift == "resolved_model":
        assert len(packets) == 1
    else:
        assert packets == []
    assert _run_ids(archive.config) == before_run_ids
    if drift != "target":
        assert archive.target.read_bytes() == archive.original


def test_decide_rejects_corrupt_parent_evidence_before_provider_call(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    packet_path = archive.config.data_root / "runs" / archive.plan.run_id / "evidence.json"
    packet_path.write_bytes(packet_path.read_bytes() + b" ")
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        keep_all,
        model_id=archive.config.llm.model,
    )
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert packets == []
    assert _run_ids(archive.config) == before_run_ids
    assert archive.target.read_bytes() == archive.original


def test_successor_cannot_repeat_the_same_conflict_fingerprint(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    packets = _patch_cli_provider(
        monkeypatch,
        _decision_plan,
        model_id=archive.config.llm.model,
    )
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert len(packets) == 1
    assert _run_ids(archive.config) == before_run_ids
    assert archive.target.read_bytes() == archive.original


def _lane_decision_plan(packet: dict[str, Any], lane: int) -> dict[str, Any]:
    enabled_text = f"Enable deployment lane {lane}."
    disabled_text = f"Disable deployment lane {lane}."
    directives = [directive for target in packet["targets"] for directive in target["directives"]]
    enabled = next(item for item in directives if enabled_text in item["text"])
    disabled = next(item for item in directives if disabled_text in item["text"])
    evidence_by_id = {item["id"]: item for item in packet["evidence_events_oldest_to_newest"]}
    enabled_evidence = evidence_by_id[f"evt_lane_{lane}_enabled"]
    disabled_evidence = evidence_by_id[f"evt_lane_{lane}_disabled"]
    request = {
        "subject_a": f"enable deployment lane {lane}",
        "subject_b": f"disable deployment lane {lane}",
        "directive_ids": [enabled["id"], disabled["id"]],
        "evidence_ids": [enabled_evidence["id"], disabled_evidence["id"]],
        "options": [
            {
                "label": enabled_text,
                "consequence": f"Deployment lane {lane} remains enabled.",
                "rationale": "The cited enabled-lane evidence is followed.",
                "evidence_ids": [enabled_evidence["id"]],
            },
            {
                "label": disabled_text,
                "consequence": f"Deployment lane {lane} remains disabled.",
                "rationale": "The cited disabled-lane evidence is followed.",
                "evidence_ids": [disabled_evidence["id"]],
            },
            {
                "label": f"Defer deployment lane {lane} to repository policy.",
                "consequence": "The loaded repository policy chooses the lane state.",
                "rationale": "Both cited constraints remain visible pending scoped policy.",
                "evidence_ids": [enabled_evidence["id"], disabled_evidence["id"]],
            },
        ],
        "recommendation_rationale": (
            f"Enabling deployment lane {lane} is the first equally authoritative option."
        ),
    }
    return {
        "schema_version": 1,
        "keep": [directive["id"] for directive in directives],
        "changes": [],
        "new_rule_suggestions": [],
        "decision_request": request,
        "unresolved_conflicts": [],
    }


def _create_depth_archive(config_factory: ConfigFactory) -> DecisionArchive:
    lane_count = 5
    body = "# Deployment lanes\n\n" + "\n\n".join(
        directive
        for lane in range(lane_count)
        for directive in (
            f"- Enable deployment lane {lane}.",
            f"- Disable deployment lane {lane}.",
        )
    )
    original_text = body + "\n"
    config, (target,) = config_factory(
        (original_text,),
        target_names=("CLAUDE.md",),
    )
    events = tuple(
        _event(
            f"evt_lane_{lane}_{state}",
            f"{verb} deployment lane {lane}.",
            session_id=f"lane-{lane}-{state}-session",
        )
        for lane in range(lane_count)
        for state, verb in (("enabled", "Enable"), ("disabled", "Disable"))
    )
    inspected = inspection(config, events)
    provider = StubProvider(lambda packet: _lane_decision_plan(packet, 0))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    plan = create_plan(config, provider=provider, inspection=inspected)
    return DecisionArchive(
        config=config,
        target=target,
        original=original_text.encode("utf-8"),
        plan=plan,
        request=plan.raw_plan["decision_request"],
        directive_ids=frozenset(
            directive.id
            for target_record in inspected.targets
            for directive in target_record.directives
        ),
        events=events,
    )


def _answer_and_read_next_question(
    archive: DecisionArchive,
    current_run_id: str,
    current_request: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> tuple[str, dict[str, Any]]:
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                current_run_id,
                current_request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    successor_run_id = _successor_run_id(
        cli_payload,
        parent_run_id=current_run_id,
        before_run_ids=before_run_ids,
        config=archive.config,
    )
    successor_plan = json.loads(
        (archive.config.data_root / "runs" / successor_run_id / "plan.json").read_text(
            encoding="utf-8"
        )
    )
    request_matches = [
        item
        for item in _dicts(successor_plan)
        if item.get("request_id")
        and "conflict_fingerprint" in item
        and "options" in item
        and "question" in item
    ]
    assert len(request_matches) == 1
    return successor_run_id, request_matches[0]


def test_third_operator_decision_succeeds_with_terminal_depth_three_successor(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_depth_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    next_lane = 1

    def two_questions_then_terminal(packet: dict[str, Any]) -> dict[str, Any]:
        nonlocal next_lane
        if next_lane <= 2:
            result = _lane_decision_plan(packet, next_lane)
            next_lane += 1
            return result
        return keep_all(packet)

    packets = _patch_cli_provider(
        monkeypatch,
        two_questions_then_terminal,
        model_id=archive.config.llm.model,
    )
    current_run_id = archive.plan.run_id
    current_request = archive.request

    for _question_number in range(2):
        current_run_id, current_request = _answer_and_read_next_question(
            archive,
            current_run_id,
            current_request,
            capsys,
        )

    before_third = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                current_run_id,
                current_request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    terminal_run_id = _successor_run_id(
        cli_payload,
        parent_run_id=current_run_id,
        before_run_ids=before_third,
        config=archive.config,
    )
    terminal_run_dir = archive.config.data_root / "runs" / terminal_run_id
    for surface in (
        cli_payload,
        json.loads((terminal_run_dir / "plan.json").read_text(encoding="utf-8")),
        json.loads((terminal_run_dir / "manifest.json").read_text(encoding="utf-8")),
    ):
        assert not any(
            "request_id" in item and "question" in item and "options" in item
            for item in _dicts(surface)
        )
    assert len(packets) == 3
    assert archive.target.read_bytes() == archive.original


def test_planner_cannot_publish_another_question_at_depth_three(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_depth_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    next_lane = 1

    def always_request_next_lane(packet: dict[str, Any]) -> dict[str, Any]:
        nonlocal next_lane
        result = _lane_decision_plan(packet, next_lane)
        next_lane += 1
        return result

    packets = _patch_cli_provider(
        monkeypatch,
        always_request_next_lane,
        model_id=archive.config.llm.model,
    )
    current_run_id = archive.plan.run_id
    current_request = archive.request
    for _question_number in range(2):
        current_run_id, current_request = _answer_and_read_next_question(
            archive,
            current_run_id,
            current_request,
            capsys,
        )

    before_third = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                current_run_id,
                current_request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert len(packets) == 3
    assert _run_ids(archive.config) == before_third
    assert archive.target.read_bytes() == archive.original


@pytest.mark.parametrize("difference", ["authority", "scope"])
def test_higher_authority_or_scope_conflict_cannot_be_downgraded_to_user_choice(
    config_factory: ConfigFactory,
    difference: str,
) -> None:
    config, _targets = config_factory(
        (
            "# Deployment\n\n"
            "- Deploy automatically after release.\n\n"
            "- Never deploy automatically; require an operator handoff before deployment.\n",
        ),
        target_names=("CLAUDE.md",),
    )
    events = list(_conflicting_events())
    if difference == "authority":
        events[1] = replace(events[1], authority=Authority.AUTO_MEMORY)
    else:
        events[1] = replace(events[1], scope="project")
    provider = StubProvider(_decision_plan)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, tuple(events)),
        )
    assert not (config.data_root / "runs").exists()


def test_newer_equal_authority_equal_scope_evidence_precludes_decision_request(
    config_factory: ConfigFactory,
) -> None:
    original_text = (
        "# Deployment\n\n"
        "- Deploy automatically after release.\n\n"
        "- Never deploy automatically; require an operator handoff before deployment.\n"
    )
    config, (target,) = config_factory(
        (original_text,),
        target_names=("CLAUDE.md",),
    )
    first, second = _conflicting_events()
    older = replace(first, timestamp="2026-08-18T12:00:00Z")
    newer = replace(second, timestamp="2026-08-18T13:00:00Z")
    assert older.authority == newer.authority
    assert older.scope == newer.scope
    provider = StubProvider(_decision_plan)
    provider.name = config.llm.provider
    provider.model = config.llm.model

    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, (older, newer)),
        )
    assert provider.last_packet is not None
    assert [event["id"] for event in provider.last_packet["evidence_events_oldest_to_newest"]] == [
        older.id,
        newer.id,
    ]
    assert not (config.data_root / "runs").exists()
    assert target.read_text(encoding="utf-8") == original_text


def _create_protected_decision_archive(
    config_factory: ConfigFactory,
) -> DecisionArchive:
    original_text = (
        "# Deployment\n\n"
        "- Deploy automatically after release.\n\n"
        "<!-- meditate:protect:start -->\n"
        "- Never deploy automatically; require an operator handoff before deployment.\n"
        "<!-- meditate:protect:end -->\n"
    )
    config, (target,) = config_factory(
        (original_text,),
        target_names=("CLAUDE.md",),
    )
    events = _conflicting_events()
    inspected = inspection(config, events)
    directives = inspected.targets[0].directives
    assert len(directives) == 2
    assert [directive.protected for directive in directives] == [False, True]
    provider = StubProvider(_decision_plan)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    plan = create_plan(config, provider=provider, inspection=inspected)
    return DecisionArchive(
        config=config,
        target=target,
        original=original_text.encode("utf-8"),
        plan=plan,
        request=plan.raw_plan["decision_request"],
        directive_ids=frozenset(
            directive.id
            for target_record in inspected.targets
            for directive in target_record.directives
        ),
        events=events,
    )


def _protected_change_plan(packet: dict[str, Any]) -> dict[str, Any]:
    target = packet["targets"][0]
    directives = target["directives"]
    source = next(directive for directive in directives if "operator handoff" in directive["text"])
    event = next(
        item
        for item in packet["evidence_events_oldest_to_newest"]
        if item["id"] == "evt_operator_handoff"
    )
    return {
        "schema_version": 1,
        "keep": [directive["id"] for directive in directives if directive is not source],
        "changes": [
            {
                "action": "replace",
                "source_ids": [source["id"]],
                "compiled_directive": compiled_directive(
                    "Require two operator handoffs before deployment."
                ),
                "destination_target": target["target"],
                "heading_path": source["heading_path"],
                "evidence_ids": [event["id"]],
                "reason": "The cited handoff preference is made more restrictive.",
                "minimum_apply_mode": "attended",
                "relocation_basis": "",
                "enforcement_target": "",
                "deterministic_check": "",
            }
        ],
        "new_rule_suggestions": [],
        "decision_request": None,
        "unresolved_conflicts": [],
    }


def test_operator_decision_cannot_bypass_protected_directive_guard(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _create_protected_decision_archive(config_factory)
    _bind_cli_config(monkeypatch, archive.config)
    _patch_cli_provider(
        monkeypatch,
        _protected_change_plan,
        model_id=archive.config.llm.model,
    )
    before_run_ids = _run_ids(archive.config)
    assert (
        _invoke_main(
            [
                "decide",
                archive.plan.run_id,
                archive.request["request_id"],
                "--choice",
                "a",
                "--config",
                str(archive.config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert _run_ids(archive.config) == before_run_ids
    assert archive.target.read_bytes() == archive.original


BAD_WORKFLOW = (
    "Run all tests and wait for CI to pass before commit; then merge, release, and deploy."
)
BAD_WORKFLOW_LABEL = "Use the global all-tests-and-CI precondition before commit"
GOOD_WORKFLOW = (
    "Treat cited action lists as coverage, not execution order. Execute commit, merge, release, "
    "and deploy in the exact order required by loaded repository instructions and the documented "
    "workflow. Before each action, run only applicable project-required checks available before "
    "that action at its stage. Treat downstream CI as a check at its own stage, not as a "
    "precondition for earlier actions. Before each remote or irreversible action, explicitly "
    "look up authority in loaded repository instructions. Stop for any required human approval "
    "or named handoff."
)
GOOD_WORKFLOW_LABEL = "Use repository-ordered stage-local workflow checks"


def _workflow_decision_plan(packet: dict[str, Any]) -> dict[str, Any]:
    directives = [directive for target in packet["targets"] for directive in target["directives"]]
    evidence = packet["evidence_events_oldest_to_newest"]
    request = {
        "subject_a": "commit merge release and deploy only after all tests and CI",
        "subject_b": "commit merge release and deploy with checks at each workflow stage",
        "directive_ids": [directives[0]["id"], directives[1]["id"]],
        "evidence_ids": [evidence[0]["id"], evidence[1]["id"]],
        "options": [
            {
                "label": BAD_WORKFLOW_LABEL,
                "consequence": BAD_WORKFLOW,
                "rationale": "The first cited workflow directive is followed.",
                "evidence_ids": [evidence[0]["id"]],
            },
            {
                "label": GOOD_WORKFLOW_LABEL,
                "consequence": GOOD_WORKFLOW,
                "rationale": "The second cited workflow directive is followed.",
                "evidence_ids": [evidence[1]["id"]],
            },
            {
                "label": "Follow the loaded repository workflow without inventing ordering.",
                "consequence": "Repository instructions determine action order and checks.",
                "rationale": (
                    "Both cited workflows remain visible until local policy resolves them."
                ),
                "evidence_ids": [evidence[0]["id"], evidence[1]["id"]],
            },
        ],
        "recommendation_rationale": (
            "The first option is presented for operator review, not selected by the model."
        ),
    }
    return {
        "schema_version": 1,
        "keep": [directive["id"] for directive in directives],
        "changes": [],
        "new_rule_suggestions": [],
        "decision_request": request,
        "unresolved_conflicts": [],
    }


def _unsafe_workflow_successor(packet: dict[str, Any]) -> dict[str, Any]:
    target = packet["targets"][0]
    directives = target["directives"]
    event = next(
        item
        for item in packet["evidence_events_oldest_to_newest"]
        if item["id"] == "evt_bad_workflow"
    )
    return {
        "schema_version": 1,
        "keep": [],
        "changes": [
            {
                "action": "replace",
                "source_ids": [directive["id"] for directive in directives],
                "compiled_directive": compiled_directive(BAD_WORKFLOW),
                "destination_target": target["target"],
                "heading_path": directives[0]["heading_path"],
                "evidence_ids": [event["id"]],
                "reason": "The selected option is expressed as one workflow directive.",
                "minimum_apply_mode": "attended",
                "relocation_basis": "",
                "enforcement_target": "",
                "deterministic_check": "",
            }
        ],
        "new_rule_suggestions": [],
        "decision_request": None,
        "unresolved_conflicts": [],
    }


def test_operator_decision_cannot_bypass_stage_local_workflow_safety(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_text = f"# Workflow\n\n- {BAD_WORKFLOW}\n\n- {GOOD_WORKFLOW}\n"
    config, (target,) = config_factory(
        (original_text,),
        target_names=("CLAUDE.md",),
    )
    events = (
        _event(
            "evt_bad_workflow",
            BAD_WORKFLOW,
            session_id="workflow-session-a",
        ),
        _event(
            "evt_good_workflow",
            GOOD_WORKFLOW,
            session_id="workflow-session-b",
        ),
    )
    inspected = inspection(config, events)
    initial_provider = StubProvider(_workflow_decision_plan)
    initial_provider.name = config.llm.provider
    initial_provider.model = config.llm.model
    parent = create_plan(config, provider=initial_provider, inspection=inspected)
    request = parent.raw_plan["decision_request"]
    _bind_cli_config(monkeypatch, config)
    _patch_cli_provider(
        monkeypatch,
        _unsafe_workflow_successor,
        model_id=config.llm.model,
    )
    before_run_ids = _run_ids(config)
    assert (
        _invoke_main(
            [
                "decide",
                parent.run_id,
                request["request_id"],
                "--choice",
                "a",
                "--config",
                str(config.config_path),
                "--json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert _run_ids(config) == before_run_ids
    assert target.read_text(encoding="utf-8") == original_text
