from __future__ import annotations

import re
from dataclasses import replace

import pytest
from conftest import ConfigFactory
from helpers import StubProvider, inspection, replace_matching

from meditate.models import Authority, EvidenceEvent
from meditate.plan import PLAN_PROMPT_VERSION, SYSTEM_PROMPT, create_plan
from meditate.transaction import PARSER_VERSION
from meditate.util import MeditateError, sha256_bytes


def _workflow_evidence(event_id: str, text: str) -> EvidenceEvent:
    return EvidenceEvent(
        id=event_id,
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id=f"stage-local-{event_id}",
        scope="global",
        text=text,
        source_locator=f"fixture:{event_id}",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def _workflow_config(config_factory: ConfigFactory):
    config, targets = config_factory(
        ("# Workflow\n\n- Commit only when asked.\n",),
        target_names=("CLAUDE.md",),
    )
    return replace(
        config,
        safety=replace(config.safety, size_ceiling_ratio=24.0),
    ), targets


def _canonical_workflow(actions: str) -> str:
    return (
        "- Treat cited action lists as coverage, not execution order. Execute "
        f"{actions} in the exact order required by loaded repository instructions and the "
        "documented workflow. Before each action, run only applicable project-required checks "
        "that are available before that action at its stage. Treat downstream CI as a check at "
        "its own stage, not as a precondition for earlier actions. Before each remote or "
        "irreversible action, explicitly look up authority in loaded repository instructions. "
        "Stop for any required human approval or named handoff."
    )


def test_global_precondition_cannot_authorize_later_merge_release_and_deploy_stages(
    config_factory: ConfigFactory,
) -> None:
    config, _targets = _workflow_config(config_factory)
    evidence_text = (
        "New rule: after all tests and CI pass, commit, merge, release, and deploy completed work."
    )
    provider = StubProvider(
        replace_matching(
            {
                "Commit only when asked": (
                    "- After all tests and CI pass, commit, merge, release, and deploy completed "
                    "work."
                )
            }
        )
    )

    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(
                config,
                (_workflow_evidence("evt_global_precondition", evidence_text),),
            ),
        )
    assert not (config.data_root / "runs").exists()


def test_new_remote_push_without_stage_local_workflow_authority_fails_closed(
    config_factory: ConfigFactory,
) -> None:
    config, _targets = _workflow_config(config_factory)
    evidence_text = "Push completed work to the configured remote."
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- Push completed work to the configured remote."}
        )
    )

    with pytest.raises(MeditateError):
        create_plan(
            config,
            provider=provider,
            inspection=inspection(
                config,
                (_workflow_evidence("evt_remote_push", evidence_text),),
            ),
        )
    assert not (config.data_root / "runs").exists()


def test_loaded_workflow_order_and_stage_available_project_checks_pass_structural_validation(
    config_factory: ConfigFactory,
) -> None:
    config, (target,) = _workflow_config(config_factory)
    evidence_text = "Required workflow actions: commit, merge, release, and deploy completed work."
    replacement = _canonical_workflow("commit, merge, release, and deploy")
    plan = create_plan(
        config,
        provider=StubProvider(replace_matching({"Commit only when asked": replacement})),
        inspection=inspection(
            config,
            (_workflow_evidence("evt_stage_local_workflow", evidence_text),),
        ),
    )

    assert plan.changed_directive_count == 1
    proposed = {str(path): content for path, content in plan.proposed_contents.items()}
    assert replacement.removeprefix("- ") in proposed[str(target)]
    for action in ("commit", "merge", "release", "deploy"):
        assert action in proposed[str(target)]


def test_prompt_encodes_action_coverage_not_order_and_stage_availability() -> None:
    prompt = " ".join(SYSTEM_PROMPT.lower().split())
    assert re.search(
        r"action\s+lists?.{0,160}coverage.{0,100}not.{0,60}(?:execution\s+)?order",
        prompt,
    )
    for term in ("applicable", "project-required", "available"):
        assert term in prompt
    assert re.search(
        r"available.{0,100}before.{0,80}(?:action|stage)|"
        r"before.{0,80}(?:action|stage).{0,100}available",
        prompt,
    )
    assert "loaded repository instructions" in prompt
    assert "documented workflow" in prompt
    assert re.search(r"exact\s+order|required\s+order", prompt)
    assert re.search(r"downstream\s+ci.{0,100}(?:its|own)\s+stage", prompt)
    assert re.search(r"(?:explicitly\s+)?look\s+up.{0,80}author", prompt)
    assert re.search(r"stop.{0,100}approval.{0,100}named\s+handoff", prompt)


def test_prompt_v13_parser_v28_require_literal_destination_targets_for_every_change() -> None:
    assert PLAN_PROMPT_VERSION == "18"
    assert PARSER_VERSION == "meditate-parser-v34"
    prompt = " ".join(SYSTEM_PROMPT.lower().split())
    assert re.search(
        r"every\s+change.{0,180}destination_target|"
        r"destination_target.{0,180}every\s+change",
        prompt,
    )
    assert re.search(
        r"every\s+change.{0,180}(?:remove.{0,80}escalate|escalate.{0,80}remove)",
        prompt,
    )
    assert re.search(
        r"destination_target.{0,160}(?:literal|exact|copy).{0,160}allowed_targets|"
        r"(?:literal|exact|copy).{0,160}destination_target.{0,160}allowed_targets",
        prompt,
    )
    for transformation in ("expand", "normaliz", "absolute"):
        assert re.search(
            rf"(?:do not|must not|never|without|forbid\w*).{{0,240}}{transformation}|"
            rf"{transformation}.{{0,160}}(?:forbid\w*|prohibit\w*|must not)",
            prompt,
        )
    assert "~" in SYSTEM_PROMPT
    prompt_plain = prompt.replace("`", "")
    source_target_rule = re.search(
        r"(?:for\s+)?replace\s*,\s*remove\s*,?\s*(?:and|&)\s*escalate.{0,240}",
        prompt_plain,
    )
    assert source_target_rule
    source_target_clause = source_target_rule.group()
    assert re.search(r"source\s+directive(?:'s|s')?\s+target", source_target_clause)
    assert re.search(r"copy|equal|match|same", source_target_clause)
    assert re.search(r"exact|identical", source_target_clause)
