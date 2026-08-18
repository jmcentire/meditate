"""Command-line interface for Meditate."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .config import (
    Config,
    default_config_path,
    load_config,
    with_llm_overrides,
    write_default_config,
)
from .cron import check_cron_environment, render_cron_entry
from .plan import create_plan, inspect_state, inspection_dict
from .report import append_log, write_inspection_report, write_plan_report
from .transaction import apply_run, purge_run, restore_run
from .util import SCHEMA_VERSION, MeditateError, exclusive_lock, fail


def _emit(value: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str))
        return
    for key, item in value.items():
        if isinstance(item, (dict, list, tuple)):
            rendered = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        else:
            rendered = str(item)
        print(f"{key}: {rendered}")


def _configured(args: argparse.Namespace) -> Config:
    config = load_config(args.config)
    return with_llm_overrides(
        config,
        model=getattr(args, "model", None),
        effort=getattr(args, "effort", None),
        max_input_tokens=getattr(args, "max_input_tokens", None),
        max_output_tokens=getattr(args, "max_output_tokens", None),
        max_total_input_tokens=getattr(args, "max_total_input_tokens", None),
        max_total_output_tokens=getattr(args, "max_total_output_tokens", None),
    )


def _plan_payload(config: Config, *, include_inspection_report: bool) -> dict[str, Any]:
    inspection = inspect_state(config)
    inspection_paths: tuple[Path, Path] | None = None
    if include_inspection_report:
        _report_id, json_path, md_path = write_inspection_report(config, inspection)
        inspection_paths = (json_path, md_path)
    plan = create_plan(config, inspection=inspection)
    plan_json, plan_markdown = write_plan_report(config, plan)
    changed_targets = _changed_target_count(config, plan.run_id)
    apply_command = (
        f"meditate apply {plan.run_id} --approve {plan.plan_sha256}"
        if changed_targets and not plan.blocked_reasons
        else None
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": plan.run_id,
        "plan_sha256": plan.plan_sha256,
        "model": f"{plan.provider}:{plan.model}",
        "model_id": plan.model_id,
        "prompt_version": plan.prompt_version,
        "prompt_sha256": plan.prompt_sha256,
        "semantic_verification": plan.semantic_verification,
        "changed_directives": plan.changed_directive_count,
        "escalated_directives": plan.escalated_directive_count,
        "changed_targets": changed_targets,
        "directives": plan.directive_count,
        "pre_directives": plan.directive_count,
        "post_directives": plan.post_directive_count,
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
        "plan_report_json": str(plan_json),
        "plan_report_markdown": str(plan_markdown),
        "apply_command": apply_command,
    }
    if inspection_paths:
        payload["inspection_report_json"] = str(inspection_paths[0])
        payload["inspection_report_markdown"] = str(inspection_paths[1])
    return payload


def _changed_target_count(config: Config, run_id: str) -> int:
    path = config.data_root / "runs" / run_id / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        targets = manifest["targets"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        fail("archive_corrupt", f"Cannot read target manifest for {run_id}")
    if not isinstance(targets, list):
        fail("archive_corrupt", f"Invalid target manifest for {run_id}")
    return sum(1 for target in targets if isinstance(target, dict) and target.get("changed", True))


def _run_command(args: argparse.Namespace) -> int:
    if args.command == "init":
        path = (args.config or default_config_path()).expanduser().absolute()
        write_default_config(path, force=args.force)
        _emit(
            {"schema_version": SCHEMA_VERSION, "config": str(path), "created": True},
            as_json=args.json,
        )
        return 0

    config = _configured(args)
    if args.command == "inspect":
        result = inspect_state(config)
        report_id, json_path, md_path = write_inspection_report(config, result)
        payload = inspection_dict(result, config)
        payload.update(
            {
                "report_id": report_id,
                "report_json": str(json_path),
                "report_markdown": str(md_path),
            }
        )
        _emit(payload, as_json=args.json)
        return 0

    if args.command == "plan":
        payload = _plan_payload(config, include_inspection_report=False)
        _emit(payload, as_json=args.json)
        return 0

    if args.command == "run":
        with exclusive_lock(config.state_root / "run.lock"):
            payload = _plan_payload(config, include_inspection_report=True)
        if args.apply and payload["changed_targets"]:
            if payload["blocked_reasons"]:
                fail("plan_blocked", "The generated plan is blocked and cannot be applied")
            receipt = apply_run(config, str(payload["run_id"]), mode="unattended")
            payload["apply"] = receipt
        elif args.apply:
            payload["apply"] = {"state": "not_needed", "reason": "no_target_changes"}
        else:
            payload["apply"] = {"state": "not_requested"}
        append_log(
            config,
            {
                "schema_version": SCHEMA_VERSION,
                "event": "run_complete",
                "run_id": payload["run_id"],
                "plan_sha256": payload["plan_sha256"],
                "model_id": payload["model_id"],
                "prompt_version": payload["prompt_version"],
                "prompt_sha256": payload["prompt_sha256"],
                "semantic_verification": payload["semantic_verification"],
                "changed_targets": payload["changed_targets"],
                "changed_directives": payload["changed_directives"],
                "escalated_directives": payload["escalated_directives"],
                "pre_directives": payload["pre_directives"],
                "post_directives": payload["post_directives"],
                "directive_delta": payload["directive_delta"],
                "pre_bytes": payload["pre_bytes"],
                "post_bytes": payload["post_bytes"],
                "byte_delta": payload["byte_delta"],
                "pre_lines": payload["pre_lines"],
                "post_lines": payload["post_lines"],
                "line_delta": payload["line_delta"],
                "metrics": payload["metrics"],
                "apply_state": payload["apply"]["state"],
            },
        )
        _emit(payload, as_json=args.json)
        return 0

    if args.command == "apply":
        mode = "unattended" if args.unattended else "attended"
        receipt = apply_run(
            config,
            args.run_id,
            mode=mode,
            approval_sha256=args.approve,
        )
        _emit(receipt, as_json=args.json)
        return 0

    if args.command == "restore":
        receipt = restore_run(config, args.run_id, force=args.force, recover=args.recover)
        _emit(receipt, as_json=args.json)
        return 0

    if args.command == "purge":
        purge_result = purge_run(config, args.run_id, execute=args.execute, force=args.force)
        _emit(purge_result, as_json=args.json)
        return 0

    if args.command == "cron":
        profile = None if args.no_profile else args.profile.expanduser().absolute()
        if args.check:
            cron_result = check_cron_environment(config, profile=profile)
            _emit(cron_result, as_json=args.json)
        else:
            entry = render_cron_entry(
                config,
                schedule=args.schedule,
                working_directory=args.working_directory,
                profile=profile,
                apply=args.apply,
            )
            if args.json:
                _emit({"schema_version": SCHEMA_VERSION, "cron_entry": entry}, as_json=True)
            else:
                print(entry)
        return 0

    fail("unknown_command", f"Unknown command: {args.command}")


def _base_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", type=Path, help="TOML config path")
    parent.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parent


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Exact Anthropic model ID; no fallback")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--max-total-input-tokens", type=int)
    parser.add_argument("--max-total-output-tokens", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meditate",
        description="Consolidate agent instructions with temporal evidence and recoverable writes.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = _base_parent()
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", parents=[common], help="Write a commented default config")
    init.add_argument("--force", action="store_true", help="Replace an existing config")

    commands.add_parser("inspect", parents=[common], help="Inspect locally without an LLM call")
    plan = commands.add_parser(
        "plan", parents=[common], help="Create a validated read-only proposal"
    )
    _add_model_options(plan)

    run = commands.add_parser("run", parents=[common], help="Inspect and plan; dry-run by default")
    _add_model_options(run)
    run.add_argument(
        "--apply",
        action="store_true",
        help="Request unattended apply (rejected until semantic qualification exists)",
    )

    apply = commands.add_parser("apply", parents=[common], help="Apply an archived exact plan")
    apply.add_argument("run_id")
    apply.add_argument("--approve", help="Exact plan SHA-256 for attended apply")
    apply.add_argument(
        "--unattended",
        action="store_true",
        help="Request unattended mode (currently rejected: semantic qualification required)",
    )

    restore = commands.add_parser("restore", parents=[common], help="Restore archived pre-images")
    restore.add_argument("run_id")
    restore.add_argument(
        "--force", action="store_true", help="Archive and overwrite later hand edits"
    )
    restore.add_argument(
        "--recover", action="store_true", help="Recover an interrupted transaction"
    )

    purge = commands.add_parser(
        "purge", parents=[common], help="Preview or explicitly erase a run archive"
    )
    purge.add_argument("run_id")
    purge.add_argument("--execute", action="store_true", help="Actually delete the archive")
    purge.add_argument(
        "--force", action="store_true", help="Permit erasing active restore material"
    )

    cron = commands.add_parser(
        "cron", parents=[common], help="Print or check a locked cron invocation"
    )
    cron.add_argument(
        "--check", action="store_true", help="Check paths, key resolution, and targets"
    )
    cron.add_argument("--schedule", default="0 3 * * 0", help="Five-field cron schedule")
    cron.add_argument("--working-directory", type=Path, default=Path.cwd())
    cron.add_argument("--profile", type=Path, default=Path("~/.profile"))
    cron.add_argument("--no-profile", action="store_true")
    cron.add_argument(
        "--apply",
        action="store_true",
        help="Print an unattended entry; runtime rejects it until qualification exists",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run_command(args)
    except MeditateError as exc:
        try:
            if args.command != "init":
                config = load_config(args.config)
                append_log(
                    config,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "event": "command_failed",
                        "command": args.command,
                        "error_code": exc.code,
                    },
                )
        except Exception:
            pass
        error = {"ok": False, "error": exc.code, "message": str(exc)}
        if getattr(args, "json", False):
            print(json.dumps(error, sort_keys=True), file=sys.stderr)
        else:
            print(f"meditate: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("meditate: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
