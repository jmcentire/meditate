from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import (
    StubProvider,
    compiled_directive,
    empty_compiled_directive,
    inspection,
    keep_all,
    replace_matching,
)

from meditate.models import Authority, EvidenceEvent
from meditate.plan import PLAN_SCHEMA, _packet, create_plan
from meditate.report import write_plan_report
from meditate.util import MeditateError, sha256_bytes


def correction(event_id: str = "evt_correction") -> EvidenceEvent:
    text = "New rule: commit completed changes by default after verification."
    return EvidenceEvent(
        id=event_id,
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id="session-correction",
        scope="global",
        text=text,
        source_locator="fixture:1",
        content_sha256=sha256_bytes(text.encode()),
    )


def canonical_high_impact_workflow(actions: str) -> str:
    return (
        "- Treat cited action lists as coverage, not execution order. Execute "
        f"{actions} in the exact order required by loaded repository instructions and the "
        "documented workflow. Before each action, run only applicable project-required checks "
        "that are available before that action at its stage. Treat downstream CI as a check at "
        "its own stage, not as a precondition for earlier actions. Before each remote or "
        "irreversible action, explicitly look up authority in loaded repository instructions. "
        "Stop for any required human approval or named handoff."
    )


def _dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _packet_reference_values(packet: dict[str, Any]) -> set[str]:
    values = set(packet["allowed_targets"])
    for target in packet["targets"]:
        values.add(target["target"])
        values.update(directive["id"] for directive in target["directives"])
    values.update(event["id"] for event in packet["evidence_events_oldest_to_newest"])
    return values


def test_provider_schema_uses_anthropic_supported_subset() -> None:
    assert "uniqueItems" not in json.dumps(PLAN_SCHEMA)


def _summary_mentions_count(summary: Any, *, label: str, expected: int) -> bool:
    rendered = json.dumps(summary, sort_keys=True).lower().replace("_", " ")
    label_pattern = label.replace(" ", r"\s+")
    return bool(
        re.search(
            rf"(?:{label_pattern}.{{0,40}}\b{expected}\b|"
            rf"\b{expected}\b.{{0,40}}{label_pattern})",
            rendered,
        )
    )


