from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from meditate.config import Config
from meditate.evidence import build_inspection
from meditate.imports import build_import_graph
from meditate.models import EvidenceEvent, InspectionResult, RunUsage, SourceStats
from meditate.segment import load_targets

PlanBuilder = Callable[[dict[str, Any]], dict[str, Any]]


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
                        "replacement": replacement,
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
