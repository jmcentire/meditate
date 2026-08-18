from __future__ import annotations

import json
from dataclasses import replace

import pytest
from conftest import ConfigFactory
from helpers import StubProvider, inspection, keep_all, replace_matching

from meditate.models import Authority, EvidenceEvent
from meditate.plan import PLAN_SCHEMA, _packet, create_plan
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


def test_provider_schema_uses_anthropic_supported_subset() -> None:
    assert "uniqueItems" not in json.dumps(PLAN_SCHEMA)


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


def test_provider_schema_enumerates_packet_ids_and_exact_targets(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory()
    provider = StubProvider(keep_all)
    create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    assert provider.last_packet is not None
    assert provider.last_schema is not None
    schema = provider.last_schema["properties"]
    event_id = provider.last_packet["evidence_events_oldest_to_newest"][0]["id"]
    target = provider.last_packet["allowed_targets"][0]
    change = schema["changes"]["items"]["properties"]
    assert change["destination_target"]["enum"] == [target]
    assert change["evidence"]["items"]["properties"]["id"]["enum"] == [event_id]
    assert "enum" not in schema["keep"]["items"]
    assert "enum" not in change["source_ids"]["items"]


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


def test_exact_reviewed_evidence_can_compute_unattended_mode(
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
    assert plan.minimum_apply_mode == "unattended"
    assert plan.raw_plan["changes"][0]["minimum_apply_mode"] == "unattended"


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
                    "replacement": "- Commit after tests.",
                    "destination_target": target["target"],
                    "heading_path": directive["heading_path"],
                    "evidence": [{"id": event["id"], "quote": "invented quote"}],
                    "reason": "fixture",
                    "minimum_apply_mode": "attended",
                }
            ],
            "unresolved_conflicts": [],
            "summary": "bad",
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
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=6.0))
    sequence_text = "Once done, commit, merge, push, deploy, rev, and release."
    sequence = replace(
        correction("evt_sequence"),
        text=sequence_text,
        content_sha256=sha256_bytes(sequence_text.encode()),
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": (
                    "- Commit and push. Proceed through merge, deploy, rev, and release only "
                    "where documented project procedures explicitly authorize autonomous action "
                    "at each stage."
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
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=3.0))
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": (
                    "- After project-required checks pass, commit completed work and release "
                    "only where documented project procedures explicitly authorize autonomous "
                    "action at each stage."
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
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=6.0))
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
                    "- After required tests and CI checks pass, commit and push. Proceed through "
                    "merge and deploy only where documented project procedures explicitly "
                    "authorize autonomous action at each stage."
                )
            }
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (new_rule,)))
    assert "explicitly authorize" in next(iter(plan.proposed_contents.values()))


def test_new_high_impact_actions_accept_concrete_lookup_wording(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    config = replace(config, safety=replace(config.safety, size_ceiling_ratio=7.0))
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
                    "- After required checks pass, commit, merge, push, and deploy. Before remote "
                    "actions, check repository rules for authorization; stop for any required "
                    "human approval or named handoff."
                )
            }
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (new_rule,)))
    assert "check repository rules" in next(iter(plan.proposed_contents.values()))


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
                    "replacement": "- Push completed commits to account A.",
                    "destination_target": target["target"],
                    "heading_path": directives[0]["heading_path"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "bad cross-heading consolidation",
                    "minimum_apply_mode": "attended",
                }
            ],
            "unresolved_conflicts": [],
            "summary": "bad",
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
                    "replacement": source["text"],
                    "destination_target": target["target"],
                    "heading_path": ["Project"],
                    "evidence": [{"id": event["id"], "quote": event["text"]}],
                    "reason": "Scope-specific evidence places this under Project.",
                    "minimum_apply_mode": "attended",
                }
            ],
            "unresolved_conflicts": [],
            "summary": "Relocated a scoped directive.",
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