def test_packet_drops_overlap_candidates_whose_evidence_was_not_submitted(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory()
    included = correction("evt_included")
    base = inspection(config, (included,))
    inconsistent = replace(
        base,
        overlaps=(
            {
                "detector": "negation_pair",
                "directive_id": base.targets[0].directives[0].id,
                "evidence_id": "evt_not_submitted",
                "shared_subject_terms": ["verify"],
            },
        ),
    )
    packet, _bytes, _schema, _estimate, _dropped = _packet(inconsistent, config)
    assert packet["overlap_candidates"] == []


def test_provider_schema_is_stable_and_omits_high_cardinality_packet_enums(
    config_factory: ConfigFactory,
) -> None:
    def capture(prefix: str) -> tuple[dict[str, Any], dict[str, Any]]:
        contents = tuple(
            f"# {prefix} rules {target_index}\n\n"
            + "\n\n".join(
                f"- Preserve {prefix} behavior {target_index}-{directive_index}."
                for directive_index in range(8)
            )
            + "\n"
            for target_index in range(4)
        )
        names = tuple(f"AGENT-{prefix}-{index}.md" for index in range(len(contents)))
        config, _paths = config_factory(contents, target_names=names)
        events = tuple(
            replace(
                correction(f"evt_{prefix}_{index}"),
                text=f"Preserve {prefix} evidence behavior {index}.",
                session_id=f"session-{prefix}-{index}",
                source_locator=f"fixture:{prefix}:{index}",
                content_sha256=sha256_bytes(
                    f"Preserve {prefix} evidence behavior {index}.".encode()
                ),
            )
            for index in range(16)
        )
        provider = StubProvider(keep_all)
        provider.name = config.llm.provider
        provider.model = config.llm.model
        create_plan(config, provider=provider, inspection=inspection(config, events))
        assert provider.last_packet is not None
        assert provider.last_schema is not None
        return provider.last_packet, provider.last_schema

    first_packet, first_schema = capture("alpha")
    second_packet, second_schema = capture("omega")
    for packet in (first_packet, second_packet):
        assert len(packet["targets"]) == 4
        assert sum(len(target["directives"]) for target in packet["targets"]) == 32
        assert len(packet["evidence_events_oldest_to_newest"]) == 16

    first_values = _packet_reference_values(first_packet)
    second_values = _packet_reference_values(second_packet)
    assert first_values != second_values
    assert first_schema == second_schema

    for schema, packet_values in (
        (first_schema, first_values),
        (second_schema, second_values),
    ):
        enum_values = {
            value
            for node in _dicts(schema)
            for value in node.get("enum", [])
            if isinstance(value, str)
        }
        assert packet_values.isdisjoint(enum_values)
        assert {"replace", "remove", "relocate", "escalate", "attended"} <= enum_values


def test_model_summary_is_forbidden_and_report_summary_uses_validated_counts(
    config_factory: ConfigFactory,
) -> None:
    original = "# Git\n\n- Commit only when asked.\n\n- Preserve unrelated edits.\n"
    config, _targets = config_factory((original,), target_names=("CLAUDE.md",))

    def miscounted_model_summary(packet: dict[str, Any]) -> dict[str, Any]:
        result = keep_all(packet)
        result["summary"] = "Changed 999 directives and escalated 999 directives."
        return result

    invalid_provider = StubProvider(miscounted_model_summary)
    invalid_provider.name = config.llm.provider
    invalid_provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(config, provider=invalid_provider, inspection=inspection(config, ()))
    assert invalid_provider.calls == 1
    assert invalid_provider.last_schema is not None
    assert "summary" not in invalid_provider.last_schema["properties"]
    assert "summary" not in PLAN_SCHEMA["properties"]
    assert not (config.data_root / "runs").exists()

    evidence_text = "New rule: commit after tests."
    evidence = replace(
        correction("evt_summary_counts"),
        text=evidence_text,
        content_sha256=sha256_bytes(evidence_text.encode()),
    )
    provider = StubProvider(replace_matching({"Commit only when asked": "- Commit after tests."}))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    plan = create_plan(config, provider=provider, inspection=inspection(config, (evidence,)))
    assert plan.changed_directive_count == 1
    assert plan.escalated_directive_count == 0

    report_json_path, report_markdown_path = write_plan_report(config, plan)
    report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    summaries = [node["summary"] for node in _dicts(report_json) if "summary" in node]
    assert summaries
    assert any(
        _summary_mentions_count(summary, label="changed directives", expected=1)
        and _summary_mentions_count(summary, label="escalated directives", expected=0)
        for summary in summaries
    )
    report_markdown = report_markdown_path.read_text(encoding="utf-8")
    assert _summary_mentions_count(report_markdown, label="changed directives", expected=1)
    assert _summary_mentions_count(report_markdown, label="escalated directives", expected=0)
    assert "999" not in json.dumps(report_json)
    assert "999" not in report_markdown


def test_replacement_rejects_repeated_contiguous_eight_word_phrase_before_archive(
    config_factory: ConfigFactory,
) -> None:
    phrase = "run focused checks before changes and preserve unrelated edits"
    assert len(phrase.split()) >= 8
    config, _targets = config_factory(
        ("# Rules\n\n- Run focused checks.\n",),
        target_names=("CLAUDE.md",),
    )
    config = replace(
        config,
        safety=replace(config.safety, size_ceiling_ratio=10.0),
    )
    evidence_text = f"New rule: {phrase}."
    evidence = replace(
        correction("evt_repeated_phrase"),
        text=evidence_text,
        content_sha256=sha256_bytes(evidence_text.encode()),
    )
    provider = StubProvider(replace_matching({"Run focused checks": f"- {phrase}; {phrase}."}))
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(config, provider=provider, inspection=inspection(config, (evidence,)))
    assert provider.calls == 1
    assert not (config.data_root / "runs").exists()


@pytest.mark.parametrize(
    "catchall",
    [
        "other applicable actions",
        "additional applicable actions",
        "and similar",
        "etc",
        "and so on",
    ],
)
@pytest.mark.parametrize("grounding", [None, "source", "evidence"])
def test_action_catchalls_require_the_exact_phrase_in_source_or_cited_evidence(
    config_factory: ConfigFactory,
    catchall: str,
    grounding: str | None,
) -> None:
    source_suffix = f"; {catchall}" if grounding == "source" else ""
    original = f"# Rules\n\n- Run focused checks before reporting results{source_suffix}.\n"
    config, _targets = config_factory((original,), target_names=("CLAUDE.md",))
    replacement = f"- Run focused checks carefully before reporting results; {catchall}."
    evidence_text = "New rule: run focused checks carefully before reporting results."
    if grounding == "evidence":
        evidence_text = (
            f"New rule: run focused checks carefully before reporting results; {catchall}."
        )
    evidence = replace(
        correction(f"evt_catchall_{grounding or 'ungrounded'}"),
        text=evidence_text,
        content_sha256=sha256_bytes(evidence_text.encode()),
    )
    provider = StubProvider(
        replace_matching({"Run focused checks before reporting results": replacement})
    )
    provider.name = config.llm.provider
    provider.model = config.llm.model

    if grounding is None:
        with pytest.raises(MeditateError):
            create_plan(config, provider=provider, inspection=inspection(config, (evidence,)))
        assert not (config.data_root / "runs").exists()
    else:
        plan = create_plan(config, provider=provider, inspection=inspection(config, (evidence,)))
        assert plan.changed_directive_count == 1
        assert (config.data_root / "runs" / plan.run_id).is_dir()
    assert provider.calls == 1


@pytest.mark.parametrize(
    "invented_reference",
    [
        "invented_absolute_target",
        "normalized_target",
        "tilde_target",
        "directive",
        "evidence",
    ],
)
def test_local_validation_rejects_invented_plan_references(
    config_factory: ConfigFactory,
    invented_reference: str,
) -> None:
    config, (configured_target,) = config_factory(
        ("# Git\n\n- Commit only when asked.\n",),
        target_names=("CLAUDE.md",),
    )

    def builder(packet: dict[str, Any]) -> dict[str, Any]:
        target = packet["targets"][0]
        directive = target["directives"][0]
        event = packet["evidence_events_oldest_to_newest"][0]
        source_id = directive["id"]
        destination_target = target["target"]
        evidence_id = event["id"]
        keep: list[str] = []
        if invented_reference == "invented_absolute_target":
            destination_target = str(configured_target.parent / "INVENTED.md")
        elif invented_reference == "normalized_target":
            destination_target = str(
                configured_target.parent / "nested" / ".." / configured_target.name
            )
        elif invented_reference == "tilde_target":
            destination_target = f"~/{configured_target.name}"
        elif invented_reference == "directive":
            source_id = "dir_invented"
            keep = [directive["id"]]
        elif invented_reference == "evidence":
            evidence_id = "evt_invented"
        else:
            raise AssertionError(invented_reference)
        if invented_reference.endswith("target"):
            assert destination_target not in packet["allowed_targets"]
        return {
            "schema_version": 1,
            "keep": keep,
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [source_id],
                    "compiled_directive": compiled_directive(
                        "Commit completed changes after verification."
                    ),
                    "destination_target": destination_target,
                    "heading_path": directive["heading_path"],
                    "evidence": [{"id": evidence_id, "quote": event["text"]}],
                    "reason": "Synthetic reference-validation fixture.",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StubProvider(builder)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, (correction(),)),
        )
    assert provider.calls == 1
    assert not (config.data_root / "runs").exists()


