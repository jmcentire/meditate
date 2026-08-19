from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import StageProvider, compiled_directive, inspection, keep_all

from meditate.analyst import (
    ANALYST_PROMPT,
    ANALYST_PROMPT_VERSION,
    merge_candidate_clusters,
    validate_analysis,
)
from meditate.candidates import derive_candidate_clusters
from meditate.cli import _validated_plan_payload
from meditate.models import Authority, EvidenceEvent
from meditate.plan import create_plan
from meditate.transaction import apply_run, restore_run
from meditate.util import MeditateError, sha256_text


def _event(
    identifier: str,
    text: str,
    *,
    session_id: str | None = "session-a",
    timestamp: str = "2026-08-19T12:00:00Z",
    source_kind: str = "claude_history_user",
    authority: Authority = Authority.REPEATED_USER_PREFERENCE,
) -> EvidenceEvent:
    return EvidenceEvent(
        id=identifier,
        source_kind=source_kind,
        authority=authority,
        timestamp=timestamp,
        session_id=session_id,
        scope="global",
        text=text,
        source_locator=f"synthetic:{identifier}",
        content_sha256=sha256_text(text),
    )


def _nomination(
    *,
    candidate_class: str,
    domain: str,
    source_ids: list[str],
    evidence: list[dict[str, str]],
    intent: str,
) -> dict[str, Any]:
    return {
        "candidate_class": candidate_class,
        "domain": domain,
        "source_ids": source_ids,
        "evidence_ids": [item["id"] for item in evidence],
        "behavioral_intent": intent,
        "reason": "The cited interaction exposes a concrete behavioral mismatch.",
        "applies_when": "The named workflow and scope are active.",
        "does_not_apply_when": "A different workflow or explicit narrower boundary applies.",
    }


def test_temporal_conversation_evidence_opens_a_bounded_existing_rule_candidate(
    config_factory: ConfigFactory,
) -> None:
    config, paths = config_factory(
        ("# Git\n\n- Only commit completed changes when the user asks.\n",)
    )
    event = _event(
        "evt_temporal",
        "New rule: no longer wait for me to ask before commit; after tests pass, commit "
        "completed changes by default.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        assert _packet["allowed_source_ids"] == [directive.id]
        assert event.id in _packet["allowed_evidence_ids"]
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="temporal_supersession",
                    domain="git",
                    source_ids=[directive.id],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent=(
                        "Commit completed changes after tests pass without waiting for a request."
                    ),
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        candidate = packet["consolidation_candidates"][0]
        mutable = packet["targets"][0]["directives"][0]
        assert candidate["source_ids"] == [directive.id]
        assert "semantic_temporal_supersession" in candidate["reason_codes"]
        assert packet["semantic_analysis"]["authority"] == "nomination_only"
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [mutable["id"]],
                    "compiled_directive": compiled_directive(
                        "Commit completed changes after project-required tests pass by default.",
                        keyword="SHOULD",
                        reason="The explicit newer correction removes per-session opt-in.",
                        scope="Completed local changes without a narrower repository handoff.",
                    ),
                    "destination_target": mutable["target"],
                    "heading_path": mutable["heading_path"],
                    "evidence_ids": [],
                    "reason": "The newer explicit correction supersedes the opt-in-only baseline.",
                    "minimum_apply_mode": "attended",
                    "enforcement_target": "",
                    "deterministic_check": "",
                    "relocation_basis": "",
                }
            ],
            "new_rule_suggestions": [],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    plan = create_plan(
        config,
        inspection=state,
        analyst_provider=provider,
        provider=provider,
    )

    assert provider.analysis_calls == 1
    assert provider.plan_calls == 1
    assert plan.usage.calls == 2
    assert plan.changed_directive_count == 1
    assert plan.semantic_analysis["prompt_version"] == ANALYST_PROMPT_VERSION
    assert plan.semantic_analysis["nominations"][0]["authority"] == "nomination_only"
    assert plan.raw_plan["changes"][0]["defect_classes"] == ["semantic_temporal_supersession"]
    assert plan.raw_plan["changes"][0]["evidence"] == [{"id": event.id, "quote": event.text}]
    assert paths[0].read_text(encoding="utf-8").startswith("# Git")
    run_dir = config.data_root / "runs" / plan.run_id
    assert (run_dir / "analysis.json").is_file()
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))[
        "semantic_analysis_sha256"
    ]


