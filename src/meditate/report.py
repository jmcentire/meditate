"""Redaction-safe JSON/Markdown reports and append-only summary logging."""

from __future__ import annotations

import difflib
import fcntl
import html
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from .analyst import analysis_summary
from .config import Config
from .models import InspectionResult, ValidatedPlan
from .plan import inspection_dict
from .redact import surviving_high_confidence
from .util import (
    SCHEMA_VERSION,
    atomic_write,
    atomic_write_json,
    ensure_private_dir,
    exclusive_lock,
    fail,
    new_run_id,
)


def _reports_root(config: Config) -> Path:
    return ensure_private_dir(config.state_root / "reports")


_MARKDOWN_METACHARACTER = re.compile(r"([\\`*_[\]{}()#+!|>~])")


def _plain_text(value: str) -> str:
    return html.escape(value, quote=False).replace("\x00", "�")


def _safe_markdown(value: str) -> str:
    single_display_line = _plain_text(value).replace("\r", r"\r").replace("\n", r"\n")
    return _MARKDOWN_METACHARACTER.sub(r"\\\1", single_display_line)


def _safe_code(value: str) -> str:
    return _plain_text(value)


def _indented(value: str) -> str:
    return "\n".join(f"    {line}" for line in _safe_code(value).splitlines())


def append_log(config: Config, event: dict[str, Any]) -> None:
    log_root = ensure_private_dir(config.state_root / "logs")
    path = log_root / "meditate.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        payload = (json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def decision_log_summary(
    decision_request: dict[str, Any] | None,
    operator_decision: dict[str, Any] | None,
    decision_lineage: dict[str, Any],
) -> dict[str, Any]:
    """Return decision provenance safe for the append-only summary log."""

    request = decision_request if isinstance(decision_request, dict) else {}
    operator = operator_decision if isinstance(operator_decision, dict) else {}
    depth = decision_lineage.get("depth") if isinstance(decision_lineage, dict) else None
    return {
        "decision_request_id": request.get("request_id"),
        "decision_conflict_fingerprint": request.get("conflict_fingerprint"),
        "operator_parent_run_id": operator.get("parent_run_id"),
        "operator_request_id": operator.get("request_id"),
        "operator_conflict_fingerprint": operator.get("conflict_fingerprint"),
        "operator_response_kind": operator.get("response_kind"),
        "operator_choice_key": operator.get("choice_key"),
        "operator_response_sha256": operator.get("response_sha256"),
        "decision_lineage_depth": depth,
    }


def write_inspection_report(config: Config, result: InspectionResult) -> tuple[str, Path, Path]:
    report_id = f"inspect-{new_run_id()}"
    payload = inspection_dict(result, config)
    payload["report_id"] = report_id
    root = _reports_root(config)
    json_path = root / f"{report_id}.json"
    md_path = root / f"{report_id}.md"
    atomic_write_json(json_path, payload)
    markdown = f"""# Meditate inspection

- Report: `{report_id}`
- Targets: {len(result.targets)}
- Directives: {sum(len(target.directives) for target in result.targets)}
- Evidence records: {len(result.events)} total; {len(result.selected_events)} selected
- Sensitive records excluded locally: {result.stats.sensitive_records_excluded}
- Malformed records: {result.stats.malformed_records} of {result.stats.records_seen}
- Potential overlaps: {len(result.overlaps)}
- Claude import graph: {len(result.import_graph.documents)} nodes /
  {len(result.import_graph.edges)} edges
- Claude import graph digest: `{result.import_graph.digest}`
- Degraded conditions: {", ".join(result.degraded) if result.degraded else "none"}

This local-only report contains counts, hashes, and detector IDs. It contains no
raw interaction text. Run `meditate plan` to create an evidence-backed proposal.
"""
    atomic_write(md_path, markdown.encode("utf-8"))
    append_log(
        config,
        {
            "schema_version": SCHEMA_VERSION,
            "event": "inspection_complete",
            "report_id": report_id,
            "targets": len(result.targets),
            "directives": sum(len(target.directives) for target in result.targets),
            "events": len(result.events),
            "selected": len(result.selected_events),
            "sensitive_excluded": result.stats.sensitive_records_excluded,
            "malformed": result.stats.malformed_records,
            "degraded": list(result.degraded),
            "import_graph": result.import_graph.public_dict(),
        },
    )
    return report_id, json_path, md_path