@pytest.mark.parametrize("action", ["replace", "remove"])
def test_non_relocate_change_rejects_another_allowed_destination_target(
    config_factory: ConfigFactory,
    action: str,
) -> None:
    config, targets = config_factory(
        (
            "# Git\n\n- Commit only when asked.\n",
            "# Git\n\n- Preserve release notes.\n",
        ),
        target_names=("CLAUDE.md", "CLAUDE.local.md"),
    )
    originals = tuple(target.read_bytes() for target in targets)

    def builder(packet: dict[str, Any]) -> dict[str, Any]:
        source_target, other_target = packet["targets"]
        source = source_target["directives"][0]
        other = other_target["directives"][0]
        event = packet["evidence_events_oldest_to_newest"][0]
        return {
            "schema_version": 1,
            "keep": [other["id"]],
            "changes": [
                {
                    "action": action,
                    "source_ids": [source["id"]],
                    "compiled_directive": (
                        compiled_directive("Commit completed changes after verification.")
                        if action == "replace"
                        else empty_compiled_directive()
                    ),
                    "destination_target": other_target["target"],
                    "heading_path": source["heading_path"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "Synthetic non-relocate destination mismatch.",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StubProvider(builder)
    provider.name = config.llm.provider
    provider.model = config.llm.model
    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, (correction(),)),
        )
    assert provider.calls == 1
    assert tuple(target.read_bytes() for target in targets) == originals
    assert not (config.data_root / "runs").exists()


def test_plan_is_read_only_and_archives_exact_pre_and_post_images(
    config_factory: ConfigFactory,
) -> None:
    original = "# Git\n\n- Commit only when asked.\n\n- Preserve unrelated changes.\n"
    config, (target,) = config_factory((original,))
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- Commit completed changes after verification."}
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert target.read_text(encoding="utf-8") == original
    assert plan.minimum_apply_mode == "attended"
    assert plan.changed_directive_count == 1
    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["plan_sha256"] == plan.plan_sha256
    assert manifest["targets"][0]["changed"] is True
    pre = (run_dir / manifest["targets"][0]["pre_blob"]).read_text(encoding="utf-8")
    post = (run_dir / manifest["targets"][0]["post_blob"]).read_text(encoding="utf-8")
    assert pre == original
    assert "Commit completed changes" in post
    assert "Preserve unrelated changes" in post
    packet = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    assert packet["evidence_events_oldest_to_newest"][0]["id"] == "evt_correction"


def test_exact_reviewed_evidence_still_requires_attended_mode(
    config_factory: ConfigFactory,
) -> None:
    original = "# Git\n\n- Commit only when asked.\n"
    config, _paths = config_factory((original,))
    reviewed = replace(correction(), unattended_eligible=True)
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- Commit completed changes after project checks pass."}
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (reviewed,)))
    assert plan.minimum_apply_mode == "attended"
    assert plan.raw_plan["changes"][0]["minimum_apply_mode"] == "attended"