def test_already_satisfied_semantic_nomination_is_a_reviewed_noop(
    config_factory: ConfigFactory,
) -> None:
    original = (
        "# Package management\n\n"
        "- MUST use `pnpm` for package installs because `pnpm-lock.yaml` defines "
        "the dependency graph. Do not use `npm`.\n"
    )
    config, paths = config_factory((original,))
    event = _event(
        "evt_already_applied",
        "New durable rule: replace npm with pnpm for package installs because "
        "pnpm-lock.yaml defines the dependency graph. Do not use npm.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]
    provider = StageProvider(
        lambda _packet: {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="temporal_supersession",
                    domain="tooling",
                    source_ids=[directive.id],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent=(
                        "Use pnpm for package installs because pnpm-lock.yaml defines the "
                        "dependency graph; do not use npm."
                    ),
                )
            ],
        },
        keep_all,
    )

    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert plan.changed_directive_count == 0
    assert plan.consolidation_preflight["status"] == "review_candidates_preserved"
    assert plan.consolidation_preflight["outcome"] == "reviewed_noop"
    assert plan.consolidation_preflight["defects_unresolved"] == []
    assert plan.consolidation_preflight["review_candidates_preserved"] == [
        "semantic_temporal_supersession"
    ]
    assert plan.consolidation_preflight["review_candidates_unresolved"] == []
    assert paths[0].read_text(encoding="utf-8") == original
    assert plan.proposed_contents[str(paths[0])] == original
    payload = _validated_plan_payload(config, plan)
    assert payload["action_required"] is True
    assert payload["apply_command"] is None


