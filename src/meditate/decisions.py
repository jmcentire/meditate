"""Immutable, operator-asserted resolution of bounded planning decisions."""

from __future__ import annotations

import json
import shlex
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Config, with_archived_target_selection
from .models import InspectionResult, ValidatedPlan
from .plan import (
    MAX_CUSTOM_DECISION_CHARS,
    MAX_DECISION_DEPTH,
    PARSER_VERSION,
    PLAN_PROMPT_VERSION,
    SYSTEM_PROMPT,
    create_plan,
    inspection_from_frozen_packet,
)
from .provider import Provider
from .redact import sanitize_text, surviving_high_confidence
from .transaction import validate_decision_resolution_marker, verified_run_artifacts
from .util import (
    SCHEMA_VERSION,
    MeditateError,
    exclusive_lock,
    fail,
    load_json,
    sha256_bytes,
    sha256_text,
    validate_run_id,
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _pending_request(
    plan: dict[str, Any], state: dict[str, Any], request_id: str | None = None
) -> dict[str, Any]:
    if state.get("state") != "planned" or state.get("consumed"):
        fail("decision_not_pending", "The parent run is not an unused planned run")
    request = plan.get("decision_request")
    blocked = plan.get("blocked_reasons")
    if (
        not isinstance(request, dict)
        or not isinstance(blocked, list)
        or "decision_required" not in blocked
    ):
        fail("decision_not_pending", "The run has no pending decision request")
    observed_id = request.get("request_id")
    if not isinstance(observed_id, str) or not observed_id:
        fail("archive_corrupt", "The pending decision request has no local request ID")
    if request_id is not None and observed_id != request_id:
        fail("decision_not_found", f"Decision request not found: {request_id}")
    options = request.get("options")
    custom = request.get("custom")
    if (
        not isinstance(request.get("question"), str)
        or not isinstance(request.get("conflict_fingerprint"), str)
        or not isinstance(options, list)
        or len(options) != 3
        or not all(isinstance(item, dict) for item in options)
        or [item.get("key") for item in options] != ["a", "b", "c"]
        or options[0].get("recommended") is not True
        or any("recommended" in item for item in options[1:])
        or not isinstance(custom, dict)
        or custom.get("key") != "custom"
    ):
        fail("archive_corrupt", "The pending decision request is malformed")
    return request


def _response_argv(config: Config, run_id: str, request_id: str) -> dict[str, list[str]]:
    base = [
        "meditate",
        "decide",
        "--config",
        str(config.config_path),
        run_id,
        request_id,
    ]
    return {
        "a": [*base, "--choice", "a"],
        "b": [*base, "--choice", "b"],
        "c": [*base, "--choice", "c"],
        "custom": [*base, "--custom", "TEXT"],
    }


def decision_payload(config: Config, run_id: str) -> dict[str, Any]:
    """Return the exact archived question and deterministic response commands."""

    with exclusive_lock(config.state_root / "meditate.lock"):
        _run_dir, plan, _manifest, state = verified_run_artifacts(config, run_id)
        request = _pending_request(plan, state)
        request_id = str(request["request_id"])
        resolution = _resolution_for_request(config, run_id, str(plan["plan_sha256"]), request_id)
        if resolution is None:
            response_argv = _response_argv(config, run_id, request_id)
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "pending",
                "run_id": run_id,
                "plan_sha256": plan["plan_sha256"],
                "decision_request": request,
                "response_argv": response_argv,
                "response_commands": {key: shlex.join(argv) for key, argv in response_argv.items()},
                "authority_boundary": "operator_asserted_user_authority_not_identity_attested",
                "semantic_verification": plan.get("semantic_verification", {}),
            }
        if resolution["successor_status"] == "available":
            child_plan = resolution["child_plan"]
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "resolved",
                "successor_status": "available",
                "parent_run_id": run_id,
                "run_id": run_id,
                "plan_sha256": plan["plan_sha256"],
                "decision_request": request,
                "successor_run_id": resolution["successor_run_id"],
                "successor_plan_sha256": resolution["successor_plan_sha256"],
                "operator_decision": child_plan.get("operator_decision"),
                "authority_boundary": "operator_asserted_user_authority_not_identity_attested",
                "semantic_verification": child_plan.get("semantic_verification", {}),
            }
        marker = resolution["decision_resolution"]
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "resolved",
            "successor_status": "purged",
            "parent_run_id": marker["parent_run_id"],
            "run_id": run_id,
            "plan_sha256": plan["plan_sha256"],
            "decision_request": request,
            "successor_run_id": marker["successor_run_id"],
            "successor_plan_sha256": marker["successor_plan_sha256"],
            "conflict_fingerprint": marker["conflict_fingerprint"],
            "response_sha256": marker["response_sha256"],
            "decision_resolution": marker,
            "authority_boundary": "operator_asserted_user_authority_not_identity_attested",
            "semantic_verification": plan.get("semantic_verification", {}),
        }