def test_noop_plan_converges_without_marking_target_changed(config_factory: ConfigFactory) -> None:
    config, _paths = config_factory()
    plan = create_plan(config, provider=StubProvider(keep_all), inspection=inspection(config, ()))
    manifest = json.loads(
        (config.data_root / "runs" / plan.run_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert plan.changed_directive_count == 0
    assert manifest["targets"][0]["changed"] is False


def test_plan_rejects_ungrounded_evidence_quote(config_factory: ConfigFactory) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))

    def builder(packet: dict[str, object]) -> dict[str, object]:
        target = packet["targets"][0]  # type: ignore[index]
        directive = target["directives"][0]  # type: ignore[index]
        event = packet["evidence_events_oldest_to_newest"][0]  # type: ignore[index]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [directive["id"]],
                    "compiled_directive": compiled_directive("Commit after tests."),
                    "destination_target": target["target"],
                    "heading_path": directive["heading_path"],
                    "evidence": [{"id": event["id"], "quote": "invented quote"}],
                    "reason": "fixture",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    with pytest.raises(MeditateError) as caught:
        create_plan(
            config, provider=StubProvider(builder), inspection=inspection(config, (correction(),))
        )
    assert caught.value.code == "ungrounded_quote"
    assert not (config.data_root / "runs").exists()


def test_plan_rejects_urgency_not_present_in_source_or_evidence(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- Commit, merge, push, and deploy immediately."}
        )
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert caught.value.code == "unsupported_intensifier"


