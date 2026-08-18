"""Redaction-safe JSON/Markdown reports and append-only summary logging."""

from __future__ import annotations

import difflib
import fcntl
import html
import json
import os
from pathlib import Path
from typing import Any

from .config import Config
from .models import InspectionResult, ValidatedPlan
from .plan import inspection_dict
from .redact import surviving_high_confidence
from .util import (
    SCHEMA_VERSION,
    atomic_write,
    atomic_write_json,
    ensure_private_dir,
    fail,
    new_run_id,
)


def _reports_root(config: Config) -> Path:
    return ensure_private_dir(config.state_root / "reports")


def _safe_markdown(value: str) -> str:
    return html.escape(value, quote=False).replace("\x00", "�")


def _indented(value: str) -> str:
    return "\n".join(f"    {line}" for line in _safe_markdown(value).splitlines())


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
        },
    )
    return report_id, json_path, md_path


def write_plan_report(config: Config, plan: ValidatedPlan) -> tuple[Path, Path]:
    root = _reports_root(config)
    json_path = root / f"{plan.run_id}.json"
    md_path = root / f"{plan.run_id}.md"
    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": plan.run_id,
        "plan_sha256": plan.plan_sha256,
        "provider": plan.provider,
        "model": plan.model,
        "minimum_apply_mode": plan.minimum_apply_mode,
        "blocked_reasons": list(plan.blocked_reasons),
        "directives": plan.directive_count,
        "changed_directives": plan.changed_directive_count,
        "usage": plan.usage.to_dict(),
        "summary": plan.raw_plan.get("summary", ""),
        "unresolved_conflicts": plan.raw_plan.get("unresolved_conflicts", []),
        "changes": [
            {
                "action": item["action"],
                "source_ids": item["source_ids"],
                "destination_target": item["destination_target"],
                "reason": item["reason"],
                "minimum_apply_mode": item["minimum_apply_mode"],
                "evidence_ids": [citation["id"] for citation in item["evidence"]],
                "baseline_support": item.get("baseline_support", []),
            }
            for item in plan.raw_plan.get("changes", [])
        ],
    }
    atomic_write_json(json_path, payload)

    sections = [
        "# Meditate proposal",
        "",
        f"- Run: `{plan.run_id}`",
        f"- Plan SHA-256: `{plan.plan_sha256}`",
        f"- Model: `{plan.provider}:{plan.model}`",
        f"- Changed directives: {plan.changed_directive_count} of {plan.directive_count}",
        f"- Minimum apply mode: `{plan.minimum_apply_mode}`",
        f"- Blocked: {', '.join(plan.blocked_reasons) if plan.blocked_reasons else 'no'}",
        (
            f"- Tokens: {plan.usage.actual_input_tokens} input / "
            f"{plan.usage.actual_output_tokens} output"
        ),
        "",
        "## Summary",
        "",
        _safe_markdown(str(plan.raw_plan.get("summary", ""))),
    ]
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
                f"- Destination: `{_safe_markdown(change['destination_target'])}`",
                f"- Apply mode: `{change['minimum_apply_mode']}`",
                f"- Reason: {_safe_markdown(change['reason'])}",
                "- Evidence:",
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
            [f"### `{target['logical_path']}`", "", _indented(diff or "(no change)"), ""]
        )
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
            "changed_directives": plan.changed_directive_count,
            "directives": plan.directive_count,
            "minimum_apply_mode": plan.minimum_apply_mode,
            "blocked_reasons": list(plan.blocked_reasons),
            "usage": plan.usage.to_dict(),
        },
    )
    return json_path, md_path