def _validated_custom(value: str) -> str:
    if not value.strip():
        fail("invalid_decision_choice", "Custom decision text must be non-empty")
    if "\x00" in value:
        fail("invalid_decision_choice", "Custom decision text contains a NUL byte")
    if len(value) > MAX_CUSTOM_DECISION_CHARS:
        fail(
            "invalid_decision_choice",
            f"Custom decision text exceeds {MAX_CUSTOM_DECISION_CHARS} characters",
        )
    sanitized = sanitize_text(value, max_chars=max(MAX_CUSTOM_DECISION_CHARS, len(value)))
    if sanitized.has_high_confidence or surviving_high_confidence(value):
        fail("secret_in_decision", "Custom decision text contains a recognized secret")
    return value


def _resolution_for_request(
    config: Config, parent_run_id: str, parent_sha256: str, request_id: str
) -> dict[str, Any] | None:
    runs_root = config.data_root / "runs"
    if runs_root.is_dir():
        for candidate in sorted(runs_root.iterdir()):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                run_id = validate_run_id(candidate.name)
            except MeditateError:
                continue
            path = candidate / "plan.json"
            if path.is_symlink() or not path.is_file():
                continue
            try:
                value = load_json(path)
            except MeditateError:
                continue
            if not isinstance(value, dict) or value.get("parent_plan_sha256") != parent_sha256:
                continue
            decision = value.get("operator_decision")
            if (
                isinstance(decision, dict)
                and decision.get("parent_run_id") == parent_run_id
                and decision.get("request_id") == request_id
            ):
                _child_dir, child_plan, _child_manifest, _child_state = verified_run_artifacts(
                    config, run_id
                )
                return {
                    "successor_status": "available",
                    "parent_run_id": parent_run_id,
                    "successor_run_id": run_id,
                    "successor_plan_sha256": child_plan["plan_sha256"],
                    "child_plan": child_plan,
                }
    tombstones_root = config.data_root / "tombstones"
    if not tombstones_root.exists():
        return None
    if tombstones_root.is_symlink() or not tombstones_root.is_dir():
        fail("archive_corrupt", "The run tombstone directory is unsafe")
    for candidate in sorted(tombstones_root.iterdir()):
        if candidate.suffix != ".json":
            continue
        if candidate.is_symlink() or not candidate.is_file():
            fail("archive_corrupt", f"Unsafe run tombstone: {candidate.name}")
        value = load_json(candidate)
        if not isinstance(value, dict):
            fail("archive_corrupt", f"Malformed run tombstone: {candidate.name}")
        raw_marker = value.get("decision_resolution")
        if raw_marker is None:
            continue
        marker = validate_decision_resolution_marker(raw_marker)
        if (
            marker["parent_run_id"] == parent_run_id
            and marker["parent_plan_sha256"] == parent_sha256
            and marker["request_id"] == request_id
        ):
            return {
                "successor_status": "purged",
                "parent_run_id": marker["parent_run_id"],
                "successor_run_id": marker["successor_run_id"],
                "successor_plan_sha256": marker["successor_plan_sha256"],
                "decision_resolution": marker,
            }
    return None