def test_rfc_normative_keyword_is_not_an_unsupported_intensifier(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    base_builder = replace_matching(
        {"Commit only when asked": "Commit completed changes after `pytest` passes."}
    )

    def must_builder(packet: dict[str, Any]) -> dict[str, Any]:
        raw = base_builder(packet)
        raw["changes"][0]["compiled_directive"]["normative_keyword"] = "MUST"
        return raw

    plan = create_plan(
        config,
        provider=StubProvider(must_builder),
        inspection=inspection(config, (correction(),)),
    )
    assert plan.raw_plan["changes"][0]["compiled_directive"]["normative_keyword"] == "MUST"


def test_typed_scope_can_restate_grounded_universal_intensifier(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Kindex\n\n- Always search before adding.\n",))
    evidence_text = "New rule: search before adding."
    evidence = replace(
        correction("evt_universal_scope"),
        text=evidence_text,
        content_sha256=sha256_bytes(evidence_text.encode()),
    )
    base_builder = replace_matching({"Always search": "Search before adding."})

    def scoped_builder(packet: dict[str, Any]) -> dict[str, Any]:
        raw = base_builder(packet)
        compiled = raw["changes"][0]["compiled_directive"]
        compiled["normative_keyword"] = "MUST"
        compiled["scope"] = "Every Kindex capture operation"
        return raw

    plan = create_plan(
        config,
        provider=StubProvider(scoped_builder),
        inspection=inspection(config, (evidence,)),
    )
    assert plan.raw_plan["changes"][0]["compiled_directive"]["scope"] == (
        "Every Kindex capture operation"
    )


def test_plan_rejects_noncanonical_archive_root_before_provider_call(
    config_factory: ConfigFactory,
    tmp_path: Any,
) -> None:
    config, _paths = config_factory(("# Rules\n\n- Keep changes focused.\n",))
    real_root = tmp_path / "canonical-data"
    real_root.mkdir()
    alias_root = tmp_path / "aliased-data"
    alias_root.symlink_to(real_root, target_is_directory=True)
    config = replace(config, data_root=alias_root)
    provider = StubProvider(keep_all)

    with pytest.raises(MeditateError) as caught:
        create_plan(
            config,
            provider=provider,
            inspection=inspection(config, (correction(),)),
        )

    assert caught.value.code == "unsafe_run_path"
    assert provider.calls == 0


def test_plan_rejects_bare_self_attested_verification(config_factory: ConfigFactory) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    provider = StubProvider(
        replace_matching({"Commit only when asked": "- After verifying changes, commit them."})
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert caught.value.code == "undefined_verification_gate"


def test_plan_accepts_project_required_checks_as_verification_criterion(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- After project-required checks pass, commit changes."}
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert "project-required checks" in next(iter(plan.proposed_contents.values()))


def test_plan_rejects_new_operational_action_absent_from_exact_citations(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    provider = StubProvider(
        replace_matching({"Commit only when asked": "- Commit and deploy completed changes."})
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert caught.value.code == "ungrounded_operational_action"


def test_validator_attaches_literal_submitted_sequence_support(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=24.0))
    sequence_text = "Once done, commit, merge, push, deploy, rev, and release."
    sequence = replace(
        correction("evt_sequence"),
        text=sequence_text,
        content_sha256=sha256_bytes(sequence_text.encode()),
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": canonical_high_impact_workflow(
                    "commit, merge, push, deploy, rev, and release"
                )
            }
        )
    )
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (correction(), sequence)),
    )
    citations = plan.raw_plan["changes"][0]["evidence"]
    assert any(citation["id"] == "evt_sequence" for citation in citations)
    assert any("rev" in citation["quote"] for citation in citations)


def test_kept_baseline_can_support_an_operational_action_and_is_recorded(
    config_factory: ConfigFactory,
) -> None:
    content = "# Git\n\n- Commit only when asked.\n\n# Release\n\n- Release through verified CI.\n"
    config, _paths = config_factory((content,))
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=24.0))
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": canonical_high_impact_workflow(
                    "commit completed work and release it"
                )
            }
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    change = plan.raw_plan["changes"][0]
    assert change["baseline_support"][0]["action"] == "release"
    assert len(change["baseline_support"][0]["directive_ids"]) == 1


def test_explicit_new_rule_cannot_retain_only_when_asked_clause(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    evidence = correction()
    evidence = replace(
        evidence,
        text="New Rule: commit completed changes by default. Why leave staged changes around?",
    )
    provider = StubProvider(
        replace_matching({"Commit only when asked": "- Commit completed changes only when asked."})
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (evidence,)))
    assert caught.value.code == "retained_reversed_clause"


def test_explicit_reversal_actions_cannot_be_replaced_by_etc(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    new_rule_text = "New Rule: commit, merge, push, deploy."
    new_rule = replace(
        correction(),
        text=new_rule_text,
        content_sha256=sha256_bytes(new_rule_text.encode()),
    )
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- Commit, push, deploy, etc. after required checks."}
        )
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (new_rule,)))
    assert caught.value.code == "dropped_explicit_action"


def test_new_high_impact_actions_need_concrete_authority_and_stop_gate(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    new_rule_text = "New Rule: commit, merge, push, deploy."
    new_rule = replace(
        correction(),
        text=new_rule_text,
        content_sha256=sha256_bytes(new_rule_text.encode()),
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": (
                    "- After required tests and CI checks pass, commit, merge, push, and deploy "
                    "following project procedures and handoff boundaries."
                )
            }
        )
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (new_rule,)))
    assert caught.value.code == "undefined_high_impact_gate"