def test_missing_rule_is_introduced_reversibly_and_restores_exact_preimage(
    config_factory: ConfigFactory,
) -> None:
    original = "# Style\n\n- Prefer concise explanations.\n"
    config, paths = config_factory((original,))
    event = _event(
        "evt_missing",
        "From now on, every release must run `make verify` first and report the result.",
    )
    state = inspection(config, (event,))

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="missing_rule",
                    domain="release",
                    source_ids=[],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Run make verify and report its result before every release.",
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        nomination = packet["semantic_analysis"]["nominations"][0]
        assert packet["targets"][0]["directives"] == []
        assert packet["allowed_missing_rule_nomination_ids"] == [nomination["id"]]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [],
            "new_rule_suggestions": [
                {
                    "nomination_id": nomination["id"],
                    "compiled_directive": compiled_directive(
                        "Run `make verify` and report its result before every release.",
                        keyword="MUST",
                        reason=(
                            "The explicit durable correction makes release verification observable."
                        ),
                        scope="Every release from a repository where `make verify` is available.",
                        boundary_example=(
                            "A local draft with no release action does not trigger it."
                        ),
                    ),
                    "destination_target": packet["allowed_targets"][0],
                    "heading_path": ["Release"],
                    "reason": (
                        "The current directive set does not represent the durable release rule."
                    ),
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    plan = create_plan(
        config,
        inspection=state,
        analyst_provider=provider,
        provider=provider,
    )

    assert plan.changed_directive_count == 1
    assert plan.new_rule_suggestion_count == 1
    assert plan.consolidation_preflight["outcome"] == "reversible_change_ready"
    assert plan.semantic_verification["status"] == "optional"
    assert "Run `make verify`" in plan.proposed_contents[str(paths[0])]
    assert paths[0].read_text(encoding="utf-8") == original
    suggestion = plan.raw_plan["new_rule_suggestions"][0]
    assert suggestion["candidate_only"] is False
    assert suggestion["write_authority"] == "reversible"
    assert suggestion["promotion_required"] is False
    assert suggestion["minimum_apply_mode"] == "unattended"
    receipt = apply_run(config, plan.run_id, mode="reversible")
    assert receipt["restore_command"] == f"meditate restore {plan.run_id}"
    assert "Run `make verify`" in paths[0].read_text(encoding="utf-8")
    restore_run(config, plan.run_id)
    assert paths[0].read_text(encoding="utf-8") == original


def test_consequential_missing_rule_requires_exact_confirmation(
    config_factory: ConfigFactory,
) -> None:
    original = "# Style\n\n- Prefer concise explanations.\n"
    config, (target,) = config_factory((original,))
    event = _event(
        "evt_secret_policy",
        "From now on, never print API keys or credential values in reports.",
    )
    state = inspection(config, (event,))

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="missing_rule",
                    domain="security",
                    source_ids=[],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Never print API keys or credential values in reports.",
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        nomination = packet["semantic_analysis"]["nominations"][0]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [],
            "new_rule_suggestions": [
                {
                    "nomination_id": nomination["id"],
                    "compiled_directive": compiled_directive(
                        "Print no API key or credential value in a report.",
                        keyword="MUST NOT",
                        reason="Secret disclosure persists beyond instruction rollback.",
                        scope="Every report and command transcript.",
                    ),
                    "destination_target": packet["allowed_targets"][0],
                    "heading_path": ["Security"],
                    "reason": "The explicit durable security rule is absent.",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert plan.minimum_apply_mode == "attended"
    suggestion = plan.raw_plan["new_rule_suggestions"][0]
    assert suggestion["requires_confirmation"] is True
    with pytest.raises(MeditateError) as caught:
        apply_run(config, plan.run_id, mode="reversible")
    assert caught.value.code == "confirmation_required"
    assert target.read_text(encoding="utf-8") == original
    apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert "API key" in target.read_text(encoding="utf-8")


def test_semantic_change_rejects_evidence_outside_its_admitted_candidate(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(
        ("# Git\n\n- Only commit completed changes when the user asks.\n",)
    )
    supporting = _event(
        "evt_bound_support",
        "New rule: no longer wait for me to ask; commit completed changes after tests pass.",
    )
    unrelated = _event(
        "evt_unrelated_support",
        "For documentation work, preserve the established narrative voice and examples.",
    )
    state = inspection(config, (supporting, unrelated))
    directive = state.targets[0].directives[0]

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="temporal_supersession",
                    domain="git",
                    source_ids=[directive.id],
                    evidence=[{"id": supporting.id, "quote": supporting.text}],
                    intent="Commit completed changes after tests pass without waiting.",
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        mutable = packet["targets"][0]["directives"][0]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [mutable["id"]],
                    "compiled_directive": compiled_directive(
                        "Commit completed changes after project-required tests pass.",
                        scope="Completed local changes.",
                    ),
                    "destination_target": mutable["target"],
                    "heading_path": mutable["heading_path"],
                    "evidence_ids": [unrelated.id],
                    "reason": "Attempted evidence substitution.",
                    "minimum_apply_mode": "attended",
                    "enforcement_target": "",
                    "deterministic_check": "",
                    "relocation_basis": "",
                }
            ],
            "new_rule_suggestions": [],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    with pytest.raises(MeditateError) as raised:
        create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert raised.value.code == "semantic_evidence_mismatch"


def test_missing_rule_draft_materializes_exact_evidence_locally(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Style\n\n- Prefer concise explanations.\n",))
    event = _event(
        "evt_minimal_draft_quote",
        "From now on, every release must run `make verify` first and report the result.",
    )
    state = inspection(config, (event,))

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="missing_rule",
                    domain="release",
                    source_ids=[],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Run make verify and report its result before every release.",
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        nomination = packet["semantic_analysis"]["nominations"][0]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [],
            "new_rule_suggestions": [
                {
                    "nomination_id": nomination["id"],
                    "compiled_directive": compiled_directive(
                        "Run `make verify` before every release.",
                        keyword="MUST",
                        scope="Every release where the command is available.",
                    ),
                    "destination_target": packet["allowed_targets"][0],
                    "heading_path": ["Release"],
                    "reason": "The durable release requirement is absent.",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert provider.analysis_calls == 1
    assert provider.plan_calls == 1
    assert plan.raw_plan["new_rule_suggestions"][0]["evidence"] == [
        {"id": event.id, "quote": event.text}
    ]


def test_structural_defect_remains_primary_when_a_missing_rule_is_also_reported(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(
        ("# Workflow\n\n- Keep changes narrowly scoped.\n- Keep changes narrowly scoped.\n",)
    )
    event = _event(
        "evt_mixed_outcome",
        "From now on, every release must run `make verify` first and report the result.",
    )
    state = inspection(config, (event,))

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="missing_rule",
                    domain="release",
                    source_ids=[],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Run make verify and report its result before every release.",
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        nomination = packet["semantic_analysis"]["nominations"][0]
        directive_ids = [
            directive["id"] for target in packet["targets"] for directive in target["directives"]
        ]
        return {
            "schema_version": 1,
            "keep": directive_ids,
            "changes": [],
            "new_rule_suggestions": [
                {
                    "nomination_id": nomination["id"],
                    "compiled_directive": compiled_directive(
                        "Run `make verify` and report its result before every release.",
                        keyword="MUST",
                        scope="Every release where `make verify` is available.",
                    ),
                    "destination_target": packet["allowed_targets"][0],
                    "heading_path": ["Release"],
                    "reason": "The durable release requirement is absent.",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert plan.new_rule_suggestion_count == 1
    assert plan.consolidation_preflight["outcome"] == "reversible_change_ready"
    assert plan.consolidation_preflight["defects_unresolved"] == ["exact_duplicate"]
    assert plan.consolidation_preflight["new_rule_hypotheses"] == 1


def test_cross_heading_contradiction_is_reported_but_not_admitted_to_mutation(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(
        (
            "# Delivery\n\n- Deploy completed work automatically.\n\n"
            "# Handoffs\n\n- Never deploy automatically; deployment belongs to the "
            "release owner.\n",
        )
    )
    event = _event(
        "evt_collision",
        "These deploy rules conflict: never deploy automatically when the release owner owns it.",
    )
    state = inspection(config, (event,))
    sources = [item.id for item in state.targets[0].directives]

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="contradiction",
                    domain="release",
                    source_ids=sources,
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent=(
                        "Resolve whether completed work deploys automatically or by owner handoff."
                    ),
                )
            ],
        }

    provider = StageProvider(analyst, keep_all)
    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    nomination = plan.semantic_analysis["nominations"][0]
    assert nomination["admission"] == "reported_only"
    assert nomination["admission_reason"] == "cross_target_or_heading_requires_operator_resolution"
    assert provider.plan_calls == 0
    assert plan.changed_directive_count == 0
    assert plan.consolidation_preflight["outcome"] == "semantic_review_required"


@pytest.mark.parametrize(
    ("candidate_class", "intent"),
    [
        ("underspecified", "Run project tests before publishing a release artifact."),
        ("overspecified", "Run project tests before publishing a release artifact."),
        ("wrong_scope", "Run project tests before publishing a release artifact."),
    ],
)
def test_semantic_existing_rule_classes_become_review_candidates_not_facts(
    config_factory: ConfigFactory,
    candidate_class: str,
    intent: str,
) -> None:
    config, _paths = config_factory(
        ("# Release\n\n- Run project tests before publishing a release artifact.\n",)
    )
    event = _event(
        f"evt_{candidate_class}",
        "For release work, run project tests before publishing the release artifact.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]
    raw = {
        "schema_version": 1,
        "nominations": [
            _nomination(
                candidate_class=candidate_class,
                domain="release",
                source_ids=[directive.id],
                evidence=[{"id": event.id, "quote": event.text}],
                intent=intent,
            )
        ],
    }

    nominations = validate_analysis(raw, state, submitted_event_ids={event.id})
    clusters = merge_candidate_clusters(state, derive_candidate_clusters(state), nominations)

    assert nominations[0]["authority"] == "nomination_only"
    assert nominations[0]["admission"] == "mutable_candidate"
    assert clusters[0].reason_codes == (f"semantic_{candidate_class}",)


def test_analyst_modality_contract_requires_meaning_not_keyword_churn() -> None:
    assert "meaningful normative force" in ANALYST_PROMPT
    assert "mere absence of an RFC keyword" in ANALYST_PROMPT
    assert "solely to add an ornamental keyword" in ANALYST_PROMPT
    assert "`ALWAYS` and `NEVER`" in ANALYST_PROMPT
    assert "ambiguous `MAY NOT`" in ANALYST_PROMPT


def test_single_source_nomination_without_external_evidence_is_report_only(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Release\n\n- Run appropriate checks before publishing.\n",))
    state = inspection(config, ())
    directive = state.targets[0].directives[0]
    raw = {
        "schema_version": 1,
        "nominations": [
            _nomination(
                candidate_class="underspecified",
                domain="release",
                source_ids=[directive.id],
                evidence=[],
                intent="Run appropriate checks before publishing the release.",
            )
        ],
    }

    nominations = validate_analysis(raw, state, submitted_event_ids=set())
    clusters = merge_candidate_clusters(state, derive_candidate_clusters(state), nominations)

    assert nominations[0]["admission"] == "reported_only"
    assert nominations[0]["admission_reason"] == "single_source_without_external_evidence"
    assert clusters == ()


def test_enforcement_nomination_requires_two_independent_interaction_groups(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Run `make lint` before every commit.\n",))
    first = _event(
        "evt_enforce_a",
        "You skipped `make lint` before commit; run it before every commit.",
        session_id="session-a",
    )
    second = _event(
        "evt_enforce_b",
        "Again, run `make lint` before every commit because the prose rule was missed.",
        session_id="session-b",
        timestamp="2026-08-19T13:00:00Z",
    )
    state = inspection(config, (first, second))
    directive = state.targets[0].directives[0]

    def raw(evidence: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="enforcement_candidate",
                    domain="git",
                    source_ids=[directive.id],
                    evidence=evidence,
                    intent="Run make lint before every commit.",
                )
            ],
        }

    with pytest.raises(MeditateError) as raised:
        validate_analysis(
            raw([{"id": first.id, "quote": first.text}]),
            state,
            submitted_event_ids={first.id, second.id},
        )
    assert raised.value.code == "insufficient_escalation_lineage"

    accepted = validate_analysis(
        raw(
            [
                {"id": first.id, "quote": first.text},
                {"id": second.id, "quote": second.text},
            ]
        ),
        state,
        submitted_event_ids={first.id, second.id},
    )
    assert accepted[0]["admission"] == "mutable_candidate"


def test_analyst_rejects_minimal_evidence_record_and_two_term_intent_grounding(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(
        ("# Release\n\n- Run project tests before publishing a release artifact.\n",)
    )
    event = _event(
        "evt_grounding",
        "For every release, run project tests before publishing the release artifact.",
    )
    minimal_event = _event("evt_minimal", "tests")
    state = inspection(config, (minimal_event, event))
    directive = state.targets[0].directives[0]

    minimal_evidence = {
        "schema_version": 1,
        "nominations": [
            _nomination(
                candidate_class="underspecified",
                domain="release",
                source_ids=[directive.id],
                evidence=[{"id": minimal_event.id, "quote": minimal_event.text}],
                intent="Run project tests before publishing a release artifact.",
            )
        ],
    }
    with pytest.raises(MeditateError) as raised:
        validate_analysis(
            minimal_evidence,
            state,
            submitted_event_ids={minimal_event.id, event.id},
        )
    assert raised.value.code == "insufficient_evidence_text"

    weak_intent = {
        "schema_version": 1,
        "nominations": [
            _nomination(
                candidate_class="underspecified",
                domain="release",
                source_ids=[directive.id],
                evidence=[{"id": event.id, "quote": event.text}],
                intent="Project tests",
            )
        ],
    }
    with pytest.raises(MeditateError) as raised:
        validate_analysis(weak_intent, state, submitted_event_ids={event.id})
    assert raised.value.code == "ungrounded_semantic_intent"


def test_analyst_rejects_duplicate_nomination_fingerprints(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Rules\n\n- Keep changes narrowly scoped.\n",))
    event = _event(
        "evt_duplicate",
        "From now on, keep every code change narrowly scoped to the requested behavior.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]
    nomination = _nomination(
        candidate_class="underspecified",
        domain="workflow",
        source_ids=[directive.id],
        evidence=[{"id": event.id, "quote": event.text}],
        intent="Keep every code change narrowly scoped to requested behavior.",
    )

    with pytest.raises(MeditateError) as raised:
        validate_analysis(
            {"schema_version": 1, "nominations": [nomination, dict(nomination)]},
            state,
            submitted_event_ids={event.id},
        )
    assert raised.value.code == "duplicate_semantic_nomination"


def test_stable_semantic_analysis_is_cached_and_repeated_runs_do_not_drift(
    config_factory: ConfigFactory,
) -> None:
    original = "# Rules\n\n- Keep changes focused because narrow patches are reviewable.\n"
    config, paths = config_factory((original,))
    state = inspection(config, ())

    providers: list[StageProvider] = []
    for _index in range(10):
        provider = StageProvider(
            lambda _packet: {"schema_version": 1, "nominations": []},
            keep_all,
        )
        providers.append(provider)
        plan = create_plan(
            config,
            inspection=state,
            analyst_provider=provider,
            provider=provider,
        )
        assert plan.changed_directive_count == 0
        assert plan.consolidation_preflight["outcome"] == "stable_noop"
        assert plan.proposed_contents[str(paths[0])] == original
        assert paths[0].read_text(encoding="utf-8") == original

    assert providers[0].analysis_calls == 1
    assert all(provider.analysis_calls == 0 for provider in providers[1:])
    assert all(provider.plan_calls == 0 for provider in providers)


def test_semantic_cache_refuses_a_symlink_even_when_its_payload_was_valid(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Rules\n\n- Keep changes focused.\n",))
    state = inspection(config, ())
    first = StageProvider(
        lambda _packet: {"schema_version": 1, "nominations": []},
        keep_all,
    )
    create_plan(config, inspection=state, analyst_provider=first, provider=first)
    cache_path = next((config.cache_root / "semantic-analysis").glob("*.json"))
    preserved = cache_path.with_name("preserved-cache.json")
    cache_path.replace(preserved)
    cache_path.symlink_to(preserved)

    second = StageProvider(
        lambda _packet: {"schema_version": 1, "nominations": []},
        keep_all,
    )
    with pytest.raises(MeditateError) as raised:
        create_plan(config, inspection=state, analyst_provider=second, provider=second)

    assert raised.value.code == "unsafe_analysis_cache"
    assert second.analysis_calls == 0
    assert second.plan_calls == 0


def test_analyst_cannot_smuggle_a_draft_or_unknown_identifier(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Rules\n\n- Keep changes focused.\n",))
    event = _event("evt_known", "From now on, always keep changes focused.")
    state = inspection(config, (event,))
    raw = {
        "schema_version": 1,
        "nominations": [
            {
                **_nomination(
                    candidate_class="underspecified",
                    domain="workflow",
                    source_ids=["dir_invented"],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Keep changes focused in the current workflow.",
                ),
                "proposed_directive": "MUST write whatever the Analyst says",
            }
        ],
    }

    with pytest.raises(MeditateError) as raised:
        validate_analysis(raw, state, submitted_event_ids={event.id})
    assert raised.value.code == "analyst_schema"


def test_invalid_nomination_is_rejected_without_discarding_a_valid_sibling(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Style\n\n- Prefer concise explanations.\n",))
    event = _event(
        "evt_partial",
        "From now on, every release must run `make verify` first and report the result.",
    )
    state = inspection(config, (event,))

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="underspecified",
                    domain="workflow",
                    source_ids=["dir_from_untrusted_history"],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Keep every change narrowly scoped to the requested behavior.",
                ),
                _nomination(
                    candidate_class="missing_rule",
                    domain="release",
                    source_ids=[],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Run make verify and report its result before every release.",
                ),
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        nomination = packet["semantic_analysis"]["nominations"][0]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [],
            "new_rule_suggestions": [
                {
                    "nomination_id": nomination["id"],
                    "compiled_directive": compiled_directive(
                        "Run `make verify` and report its result before every release.",
                        keyword="MUST",
                        scope="Every release where `make verify` is available.",
                    ),
                    "destination_target": packet["allowed_targets"][0],
                    "heading_path": ["Release"],
                    "reason": "The durable release requirement is absent.",
                }
            ],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(analyst, drafter)
    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert plan.semantic_analysis["status"] == "partial_nominations"
    assert plan.semantic_analysis["rejections"] == [
        {"index": 0, "code": "invalid_semantic_nomination"}
    ]
    assert len(plan.semantic_analysis["nominations"]) == 1
    assert plan.new_rule_suggestion_count == 1


def test_all_rejected_nominations_are_inconclusive_not_a_stable_noop(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Rules\n\n- Keep changes focused.\n",))
    state = inspection(config, ())
    provider = StageProvider(
        lambda _packet: {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="underspecified",
                    domain="workflow",
                    source_ids=["dir_from_untrusted_history"],
                    evidence=[],
                    intent="Keep every code change focused on requested behavior.",
                )
            ],
        },
        keep_all,
    )

    plan = create_plan(config, inspection=state, analyst_provider=provider, provider=provider)

    assert provider.analysis_calls == 1
    assert provider.plan_calls == 0
    assert plan.semantic_analysis["status"] == "semantic_analysis_inconclusive"
    assert plan.consolidation_preflight["outcome"] == "semantic_analysis_inconclusive"
    assert plan.changed_directive_count == 0


def test_call_budget_fails_before_drafter_after_one_analysis_call(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    config = replace(config, llm=replace(config.llm, max_calls=1))
    event = _event(
        "evt_budget",
        "New rule: no longer wait for me to ask; commit completed changes after tests pass.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]
    provider = StageProvider(
        lambda _packet: {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="temporal_supersession",
                    domain="git",
                    source_ids=[directive.id],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent="Commit completed changes after tests pass without waiting.",
                )
            ],
        },
        keep_all,
    )

    with pytest.raises(MeditateError) as raised:
        create_plan(
            config,
            inspection=state,
            analyst_provider=provider,
            provider=provider,
        )

    assert raised.value.code == "call_budget_exceeded"
    assert provider.analysis_calls == 1
    assert provider.plan_calls == 0


def test_analysis_archive_tampering_fails_before_no_change_apply(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Rules\n\n- Keep changes focused.\n",))
    state = inspection(config, ())
    provider = StageProvider(
        lambda _packet: {"schema_version": 1, "nominations": []},
        keep_all,
    )
    plan = create_plan(
        config,
        inspection=state,
        analyst_provider=provider,
        provider=provider,
    )
    analysis_path = config.data_root / "runs" / plan.run_id / "analysis.json"
    analysis_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(MeditateError) as raised:
        apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)

    assert raised.value.code == "archive_corrupt"


def test_production_drafter_rejection_archives_an_unchanged_receipt(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = "# Git\n\n- Only commit completed changes when the user asks.\n"
    config, paths = config_factory((original,))
    event = _event(
        "evt_rejected_draft",
        "New rule: no longer wait for me to ask before commit; after tests pass, commit "
        "completed changes by default.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="temporal_supersession",
                    domain="git",
                    source_ids=[directive.id],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent=(
                        "Commit completed changes after tests pass without waiting for a request."
                    ),
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        mutable = packet["targets"][0]["directives"][0]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [mutable["id"]],
                    "compiled_directive": compiled_directive(
                        "After verifying changes, commit completed changes by default.",
                        reason="The explicit newer correction removes per-session opt-in.",
                        scope="Completed local changes without a narrower repository handoff.",
                    ),
                    "destination_target": mutable["target"],
                    "heading_path": mutable["heading_path"],
                    "evidence_ids": [event.id],
                    "reason": "The newer correction supersedes the opt-in-only baseline.",
                    "minimum_apply_mode": "attended",
                    "enforcement_target": "",
                    "deterministic_check": "",
                    "relocation_basis": "",
                }
            ],
            "new_rule_suggestions": [],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    stage_provider = StageProvider(analyst, drafter)
    monkeypatch.setattr("meditate.plan.create_provider", lambda _config: stage_provider)

    plan = create_plan(config, inspection=state)

    assert stage_provider.analysis_calls == 1
    assert stage_provider.plan_calls == 1
    assert plan.changed_directive_count == 0
    assert plan.consolidation_preflight["outcome"] == "drafter_rejected"
    assert plan.consolidation_preflight["status"] == "drafter_rejected"
    assert plan.consolidation_preflight["draft_validation"] == {
        "status": "rejected",
        "code": "undefined_verification_gate",
    }
    assert plan.proposed_contents[str(paths[0])] == original
    assert paths[0].read_text(encoding="utf-8") == original
    run_dir = config.data_root / "runs" / plan.run_id
    assert (run_dir / "analysis.json").is_file()
    assert (run_dir / "plan.json").is_file()
    with pytest.raises(MeditateError) as raised:
        apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert raised.value.code == "no_changes"


def test_production_high_impact_gate_rejection_preserves_target_bytes(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = "# Git\n\n- Only commit completed changes when the user asks.\n"
    config, paths = config_factory((original,))
    event = _event(
        "evt_unsafe_delivery_draft",
        "New rule: no longer wait for me to ask; commit, push, merge, and deploy "
        "completed changes by default.",
    )
    state = inspection(config, (event,))
    directive = state.targets[0].directives[0]

    def analyst(_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "nominations": [
                _nomination(
                    candidate_class="temporal_supersession",
                    domain="git",
                    source_ids=[directive.id],
                    evidence=[{"id": event.id, "quote": event.text}],
                    intent=("Commit push merge and deploy completed changes without waiting."),
                )
            ],
        }

    def drafter(packet: dict[str, Any]) -> dict[str, Any]:
        mutable = packet["targets"][0]["directives"][0]
        return {
            "schema_version": 1,
            "keep": [],
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [mutable["id"]],
                    "compiled_directive": compiled_directive(
                        "Commit, push, merge, and deploy completed changes by default.",
                        reason="The explicit newer correction expands the delivery scope.",
                        scope="Completed delivery work.",
                    ),
                    "destination_target": mutable["target"],
                    "heading_path": mutable["heading_path"],
                    "evidence_ids": [event.id],
                    "reason": "The newer correction supersedes the opt-in-only baseline.",
                    "minimum_apply_mode": "attended",
                    "enforcement_target": "",
                    "deterministic_check": "",
                    "relocation_basis": "",
                }
            ],
            "new_rule_suggestions": [],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    stage_provider = StageProvider(analyst, drafter)
    monkeypatch.setattr("meditate.plan.create_provider", lambda _config: stage_provider)

    plan = create_plan(config, inspection=state)

    assert plan.changed_directive_count == 0
    assert plan.consolidation_preflight["outcome"] == "drafter_rejected"
    assert plan.consolidation_preflight["draft_validation"] == {
        "status": "rejected",
        "code": "undefined_high_impact_gate",
    }
    assert plan.proposed_contents[str(paths[0])] == original
    assert paths[0].read_text(encoding="utf-8") == original