def _frozen_context(
    config: Config,
    run_dir: Path,
    plan: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], InspectionResult, Config]:
    if (
        plan.get("config_sha256") != config.hash
        or manifest.get("config_sha256") != config.hash
        or plan.get("parser_version") != PARSER_VERSION
        or manifest.get("parser_version") != PARSER_VERSION
        or plan.get("prompt_version") != PLAN_PROMPT_VERSION
        or manifest.get("prompt_version") != PLAN_PROMPT_VERSION
        or plan.get("prompt_sha256") != sha256_text(SYSTEM_PROMPT)
        or manifest.get("prompt_sha256") != sha256_text(SYSTEM_PROMPT)
        or plan.get("provider") != config.llm.provider
        or plan.get("model") != config.llm.model
    ):
        fail(
            "decision_context_drift",
            "Configuration, prompt, parser, provider, or requested model changed "
            "after the question",
        )
    effective_config = with_archived_target_selection(config, plan.get("target_selection"))
    packet_path = run_dir / "evidence.json"
    if packet_path.is_symlink() or not packet_path.is_file():
        fail("decision_context_drift", "Parent evidence packet is missing or unsafe")
    try:
        packet_bytes = packet_path.read_bytes()
        packet = json.loads(packet_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("decision_context_drift", "Parent evidence packet is unreadable")
    packet_sha256 = sha256_bytes(packet_bytes)
    if (
        not isinstance(packet, dict)
        or packet_sha256 != plan.get("evidence_sha256")
        or packet_sha256 != manifest.get("packet_sha256")
    ):
        fail("decision_context_drift", "Parent evidence packet failed its bound hash")
    lineage = plan.get("decision_lineage")
    packet_decisions = packet.get("operator_decisions")
    if (
        not isinstance(lineage, dict)
        or packet.get("decision_lineage") != lineage
        or not isinstance(packet_decisions, list)
        or not all(isinstance(item, dict) for item in packet_decisions)
        or len(packet_decisions) != lineage.get("depth")
        or (packet_decisions[-1] if packet_decisions else None) != plan.get("operator_decision")
    ):
        fail("decision_context_drift", "Parent operator decision lineage is inconsistent")
    source_stats = manifest.get("source_stats")
    if not isinstance(source_stats, dict):
        fail("decision_context_drift", "Parent source statistics are malformed")
    if packet.get("target_selection") != effective_config.target_selection:
        fail("decision_context_drift", "Parent packet target selection is inconsistent")
    inspection = inspection_from_frozen_packet(effective_config, packet, source_stats)

    expected_targets = manifest.get("targets")
    if not isinstance(expected_targets, list) or not all(
        isinstance(item, dict) for item in expected_targets
    ):
        fail("decision_context_drift", "Parent target manifest is malformed")
    expected = {
        str(item.get("logical_path")): (
            item.get("semantic_sha256", item.get("pre_sha256")),
            item.get("pre_sha256"),
            item.get("existed"),
            item.get("mode"),
        )
        for item in expected_targets
    }
    observed = {
        target.logical_path: (
            target.sha256,
            target.archived_preimage_sha256,
            target.existed,
            target.mode,
        )
        for target in inspection.targets
    }
    if observed != expected:
        fail("decision_context_drift", "Configured target bytes changed after the question")
    observed_graph = inspection.import_graph.public_dict()
    if (
        observed_graph != plan.get("import_graph_before")
        or packet.get("import_graph") != observed_graph
    ):
        fail("decision_context_drift", "Claude import graph changed after the question")
    allowed_targets = packet.get("allowed_targets")
    if allowed_targets != [target.logical_path for target in inspection.targets]:
        fail("decision_context_drift", "Configured target order changed after the question")
    expected_inputs = manifest.get("input_documents")
    observed_inputs = [
        {
            "path": str(item.path),
            "logical_path": item.logical_path,
            "sha256": item.sha256,
            "bytes": len(item.content_bytes),
            "mode": item.mode,
            "existed": item.existed,
            "frontmatter": bool(item.frontmatter),
        }
        for item in inspection.input_documents
    ]
    if expected_inputs != observed_inputs:
        fail("decision_context_drift", "Semantic input bytes changed after the question")
    return packet, inspection, effective_config


def resolve_decision(
    config: Config,
    run_id: str,
    request_id: str,
    *,
    choice: str | None = None,
    custom: str | None = None,
    provider: Provider | None = None,
) -> ValidatedPlan:
    """Bind one asserted user choice into a fresh, frozen-context plan."""

    if (choice is None) == (custom is None):
        fail("invalid_decision_choice", "Supply exactly one of --choice or --custom")
    with exclusive_lock(config.state_root / "meditate.lock"):
        run_dir, plan, manifest, state = verified_run_artifacts(config, run_id)
        request = _pending_request(plan, state, request_id)
        parent_sha256 = str(plan["plan_sha256"])
        replay = _resolution_for_request(config, run_id, parent_sha256, request_id)
        if replay is not None:
            fail(
                "decision_replayed",
                f"Decision request already produced successor run {replay['successor_run_id']}",
            )

        lineage = plan.get("decision_lineage")
        if not isinstance(lineage, dict):
            fail("archive_corrupt", "Parent decision lineage is missing")
        depth = lineage.get("depth")
        resolved_ids = lineage.get("resolved_request_ids")
        fingerprints = lineage.get("conflict_fingerprints")
        if (
            not isinstance(depth, int)
            or isinstance(depth, bool)
            or not isinstance(resolved_ids, list)
            or not all(isinstance(item, str) for item in resolved_ids)
            or not isinstance(fingerprints, list)
            or not all(isinstance(item, str) for item in fingerprints)
        ):
            fail("archive_corrupt", "Parent decision lineage is malformed")
        if depth >= MAX_DECISION_DEPTH:
            fail(
                "decision_depth_exceeded",
                f"Decision chains are limited to {MAX_DECISION_DEPTH} operator choices",
            )
        fingerprint = request.get("conflict_fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            fail("archive_corrupt", "Parent conflict fingerprint is malformed")
        if request_id in resolved_ids or fingerprint in fingerprints:
            fail("decision_replayed", "Decision request is already present in its own lineage")

        options = request["options"]
        selected_option: dict[str, Any] | None = None
        if choice is not None:
            if choice not in {"a", "b", "c"}:
                fail("invalid_decision_choice", "Decision choice must be a, b, or c")
            selected_option = next(
                (deepcopy(item) for item in options if item.get("key") == choice), None
            )
            if selected_option is None or not isinstance(selected_option.get("label"), str):
                fail("archive_corrupt", "Selected archived option is malformed")
            response_kind = "choice"
            response_text = str(selected_option["label"])
            choice_key: str | None = choice
        else:
            response_kind = "custom"
            response_text = _validated_custom(str(custom))
            choice_key = None
        operator_decision = {
            "authority": "operator_asserted_user",
            "identity_attestation": "not_provided",
            "recorded_at": _now(),
            "parent_run_id": run_id,
            "parent_plan_sha256": parent_sha256,
            "parent_packet_sha256": str(plan["evidence_sha256"]),
            "request_id": request_id,
            "conflict_fingerprint": fingerprint,
            "collision_scope": {
                "subject_a": request["subject_a"],
                "subject_b": request["subject_b"],
                "directive_ids": deepcopy(request["directive_ids"]),
                "evidence_ids": deepcopy(request["evidence_ids"]),
            },
            "response_kind": response_kind,
            "choice_key": choice_key,
            "response_text": response_text,
            "selected_option": selected_option,
            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        }
        next_lineage = {
            "depth": depth + 1,
            "resolved_request_ids": [*resolved_ids, request_id],
            "conflict_fingerprints": [*fingerprints, fingerprint],
        }
        packet, inspection, effective_config = _frozen_context(config, run_dir, plan, manifest)
        dropped = manifest.get("dropped_evidence_ids", [])
        if not isinstance(dropped, list) or not all(isinstance(item, str) for item in dropped):
            fail("decision_context_drift", "Parent dropped-evidence lineage is malformed")
        if provider is not None and (
            provider.name != plan.get("provider") or provider.model != plan.get("model")
        ):
            fail("decision_context_drift", "Provider or requested model changed after the question")
        return create_plan(
            effective_config,
            provider=provider,
            inspection=inspection,
            frozen_packet=packet,
            operator_decision=operator_decision,
            parent_plan_sha256=parent_sha256,
            parent_packet_sha256=str(plan["evidence_sha256"]),
            decision_lineage=next_lineage,
            dropped_evidence_ids=tuple(dropped),
            expected_model_id=str(plan["model_id"]),
        )