def test_new_high_impact_actions_accept_explicit_per_stage_gate(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=24.0))
    new_rule_text = "New Rule: commit, merge, push, deploy."
    new_rule = replace(
        correction(),
        text=new_rule_text,
        content_sha256=sha256_bytes(new_rule_text.encode()),
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": canonical_high_impact_workflow(
                    "commit, merge, push, and deploy"
                )
            }
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (new_rule,)))
    assert "explicitly look up authority" in next(iter(plan.proposed_contents.values()))


def test_new_high_impact_actions_accept_concrete_lookup_wording(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=24.0))
    new_rule_text = "New Rule: commit, merge, push, deploy."
    new_rule = replace(
        correction(),
        text=new_rule_text,
        content_sha256=sha256_bytes(new_rule_text.encode()),
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": canonical_high_impact_workflow(
                    "commit, merge, push, and deploy"
                )
            }
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (new_rule,)))
    assert "explicitly look up authority" in next(iter(plan.proposed_contents.values()))


def test_replace_cannot_consolidate_across_headings(config_factory: ConfigFactory) -> None:
    content = "# Identity\n\n- Push to account A.\n\n# Preferences\n\n- Commit only when asked.\n"
    config, _paths = config_factory((content,))

    def builder(packet: dict[str, object]) -> dict[str, object]:
        target = packet["targets"][0]  # type: ignore[index]
        directives = target["directives"]  # type: ignore[index]
        event = packet["evidence_events_oldest_to_newest"][0]  # type: ignore[index]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [item["id"] for item in directives],
                    "compiled_directive": compiled_directive(
                        "Push completed commits to account A."
                    ),
                    "destination_target": target["target"],
                    "heading_path": directives[0]["heading_path"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "bad cross-heading consolidation",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    with pytest.raises(MeditateError) as caught:
        create_plan(
            config, provider=StubProvider(builder), inspection=inspection(config, (correction(),))
        )
    assert caught.value.code == "cross_heading_replace"


def test_plan_rejects_protected_directive_change(config_factory: ConfigFactory) -> None:
    content = (
        "# Rules\n\n<!-- meditate:protect:start -->\n"
        "- Commit only when asked.\n<!-- meditate:protect:end -->\n"
    )
    config, _paths = config_factory((content,))
    provider = StubProvider(
        replace_matching({"Commit only when asked": "- Commit everything automatically."})
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert caught.value.code == "protected_change"


def test_plan_budget_blocks_before_provider_call(config_factory: ConfigFactory) -> None:
    config, _paths = config_factory(("# Rules\n\n- " + ("large " * 100) + "\n",))
    config = replace(
        config,
        llm=replace(config.llm, max_input_tokens=100, max_total_input_tokens=100),
    )
    provider = StubProvider(keep_all)
    with pytest.raises(MeditateError) as caught:
        create_plan(config, provider=provider, inspection=inspection(config, ()))
    assert caught.value.code == "input_budget_exceeded"
    assert provider.calls == 0


def test_relocate_within_same_file_moves_instead_of_replacing_in_place(
    config_factory: ConfigFactory,
) -> None:
    content = (
        "# Global\n\n- Project-only release process.\n\n# Project\n\n- Keep local rules here.\n"
    )
    config, _paths = config_factory((content,))

    def builder(packet: dict[str, object]) -> dict[str, object]:
        target = packet["targets"][0]  # type: ignore[index]
        directives = target["directives"]  # type: ignore[index]
        source = directives[0]
        keep = [item["id"] for item in directives[1:]]
        event = packet["evidence_events_oldest_to_newest"][0]  # type: ignore[index]
        return {
            "schema_version": 1,
            "keep": keep,
            "changes": [
                {
                    "action": "relocate",
                    "source_ids": [source["id"]],
                    "compiled_directive": empty_compiled_directive(),
                    "destination_target": target["target"],
                    "heading_path": ["Project"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "Scope-specific evidence places this under Project.",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "organization",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    scoped_text = "Move this project-only release process under the Project heading."
    scoped_evidence = replace(
        correction(),
        text=scoped_text,
        content_sha256=sha256_bytes(scoped_text.encode()),
    )
    plan = create_plan(
        config,
        provider=StubProvider(builder),
        inspection=inspection(config, (scoped_evidence,)),
    )
    proposed = next(iter(plan.proposed_contents.values()))
    assert proposed.index("# Project") < proposed.index("Project-only release process")
