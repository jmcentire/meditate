from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from meditate.config import Config
from meditate.evidence import build_inspection
from meditate.imports import build_import_graph
from meditate.models import EvidenceEvent, InspectionResult, RunUsage, SourceStats
from meditate.segment import load_targets
from meditate.verification import VerificationRunner, verify_run

PlanBuilder = Callable[[dict[str, Any]], dict[str, Any]]


def compiled_directive(
    text: str,
    *,
    keyword: str = "SHOULD",
    reason: str = "The cited evidence defines this behavior",
    scope: str = "The cited target and heading",
    boundary_example: str = "",
) -> dict[str, str]:
    """Build the strict planner record used by synthetic provider fixtures."""

    rule = text.strip().removeprefix("-").strip()
    for candidate in ("MUST NOT", "SHOULD NOT", "MUST", "SHOULD", "MAY"):
        if rule == candidate or rule.startswith(candidate + " "):
            keyword = candidate
            rule = rule.removeprefix(candidate).strip()
            break
    return {
        "normative_keyword": keyword,
        "rule": rule,
        "reason": reason,
        "scope": scope,
        "boundary_example": boundary_example,
    }


def empty_compiled_directive() -> dict[str, str]:
    return {
        "normative_keyword": "",
        "rule": "",
        "reason": "",
        "scope": "",
        "boundary_example": "",
    }


class StubProvider:
    name = "stub"
    model = "stub-model-v1"

    def __init__(self, builder: PlanBuilder) -> None:
        self.builder = builder
        self.calls = 0
        self.last_packet: dict[str, Any] | None = None
        self.last_schema: dict[str, Any] | None = None

    def complete(
        self, *, system: str, payload: str, schema: dict[str, Any]
    ) -> tuple[str, RunUsage]:
        assert "untrusted data" in system
        assert schema["type"] == "object"
        self.calls += 1
        self.last_packet = json.loads(payload)
        self.last_schema = schema
        result = self.builder(self.last_packet)
        return json.dumps(result), RunUsage(
            calls=1,
            actual_input_tokens=max(1, len(payload) // 4),
            actual_output_tokens=100,
            stop_reason="end_turn",
        )


class StubVerificationRunner:
    agent = "claude"
    model = "stub-consumer-v1"
    version = "stub-verifier 1"

    def __init__(self, *, fail_post: bool = False) -> None:
        self.fail_post = fail_post
        self.calls: list[tuple[str, str]] = []

    def run(
        self,
        *,
        condition: str,
        instruction_text: str,
        evaluation_prompt: str,
        response_schema: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        assert response_schema["type"] == "object"
        self.calls.append((condition, instruction_text))
        visible_cases = json.loads(evaluation_prompt.split("\n\n", 1)[1])
        steps = (
            ["Inspect the scenario without invoking the requested behavior."]
            if self.fail_post and condition == "post"
            else ["Invoke follow_rule for the requested behavior."]
        )
        payload = {
            "results": [{"case_ref": case["case_ref"], "steps": steps} for case in visible_cases]
        }
        return payload, {
            "condition": condition,
            "resolved_model": self.model,
            "response_sha256": "a" * 64,
        }


def qualify_plan(config: Config, run_id: str, *, fail_post: bool = False) -> dict[str, Any]:
    """Attach a synthetic owner-suite receipt for transaction-focused tests."""

    run_dir = config.data_root / "runs" / run_id
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    changed_targets = [item for item in plan["targets"] if item["changed"]]
    covers = [
        {
            "target_suffix": str(Path(item["logical_path"])),
            "heading_contains": "*",
        }
        for item in changed_targets
    ]
    suite = {
        "schema_version": 2,
        "suite_id": "synthetic-owner-suite-v1",
        "owner": "synthetic test owner",
        "action_detectors": {
            "follow_rule": ["follow_rule"],
            "ignore_rule": ["ignore_rule"],
        },
        "cases": [
            {
                "id": "preserve_requested_behavior",
                "description": "The requested behavior remains active.",
                "prompt": "Choose whether to follow the requested behavior.",
                "allowed_actions": ["follow_rule", "ignore_rule"],
                "required_actions": ["follow_rule"],
                "forbidden_actions": ["ignore_rule"],
                "ordered_actions": ["follow_rule"],
                "control_must_underperform": False,
                "covers": covers,
            }
        ],
    }
    suite_path = config.data_root / f"{run_id}-suite.json"
    suite_path.parent.mkdir(parents=True, exist_ok=True)
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    runner: VerificationRunner = StubVerificationRunner(fail_post=fail_post)
    return verify_run(
        config,
        run_id,
        suite_path=suite_path,
        agent="claude",
        model="stub-consumer-v1",
        repeats=1,
        runner=runner,
    )


def inspection(config: Config, events: tuple[EvidenceEvent, ...]) -> InspectionResult:
    return build_inspection(
        load_targets(config),
        build_import_graph(config),
        events,
        SourceStats(),
        (),
        config,
    )


def replace_matching(
    match_to_replacement: dict[str, str], *, evidence_index: int = 0
) -> PlanBuilder:
    def build(packet: dict[str, Any]) -> dict[str, Any]:
        evidence = packet["evidence_events_oldest_to_newest"][evidence_index]
        keep: list[str] = []
        changes: list[dict[str, Any]] = []
        for target in packet["targets"]:
            for directive in target["directives"]:
                replacement = next(
                    (
                        new_text
                        for old_fragment, new_text in match_to_replacement.items()
                        if old_fragment in directive["text"]
                    ),
                    None,
                )
                if replacement is None:
                    keep.append(directive["id"])
                    continue
                changes.append(
                    {
                        "action": "replace",
                        "source_ids": [directive["id"]],
                        "compiled_directive": compiled_directive(replacement),
                        "destination_target": target["target"],
                        "heading_path": directive["heading_path"],
                        "evidence": [{"id": evidence["id"], "quote": evidence["text"]}],
                        "reason": "The cited newer user correction replaces the old behavior.",
                        "minimum_apply_mode": "attended",
                        "relocation_basis": "",
                        "enforcement_target": "",
                        "deterministic_check": "",
                    }
                )
        return {
            "schema_version": 1,
            "keep": keep,
            "changes": changes,
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    return build


def keep_all(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "keep": [
            directive["id"] for target in packet["targets"] for directive in target["directives"]
        ],
        "changes": [],
        "decision_request": None,
        "unresolved_conflicts": [],
    }