def _write_plan_report_unlocked(config: Config, plan: ValidatedPlan) -> tuple[Path, Path]:
    root = _reports_root(config)
    json_path = root / f"{plan.run_id}.json"
    md_path = root / f"{plan.run_id}.md"
    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    semantic_analysis_public = analysis_summary(plan.semantic_analysis)
    decision_response_argv: dict[str, list[str]] = {}
    if plan.decision_request:
        response_base = [
            "meditate",
            "decide",
            "--config",
            str(config.config_path),
            plan.run_id,
            str(plan.decision_request["request_id"]),
        ]
        decision_response_argv = {
            "a": [*response_base, "--choice", "a"],
            "b": [*response_base, "--choice", "b"],
            "c": [*response_base, "--choice", "c"],
            "custom": [*response_base, "--custom", "TEXT"],
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": plan.run_id,
        "plan_sha256": plan.plan_sha256,
        "provider": plan.provider,
        "model": plan.model,
        "model_id": plan.model_id,
        "prompt_version": plan.prompt_version,
        "prompt_sha256": plan.prompt_sha256,
        "semantic_verification": plan.semantic_verification,
        "semantic_analysis": plan.semantic_analysis,
        "semantic_analysis_summary": semantic_analysis_public,
        "consolidation_preflight": plan.consolidation_preflight,
        "decision_request": plan.decision_request,
        "operator_decision": plan.operator_decision,
        "parent_plan_sha256": plan.parent_plan_sha256,
        "parent_packet_sha256": plan.parent_packet_sha256,
        "decision_lineage": plan.decision_lineage,
        "decision_response_argv": decision_response_argv,
        "decision_response_commands": {
            key: shlex.join(argv) for key, argv in decision_response_argv.items()
        },
        "minimum_apply_mode": plan.minimum_apply_mode,
        "blocked_reasons": list(plan.blocked_reasons),
        "directives": plan.directive_count,
        "pre_directives": plan.directive_count,
        "post_directives": plan.post_directive_count,
        "changed_directives": plan.changed_directive_count,
        "escalated_directives": plan.escalated_directive_count,
        "new_rule_suggestions": plan.raw_plan.get("new_rule_suggestions", []),
        "directive_delta": plan.metrics.get("directive_delta", 0),
        "pre_bytes": plan.metrics.get("pre_bytes", 0),
        "post_bytes": plan.metrics.get("post_bytes", 0),
        "byte_delta": plan.metrics.get("byte_delta", 0),
        "pre_lines": plan.metrics.get("pre_lines", 0),
        "post_lines": plan.metrics.get("post_lines", 0),
        "line_delta": plan.metrics.get("line_delta", 0),
        "metrics": plan.metrics,
        "targets": manifest.get("targets", []),
        "usage": plan.usage.to_dict(),
        "summary": plan.raw_plan.get("summary", ""),
        "unresolved_conflicts": plan.raw_plan.get("unresolved_conflicts", []),
        "changes": [
            {
                "action": item["action"],
                "source_ids": item["source_ids"],
                "destination_target": item["destination_target"],
                "reason": item["reason"],
                "defect_classes": item.get("defect_classes", []),
                "compiled_directive": item.get("compiled_directive", {}),
                "minimum_apply_mode": item["minimum_apply_mode"],
                "evidence_ids": [citation["id"] for citation in item["evidence"]],
                "baseline_support": item.get("baseline_support", []),
                "enforcement_target": item.get("enforcement_target", ""),
                "deterministic_check": item.get("deterministic_check", ""),
                "relocation_basis": item.get("relocation_basis", ""),
                "candidate_only": item.get("candidate_only", False),
                "lineage_depth": item.get("lineage_depth", 0),
            }
            for item in plan.raw_plan.get("changes", [])
        ],
    }
    atomic_write_json(json_path, payload)

    codex_budget = plan.metrics.get("codex_instruction_budget", {})
    if not isinstance(codex_budget, dict):
        codex_budget = {}
    sections = [
        "# Meditate proposal",
        "",
        f"- Run: `{plan.run_id}`",
        f"- Plan SHA-256: `{plan.plan_sha256}`",
        f"- Requested model: `{plan.provider}:{plan.model}`",
        f"- Resolved model ID: `{plan.model_id}`",
        f"- Prompt version: `{plan.prompt_version}`",
        f"- Prompt SHA-256: `{plan.prompt_sha256}`",
        (
            "- Consolidation preflight: "
            f"`{_safe_code(str(plan.consolidation_preflight.get('status', 'unknown')))}`; "
            f"clusters {plan.consolidation_preflight.get('clusters', 0)}; "
            f"provider called "
            f"{str(plan.consolidation_preflight.get('provider_called', False)).lower()}; "
            f"estimated input bytes avoided "
            f"{plan.consolidation_preflight.get('estimated_input_tokens_avoided', 0)}"
        ),
        (
            "- Defect outcome: "
            f"`{_safe_code(str(plan.consolidation_preflight.get('outcome', 'unknown')))}`; "
            "detected "
            f"{', '.join(plan.consolidation_preflight.get('defect_classes', [])) or 'none'}; "
            "resolved "
            f"{', '.join(plan.consolidation_preflight.get('defects_resolved', [])) or 'none'}; "
            "unresolved "
            f"{', '.join(plan.consolidation_preflight.get('defects_unresolved', [])) or 'none'}"
        ),
        "- Semantic verification: "
        f"`{plan.semantic_verification.get('status', '')}` via "
        f"`{plan.semantic_verification.get('method', '')}`",
        f"- Pre directives: {plan.directive_count}",
        f"- Post directives: {plan.post_directive_count}",
        f"- Directive delta: {plan.metrics.get('directive_delta', 0):+d}",
        f"- Changed directives: {plan.changed_directive_count}",
        f"- Escalated directives: {plan.escalated_directive_count}",
        f"- Report-only new-rule hypotheses: {plan.new_rule_suggestion_count}",
        (
            "- Semantic Analyst: "
            f"`{_safe_code(str(semantic_analysis_public.get('status', 'not_run')))}`; "
            f"nominations {semantic_analysis_public.get('nominations', 0)}; "
            f"rejected {semantic_analysis_public.get('rejected_nominations', 0)}; "
            f"cache hit {str(semantic_analysis_public.get('cache_hit', False)).lower()}; "
            f"authority `nomination_only`"
        ),
        f"- Byte telemetry — pre: {plan.metrics.get('pre_bytes', 0)}",
        f"- Byte telemetry — post: {plan.metrics.get('post_bytes', 0)}",
        f"- Byte telemetry — delta: {plan.metrics.get('byte_delta', 0):+d}",
        f"- Pre lines: {plan.metrics.get('pre_lines', 0)}",
        f"- Post lines: {plan.metrics.get('post_lines', 0)}",
        f"- Line delta: {plan.metrics.get('line_delta', 0):+d}",
        (
            "- Codex instruction budget: "
            f"status `{_safe_code(str(codex_budget.get('status', 'unknown')))}`; "
            f"post bytes {codex_budget.get('post_bytes', 0)}; "
            f"limit {codex_budget.get('project_doc_max_bytes', 0)}; "
            f"source `{_safe_code(str(codex_budget.get('source', 'unknown')))}`; "
            f"coverage `{_safe_code(str(codex_budget.get('coverage', 'unknown')))}`; "
            f"configured targets {codex_budget.get('configured_target_count', 0)}"
        ),
        f"- Minimum apply mode: `{plan.minimum_apply_mode}`",
        f"- Blocked: {', '.join(plan.blocked_reasons) if plan.blocked_reasons else 'no'}",
        f"- Parent plan SHA-256: `{plan.parent_plan_sha256 or 'none'}`",
        f"- Parent packet SHA-256: `{plan.parent_packet_sha256 or 'none'}`",
        f"- Decision depth: {plan.decision_lineage.get('depth', 0)}",
        (
            f"- Tokens: {plan.usage.actual_input_tokens} input / "
            f"{plan.usage.actual_output_tokens} output"
        ),
        "",
        "Structural validation is not behavioral qualification. Every changed plan remains "
        "inapplicable until a frozen owner-authored probe/counter-probe suite passes; the planner "
        "never receives that suite or its results.",
        "",
        "## Summary",
        "",
        _safe_markdown(str(plan.raw_plan.get("summary", ""))),
    ]
    nominations = plan.semantic_analysis.get("nominations", [])
    rejected_nominations = plan.semantic_analysis.get("rejections", [])
    if isinstance(rejected_nominations, list) and rejected_nominations:
        rejection_codes = sorted(
            str(item.get("code", "unknown"))
            for item in rejected_nominations
            if isinstance(item, dict)
        )
        sections.extend(
            [
                "",
                "## Rejected semantic nominations",
                "",
                f"Local validation rejected {len(rejected_nominations)} nomination(s) before "
                "they could influence a plan. Rejection codes: "
                + ", ".join(f"`{_safe_code(code)}`" for code in rejection_codes)
                + ". Model text is not repeated here.",
            ]
        )
    if isinstance(nominations, list) and nominations:
        admission_labels = {
            "mutable_candidate": (
                "eligible for the bounded Drafter because every cited directive shares one "
                "exact target and heading"
            ),
            "reported_only": (
                "report only because the hypothesis crosses a target or heading boundary"
            ),
            "suggestion_candidate": (
                "missing-behavior hypothesis eligible only for a report-only draft"
            ),
        }
        sections.extend(
            [
                "",
                "## Semantic Analyst nominations",
                "",
                "These are evidence-grounded hypotheses, not proven defects, directives, or write "
                "authority. Local validation checks identity, citations, scope shape, and "
                "admission; "
                "it does not prove the Analyst's semantic judgment.",
            ]
        )
        for nomination in nominations:
            if not isinstance(nomination, dict):
                continue
            admission = str(nomination.get("admission", ""))
            sections.extend(
                [
                    "",
                    f"### `{_safe_code(str(nomination.get('id', '')))}`",
                    "",
                    f"- Class: `{_safe_code(str(nomination.get('candidate_class', '')))}`",
                    f"- Domain: `{_safe_code(str(nomination.get('domain', '')))}`",
                    f"- Admission: `{_safe_code(admission)}` — "
                    + _safe_markdown(admission_labels.get(admission, "unknown local state")),
                    "- Source IDs: "
                    + (
                        ", ".join(f"`{item}`" for item in nomination.get("source_ids", []))
                        or "none"
                    ),
                    "- Intent: " + _safe_markdown(str(nomination.get("behavioral_intent", ""))),
                    "- Reason: " + _safe_markdown(str(nomination.get("reason", ""))),
                    "- Applies when: " + _safe_markdown(str(nomination.get("applies_when", ""))),
                    "- Does not apply when: "
                    + _safe_markdown(str(nomination.get("does_not_apply_when", ""))),
                    "- Evidence:",
                ]
            )
            for citation in nomination.get("evidence", []):
                if isinstance(citation, dict):
                    sections.append(
                        f"  - `{citation.get('id', '')}`: "
                        + _safe_markdown(str(citation.get("quote", "")))
                    )

    suggestions = plan.raw_plan.get("new_rule_suggestions", [])
    if isinstance(suggestions, list) and suggestions:
        sections.extend(
            [
                "",
                "## Report-only new-rule hypotheses",
                "",
                "These drafts are not included in proposed target bytes and cannot be applied. "
                "Each derives from the named Analyst nomination and requires explicit promotion "
                "plus independent behavioral qualification. Meditate v0.3 has no promotion "
                "command: the operator must deliberately author or promote the rule after "
                "supplying a hidden owner-authored probe/counter-probe suite.",
            ]
        )
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            compiled = suggestion.get("compiled_directive", {})
            sections.extend(
                [
                    "",
                    f"### `{_safe_code(str(suggestion.get('nomination_id', '')))}`",
                    "",
                    "- Destination candidate: `"
                    + _safe_code(str(suggestion.get("destination_target", "")))
                    + "`",
                    "- Heading candidate: "
                    + " / ".join(
                        _safe_markdown(str(item)) for item in suggestion.get("heading_path", [])
                    ),
                    "- Normative keyword: "
                    f"`{_safe_code(str(compiled.get('normative_keyword', '')))}`",
                    f"- Rule: {_safe_markdown(str(compiled.get('rule', '')))}",
                    f"- Reason: {_safe_markdown(str(compiled.get('reason', '')))}",
                    f"- Scope: {_safe_markdown(str(compiled.get('scope', '')))}",
                    "- Boundary example: "
                    + (
                        _safe_markdown(str(compiled.get("boundary_example", "")))
                        if compiled.get("boundary_example")
                        else "none"
                    ),
                    "- Write authority: `none`",
                ]
            )
    if plan.operator_decision:
        decision = plan.operator_decision
        collision_scope = decision.get("collision_scope", {})
        subject_a = (
            collision_scope.get("subject_a", "") if isinstance(collision_scope, dict) else ""
        )
        subject_b = (
            collision_scope.get("subject_b", "") if isinstance(collision_scope, dict) else ""
        )
        sections.extend(
            [
                "",
                "## Operator-asserted decision authority",
                "",
                f"- Request: `{_safe_code(str(decision.get('request_id', '')))}`",
                f"- Collision: {_safe_markdown(str(subject_a))} / {_safe_markdown(str(subject_b))}",
                f"- Parent run: `{_safe_code(str(decision.get('parent_run_id', '')))}`",
                f"- Parent plan SHA-256: `{decision.get('parent_plan_sha256', '')}`",
                f"- Parent packet SHA-256: `{decision.get('parent_packet_sha256', '')}`",
                f"- Conflict fingerprint: `{decision.get('conflict_fingerprint', '')}`",
                f"- Response kind: `{_safe_code(str(decision.get('response_kind', '')))}`",
                f"- Choice key: `{_safe_code(str(decision.get('choice_key', '')))}`",
                f"- Response: {_safe_markdown(str(decision.get('response_text', '')))}",
                f"- Response SHA-256: `{decision.get('response_sha256', '')}`",
                f"- Decision lineage depth: `{plan.decision_lineage.get('depth', 0)}`",
                "- Authority: operator-asserted user authority; identity is not authenticated "
                "or attested.",
                "- Scope: this choice cannot bypass protected directives, deterministic safety, "
                "or higher-scope loaded authority.",
            ]
        )
    decision_request = plan.decision_request
    if decision_request:
        sections.extend(
            [
                "",
                "## Decision required",
                "",
                _safe_markdown(str(decision_request["question"])),
                "",
                "The recommendation is model-authored and advisory. Its evidence grounding is "
                "structurally checked, but its framing and recommendation are not semantically "
                "verified and it is never a default answer.",
                "",
                "Recommendation rationale: "
                + _safe_markdown(decision_request["recommendation_rationale"]),
                "",
            ]
        )
        for option in decision_request["options"]:
            marker = " (recommended)" if option.get("recommended") is True else ""
            sections.extend(
                [
                    f"- `{option['key']}` — {_safe_markdown(option['label'])}{marker}",
                    f"  - Consequence: {_safe_markdown(option['consequence'])}",
                    f"  - Rationale: {_safe_markdown(option['rationale'])}",
                    "  - Evidence: " + ", ".join(f"`{item}`" for item in option["evidence_ids"]),
                ]
            )
        sections.extend(
            [
                f"- `custom` — {_safe_markdown(decision_request['custom']['label'])}",
                "",
                "Deterministic responses:",
                "",
                *[f"- `{shlex.join(decision_response_argv[key])}`" for key in ("a", "b", "c")],
                f"- `{shlex.join(decision_response_argv['custom'])}`",
                "",
                "An invoking agent must relay the user's explicit choice. Meditate hashes and "
                "records that operator assertion; it cannot attest the speaker's identity.",
            ]
        )
    conflicts = plan.raw_plan.get("unresolved_conflicts", [])
    if conflicts:
        sections.extend(["", "## Unresolved conflicts", ""])
        for conflict in conflicts:
            sections.extend(
                [
                    f"- {_safe_markdown(conflict['description'])}",
                    "  - Directives: "
                    + ", ".join(f"`{item}`" for item in conflict["directive_ids"]),
                    "  - Evidence: " + ", ".join(f"`{item}`" for item in conflict["evidence_ids"]),
                ]
            )
    for index, change in enumerate(plan.raw_plan.get("changes", []), start=1):
        sections.extend(
            [
                "",
                f"## Change {index}: {change['action']}",
                "",
                f"- Source IDs: {', '.join(f'`{item}`' for item in change['source_ids'])}",
                f"- Destination: `{_safe_code(change['destination_target'])}`",
                f"- Apply mode: `{change['minimum_apply_mode']}`",
                f"- Reason: {_safe_markdown(change['reason'])}",
                "- Defect classes: "
                + (", ".join(f"`{item}`" for item in change.get("defect_classes", [])) or "none"),
                f"- Relocation basis: `{change.get('relocation_basis', '')}`",
                f"- Candidate only: `{str(change.get('candidate_only', False)).lower()}`",
                "- Evidence:",
            ]
        )
        if change["action"] == "escalate":
            sections.extend(
                [
                    f"- Enforcement target: `{change['enforcement_target']}`",
                    f"- Deterministic check: {_safe_markdown(change['deterministic_check'])}",
                    f"- Locally computed lineage depth: {change['lineage_depth']}",
                    "- Report-only: source prose is preserved byte-for-byte; Meditate does not "
                    "write hooks or settings.",
                ]
            )
        compiled = change.get("compiled_directive", {})
        if isinstance(compiled, dict) and any(compiled.values()):
            sections.extend(
                [
                    "- Normative keyword: "
                    f"`{_safe_code(str(compiled.get('normative_keyword', '')))}`",
                    f"- Rule: {_safe_markdown(str(compiled.get('rule', '')))}",
                    f"- Directive rationale: {_safe_markdown(str(compiled.get('reason', '')))}",
                    f"- Scope: {_safe_markdown(str(compiled.get('scope', '')))}",
                    "- Boundary example: "
                    + (
                        _safe_markdown(str(compiled.get("boundary_example", "")))
                        if compiled.get("boundary_example")
                        else "none"
                    ),
                ]
            )
        for citation in change["evidence"]:
            sections.append(f"  - `{citation['id']}`: {_safe_markdown(citation['quote'])}")
        baseline_support = change.get("baseline_support", [])
        if baseline_support:
            sections.append("- Kept baseline support:")
            for support in baseline_support:
                identifiers = ", ".join(f"`{item}`" for item in support["directive_ids"])
                sections.append(f"  - `{support['action']}`: {identifiers}")
    sections.extend(["", "## File diffs", ""])
    for target in manifest["targets"]:
        pre = (run_dir / target["pre_blob"]).read_text(encoding="utf-8")
        post = (run_dir / target["post_blob"]).read_text(encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                pre.splitlines(keepends=True),
                post.splitlines(keepends=True),
                fromfile=f"before:{target['logical_path']}",
                tofile=f"after:{target['logical_path']}",
            )
        )
        sections.extend(
            [
                f"### `{target['logical_path']}`",
                "",
                (
                    f"- Pre directives: {target['pre_directives']}; "
                    f"post directives: {target['post_directives']}; "
                    f"directive delta: {target['directive_delta']:+d}"
                ),
                (
                    f"- Pre bytes: {target['pre_bytes']}; post bytes: "
                    f"{target['post_bytes']}; byte delta: {target['byte_delta']:+d}"
                ),
                (
                    f"- Pre lines: {target['pre_lines']}; post lines: "
                    f"{target['post_lines']}; line delta: {target['line_delta']:+d}"
                ),
            ]
        )
        claude_guidance = target.get("claude_line_guidance")
        if isinstance(claude_guidance, dict):
            sections.append(
                "- Claude line guidance: "
                f"status `{_safe_code(str(claude_guidance.get('status', 'unknown')))}`; "
                f"post lines {claude_guidance.get('post_lines', 0)}; recommended maximum "
                f"{claude_guidance.get('recommended_max_lines', 200)} lines. This is guidance, "
                "not a hard limit."
            )
        sections.extend(["", _indented(diff or "(no change)"), ""])
    markdown = "\n".join(sections).rstrip() + "\n"
    if surviving_high_confidence(markdown):
        # The model output was already scanned. This catches accidental report
        # interpolation changes before anything user-facing is persisted.
        fail(
            "report_secret_scan_failed", "A high-confidence secret shape survived report rendering"
        )
    atomic_write(md_path, markdown.encode("utf-8"))
    append_log(
        config,
        {
            "schema_version": SCHEMA_VERSION,
            "event": "plan_complete",
            "run_id": plan.run_id,
            "plan_sha256": plan.plan_sha256,
            "provider": plan.provider,
            "model": plan.model,
            "model_id": plan.model_id,
            "prompt_version": plan.prompt_version,
            "prompt_sha256": plan.prompt_sha256,
            "semantic_verification": plan.semantic_verification,
            "semantic_analysis": semantic_analysis_public,
            "consolidation_preflight": plan.consolidation_preflight,
            "parent_plan_sha256": plan.parent_plan_sha256,
            "parent_packet_sha256": plan.parent_packet_sha256,
            **decision_log_summary(
                plan.decision_request, plan.operator_decision, plan.decision_lineage
            ),
            "changed_directives": plan.changed_directive_count,
            "directives": plan.directive_count,
            "pre_directives": plan.directive_count,
            "post_directives": plan.post_directive_count,
            "escalated_directives": plan.escalated_directive_count,
            "new_rule_suggestions": plan.new_rule_suggestion_count,
            "directive_delta": plan.metrics.get("directive_delta", 0),
            "pre_bytes": plan.metrics.get("pre_bytes", 0),
            "post_bytes": plan.metrics.get("post_bytes", 0),
            "byte_delta": plan.metrics.get("byte_delta", 0),
            "pre_lines": plan.metrics.get("pre_lines", 0),
            "post_lines": plan.metrics.get("post_lines", 0),
            "line_delta": plan.metrics.get("line_delta", 0),
            "metrics": plan.metrics,
            "minimum_apply_mode": plan.minimum_apply_mode,
            "blocked_reasons": list(plan.blocked_reasons),
            "usage": plan.usage.to_dict(),
        },
    )
    return json_path, md_path


def write_plan_report(config: Config, plan: ValidatedPlan) -> tuple[Path, Path]:
    """Write a run report without racing explicit archive/report purge."""

    with exclusive_lock(config.state_root / "meditate.lock"):
        return _write_plan_report_unlocked(config, plan)
