"""Archive-backed apply, rollback, restore, and explicit erasure."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import plan as plan_module
from .config import Config
from .imports import build_import_graph
from .plan import PARSER_VERSION, SEMANTIC_VERIFICATION
from .report import append_log
from .util import (
    SCHEMA_VERSION,
    MeditateError,
    atomic_write,
    atomic_write_json,
    canonical_json_bytes,
    ensure_private_dir,
    exclusive_lock,
    fail,
    load_json,
    resolve_allowlisted,
    sha256_bytes,
    sha256_text,
    validate_run_id,
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_dir(config: Config, run_id: str) -> Path:
    validate_run_id(run_id)
    root = ensure_private_dir(config.data_root / "runs")
    candidate = root / run_id
    tombstone = config.data_root / "tombstones" / f"{run_id}.json"
    if tombstone.exists():
        fail("archive_explicitly_purged", f"Run {run_id} was explicitly purged")
    if not candidate.exists():
        fail("archive_never_existed", f"Run archive does not exist: {run_id}")
    if candidate.is_symlink() or candidate.resolve() != candidate.absolute():
        fail("unsafe_run_path", f"Run archive path is unsafe: {candidate}")
    return candidate


def _verified_artifacts(
    config: Config, run_id: str
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    run_dir = _run_dir(config, run_id)
    artifacts: list[dict[str, Any]] = []
    for name in ("plan.json", "manifest.json", "state.json"):
        path = run_dir / name
        if path.is_symlink() or not path.is_file():
            fail("archive_corrupt", f"Missing or unsafe archive artifact: {name}")
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            fail(
                "archive_corrupt",
                f"Run {run_id} contains unreadable or invalid {name}: {type(exc).__name__}",
            )
        if not isinstance(value, dict):
            fail("archive_corrupt", f"Run {run_id} contains invalid {name}")
        if raw != canonical_json_bytes(value):
            fail("archive_corrupt", f"Run {run_id} contains non-canonical {name}")
        artifacts.append(value)
    plan, manifest, state = artifacts
    if not all(isinstance(item, dict) for item in (plan, manifest, state)):
        fail("archive_corrupt", f"Run {run_id} contains invalid artifact shapes")
    if any(item.get("schema_version") != SCHEMA_VERSION for item in (plan, manifest, state)):
        fail("archive_schema", f"Run {run_id} has an unsupported schema")
    if any(item.get("run_id") != run_id for item in (plan, manifest, state)):
        fail("archive_corrupt", f"Run artifacts disagree on run ID for {run_id}")
    plan_sha = plan.get("plan_sha256")
    core = {key: value for key, value in plan.items() if key != "plan_sha256"}
    calculated = sha256_bytes(canonical_json_bytes(core))
    if not isinstance(plan_sha, str) or calculated != plan_sha:
        fail("archive_corrupt", f"Plan hash mismatch for {run_id}")
    if manifest.get("plan_sha256") != plan_sha or state.get("plan_sha256") != plan_sha:
        fail("archive_corrupt", f"Run artifacts disagree on plan hash for {run_id}")
    if plan.get("targets") != manifest.get("targets"):
        fail("archive_corrupt", f"Plan and manifest targets differ for {run_id}")
    for field in (
        "model_id",
        "prompt_version",
        "prompt_sha256",
        "semantic_verification",
        "decision_request",
        "operator_decision",
        "parent_plan_sha256",
        "parent_packet_sha256",
        "decision_lineage",
        "blocked_reasons",
        "metrics",
        "import_graph_before",
        "import_graph_after",
    ):
        if (field in plan or field in manifest) and (
            field not in plan or field not in manifest or plan[field] != manifest[field]
        ):
            fail(
                "archive_corrupt",
                f"Plan and manifest disagree on {field} for {run_id}",
            )
    if "model_id" in plan and (not isinstance(plan["model_id"], str) or not plan["model_id"]):
        fail("archive_corrupt", f"Run {run_id} has invalid model provenance")
    if "prompt_version" in plan and not isinstance(plan["prompt_version"], str):
        fail("archive_corrupt", f"Run {run_id} has invalid prompt version")
    if "prompt_sha256" in plan and (
        not isinstance(plan["prompt_sha256"], str) or len(plan["prompt_sha256"]) != 64
    ):
        fail("archive_corrupt", f"Run {run_id} has invalid prompt hash")
    if "semantic_verification" in plan and plan["semantic_verification"] != SEMANTIC_VERIFICATION:
        fail("archive_corrupt", f"Run {run_id} has invalid semantic verification state")
    blocked_reasons = plan.get("blocked_reasons")
    if not isinstance(blocked_reasons, list) or not all(
        isinstance(item, str) and item for item in blocked_reasons
    ):
        fail("archive_corrupt", f"Run {run_id} has invalid blocked reasons")
    operations = plan.get("operations")
    if not isinstance(operations, dict) or "decision_request" in operations:
        fail("archive_corrupt", f"Run {run_id} duplicates its decision request")
    lineage = plan.get("decision_lineage")
    if lineage is not None and (
        not isinstance(lineage, dict)
        or not isinstance(lineage.get("depth"), int)
        or isinstance(lineage.get("depth"), bool)
        or not isinstance(lineage.get("resolved_request_ids"), list)
        or not isinstance(lineage.get("conflict_fingerprints"), list)
    ):
        fail("archive_corrupt", f"Run {run_id} has invalid decision lineage")
    operator_decision = plan.get("operator_decision")
    if operator_decision is not None:
        if not isinstance(operator_decision, dict):
            fail("archive_corrupt", f"Run {run_id} has invalid operator decision")
        expected_fields = {
            "authority",
            "identity_attestation",
            "recorded_at",
            "parent_run_id",
            "parent_plan_sha256",
            "parent_packet_sha256",
            "request_id",
            "conflict_fingerprint",
            "collision_scope",
            "response_kind",
            "choice_key",
            "response_text",
            "selected_option",
            "response_sha256",
        }
        if set(operator_decision) != expected_fields:
            fail("archive_corrupt", f"Run {run_id} has invalid operator decision fields")
        response_kind = operator_decision.get("response_kind")
        choice_key = operator_decision.get("choice_key")
        response_text = operator_decision.get("response_text")
        response_sha256 = operator_decision.get("response_sha256")
        if (
            response_kind not in {"choice", "custom"}
            or not isinstance(response_text, str)
            or not isinstance(response_sha256, str)
            or sha256_text(response_text) != response_sha256
            or (response_kind == "choice" and choice_key not in {"a", "b", "c"})
            or (response_kind == "custom" and choice_key is not None)
        ):
            fail("archive_corrupt", f"Run {run_id} has invalid operator response binding")
        collision_scope = operator_decision.get("collision_scope")
        if (
            not isinstance(collision_scope, dict)
            or set(collision_scope) != {"subject_a", "subject_b", "directive_ids", "evidence_ids"}
            or not all(
                isinstance(collision_scope.get(field), str)
                and bool(str(collision_scope[field]).strip())
                for field in ("subject_a", "subject_b")
            )
            or not all(
                isinstance(collision_scope.get(field), list)
                and bool(collision_scope[field])
                and all(isinstance(item, str) and item for item in collision_scope[field])
                for field in ("directive_ids", "evidence_ids")
            )
        ):
            fail("archive_corrupt", f"Run {run_id} has invalid operator collision scope")
        selected_option = operator_decision.get("selected_option")
        if (
            response_kind == "choice"
            and (
                not isinstance(selected_option, dict)
                or selected_option.get("key") != choice_key
                or response_text != selected_option.get("label")
                or not isinstance(selected_option.get("evidence_ids"), list)
                or not set(selected_option["evidence_ids"]).issubset(
                    set(collision_scope["evidence_ids"])
                )
            )
        ) or (response_kind == "custom" and selected_option is not None):
            fail("archive_corrupt", f"Run {run_id} has invalid archived option binding")
    for field in ("import_graph_before", "import_graph_after"):
        snapshot = plan.get(field)
        if snapshot is None:
            continue
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("digest"), str):
            fail("archive_corrupt", f"Run {run_id} has invalid {field}")
        graph_core = {key: value for key, value in snapshot.items() if key != "digest"}
        if sha256_bytes(canonical_json_bytes(graph_core)) != snapshot["digest"]:
            fail("archive_corrupt", f"Run {run_id} has invalid {field} digest")
    evidence_sha = plan.get("evidence_sha256")
    if not isinstance(evidence_sha, str) or manifest.get("packet_sha256") != evidence_sha:
        fail("archive_corrupt", f"Run artifacts disagree on evidence hash for {run_id}")
    _verify_blob(run_dir, "evidence.json", evidence_sha)
    return run_dir, plan, manifest, state


def verified_run_artifacts(
    config: Config, run_id: str
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load an immutable run after all archive cross-checks."""

    return _verified_artifacts(config, run_id)


_DECISION_RESOLUTION_FIELDS = frozenset(
    {
        "parent_run_id",
        "parent_plan_sha256",
        "request_id",
        "conflict_fingerprint",
        "successor_run_id",
        "successor_plan_sha256",
        "response_sha256",
    }
)


def validate_decision_resolution_marker(value: Any) -> dict[str, str]:
    """Validate the non-sensitive replay marker retained after successor purge."""

    if not isinstance(value, dict) or set(value) != _DECISION_RESOLUTION_FIELDS:
        fail("archive_corrupt", "A decision resolution marker is malformed")
    marker = {field: value.get(field) for field in _DECISION_RESOLUTION_FIELDS}
    if not all(isinstance(item, str) and item for item in marker.values()) or any(
        len(str(marker[field])) != 64
        for field in (
            "parent_plan_sha256",
            "conflict_fingerprint",
            "successor_plan_sha256",
            "response_sha256",
        )
    ):
        fail("archive_corrupt", "A decision resolution marker has invalid identifiers")
    try:
        validate_run_id(str(marker["parent_run_id"]))
        validate_run_id(str(marker["successor_run_id"]))
        request_id = str(marker["request_id"])
        if not request_id.startswith("decision-") or len(request_id) != 25:
            raise ValueError("invalid request ID")
        int(request_id.removeprefix("decision-"), 16)
        for field in (
            "parent_plan_sha256",
            "conflict_fingerprint",
            "successor_plan_sha256",
            "response_sha256",
        ):
            int(str(marker[field]), 16)
    except (ValueError, MeditateError):
        fail("archive_corrupt", "A decision resolution marker has invalid identifiers")
    return {field: str(marker[field]) for field in _DECISION_RESOLUTION_FIELDS}


def _decision_resolution_marker(plan: dict[str, Any], run_id: str) -> dict[str, str] | None:
    operator_decision = plan.get("operator_decision")
    if operator_decision is None:
        return None
    if not isinstance(operator_decision, dict):
        fail("archive_corrupt", f"Run {run_id} has an invalid operator decision")
    return validate_decision_resolution_marker(
        {
            "parent_run_id": operator_decision.get("parent_run_id"),
            "parent_plan_sha256": plan.get("parent_plan_sha256"),
            "request_id": operator_decision.get("request_id"),
            "conflict_fingerprint": operator_decision.get("conflict_fingerprint"),
            "successor_run_id": run_id,
            "successor_plan_sha256": plan.get("plan_sha256"),
            "response_sha256": operator_decision.get("response_sha256"),
        }
    )


def _purge_run_reports(config: Config, run_id: str, *, execute: bool) -> list[Path]:
    """Resolve or unlink exact run reports through a non-followed directory fd."""

    reports_root = config.state_root / "reports"
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(reports_root, flags)
    except FileNotFoundError:
        return []
    except OSError as exc:
        fail("unsafe_report_path", f"Cannot safely open the configured reports root: {exc}")
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            fail("unsafe_report_path", "The configured reports root is not a directory")
        paths: list[Path] = []
        names: list[str] = []
        for suffix in (".json", ".md"):
            name = f"{run_id}{suffix}"
            try:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                fail("unsafe_report_path", f"Cannot inspect run report {name}: {exc}")
            if not stat.S_ISREG(info.st_mode):
                fail("unsafe_report_path", f"Refusing unsafe run report: {name}")
            paths.append(reports_root / name)
            names.append(name)
        if execute:
            for name in names:
                try:
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        fail("unsafe_report_path", f"Refusing unsafe run report: {name}")
                    os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:
                    fail("purge_report_failed", f"Run report changed before erasure: {name}")
                except OSError as exc:
                    fail("purge_report_failed", f"Could not erase run report {name}: {exc}")
        return paths
    finally:
        os.close(descriptor)


def _fd_hash(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _snapshot(path: Path) -> tuple[bool, str, int, tuple[int, int, int]]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False, sha256_bytes(b""), 0o644, (0, 0, 0)
    if stat.S_ISLNK(info.st_mode):
        fail("symlink_target", f"Refusing symlinked target: {path}")
    if not stat.S_ISREG(info.st_mode):
        fail("non_regular_target", f"Target is not a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            fail("non_regular_target", f"Target changed type while opening: {path}")
        digest = _fd_hash(descriptor)
        fingerprint = (opened.st_ino, opened.st_size, opened.st_mtime_ns)
        return True, digest, stat.S_IMODE(opened.st_mode), fingerprint
    finally:
        os.close(descriptor)


def _verify_parent(path: Path) -> Path:
    parent = path.parent.absolute()
    try:
        resolved = parent.resolve(strict=True)
    except FileNotFoundError:
        fail("missing_target_parent", f"Target parent does not exist: {parent}")
    if resolved != parent or parent.is_symlink() or not parent.is_dir():
        fail(
            "unsafe_target_parent",
            f"Target parent contains a symlink or is not a directory: {parent}",
        )
    return parent


def _replace_target(
    path: Path,
    data: bytes,
    mode: int,
    *,
    expected_exists: bool,
    expected_sha256: str,
) -> None:
    if mode & ~0o777:
        fail("unsafe_target_mode", f"Refusing special permission bits for target: {path}")
    parent = _verify_parent(path)
    exists, digest, _current_mode, fingerprint = _snapshot(path)
    if exists != expected_exists or digest != expected_sha256:
        fail("source_drift", f"Target changed before replacement: {path}")
    temp_path = parent / f".meditate-{secrets.token_hex(12)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temp_path, flags, mode)
    try:
        os.fchmod(descriptor, mode)
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                fail("short_write", f"Could not complete temporary write for {path}")
            written += count
        os.fsync(descriptor)
        temp_info = os.fstat(descriptor)
        if not stat.S_ISREG(temp_info.st_mode):
            fail("unsafe_tempfile", f"Temporary path is not regular: {temp_path}")
    finally:
        os.close(descriptor)
    try:
        # Narrow the editor race: verify the same inode/size/mtime immediately
        # before the atomic rename. Non-cooperating editors cannot be fully locked.
        re_exists, re_digest, _mode, re_fingerprint = _snapshot(path)
        if (
            re_exists != expected_exists
            or re_digest != expected_sha256
            or re_fingerprint != fingerprint
        ):
            fail("source_drift", f"Target changed during replacement: {path}")
        os.replace(temp_path, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def _unlink_target(path: Path, *, expected_sha256: str) -> None:
    parent = _verify_parent(path)
    exists, digest, _mode, _fingerprint = _snapshot(path)
    if not exists or digest != expected_sha256:
        fail("source_drift", f"Target changed before removal: {path}")
    path.unlink()
    directory_fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _transition(run_dir: Path, state: dict[str, Any], name: str, **extra: Any) -> dict[str, Any]:
    updated = dict(state, state=name, updated_at=_now(), **extra)
    atomic_write_json(run_dir / "state.json", updated)
    return updated


def _verify_blob(run_dir: Path, relative: str, expected: str) -> bytes:
    relative_path = Path(relative)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        fail("archive_corrupt", f"Unsafe archive-relative path: {relative}")
    path = run_dir / relative_path
    try:
        resolved = path.resolve(strict=True)
        archive_root = run_dir.resolve(strict=True)
    except OSError:
        fail("archive_corrupt", f"Missing archive blob: {relative}")
    if not resolved.is_relative_to(archive_root) or path.is_symlink() or not resolved.is_file():
        fail("archive_corrupt", f"Missing or unsafe archive blob: {relative}")
    data = resolved.read_bytes()
    if sha256_bytes(data) != expected:
        fail("archive_corrupt", f"Archive blob hash mismatch: {relative}")
    return data


def _free_space_preflight(config: Config, targets: list[dict[str, Any]], run_dir: Path) -> None:
    required = config.safety.minimum_free_bytes
    required += sum((run_dir / target["post_blob"]).stat().st_size for target in targets) * 3
    roots = {run_dir, *(Path(target["path"]).parent for target in targets)}
    for root in roots:
        free = shutil.disk_usage(root).free
        if free < required:
            fail(
                "insufficient_disk_space",
                f"Need at least {required} free bytes on {root}, found {free}",
            )


def _ledger(config: Config) -> dict[str, Any]:
    path = config.data_root / "ledger.json"
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "attended_applies": 0, "events": []}
    value = load_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        fail("ledger_corrupt", f"Invalid Meditate ledger: {path}")
    return value


def _record_ledger(config: Config, run_id: str, mode: str) -> None:
    ensure_private_dir(config.data_root)
    ledger = _ledger(config)
    events = list(ledger.get("events", []))
    events.append({"run_id": run_id, "mode": mode, "at": _now()})
    attended = int(ledger.get("attended_applies", 0)) + int(mode == "attended")
    atomic_write_json(
        config.data_root / "ledger.json",
        {"schema_version": SCHEMA_VERSION, "attended_applies": attended, "events": events[-1000:]},
    )


def apply_run(
    config: Config,
    run_id: str,
    *,
    mode: str,
    approval_sha256: str | None = None,
) -> dict[str, Any]:
    if mode not in {"attended", "unattended"}:
        fail("invalid_apply_mode", f"Invalid apply mode: {mode}")
    with exclusive_lock(config.state_root / "meditate.lock"):
        run_dir, plan, manifest, state = _verified_artifacts(config, run_id)
        if state.get("state") != "planned" or state.get("consumed"):
            fail("plan_consumed", f"Run {run_id} is not an unused planned run")
        if mode == "unattended":
            fail(
                "semantic_verification_required",
                "Unattended apply requires an owner-defined behavioral qualification suite",
            )
        if (
            plan.get("parser_version") != PARSER_VERSION
            or manifest.get("parser_version") != PARSER_VERSION
        ):
            fail(
                "parser_version_drift",
                "Parser version differs from the version that created the plan",
            )
        if plan.get("prompt_version") != plan_module.PLAN_PROMPT_VERSION:
            fail(
                "prompt_version_drift",
                "Plan prompt version differs from the local planner; generate a new plan",
            )
        if plan.get("prompt_sha256") != sha256_text(plan_module.SYSTEM_PROMPT):
            fail(
                "prompt_sha256_drift",
                "Plan prompt hash differs from the local planner; generate a new plan",
            )
        if plan.get("config_sha256") != config.hash or manifest.get("config_sha256") != config.hash:
            fail("config_drift", "Configuration changed after plan generation; generate a new plan")
        blocked = plan.get("blocked_reasons", [])
        if "decision_required" in blocked:
            fail(
                "decision_required",
                "The plan has a pending operator authority decision and cannot be applied",
            )
        if "compression_regression" in blocked:
            fail(
                "compression_regression",
                "Aggregate post-plan bytes exceed pre-plan bytes; generate a smaller plan",
            )
        if blocked:
            fail("plan_blocked", f"Plan is blocked: {', '.join(str(item) for item in blocked)}")
        plan_sha = str(plan["plan_sha256"])
        if mode == "attended" and approval_sha256 != plan_sha:
            fail("approval_required", f"Attended apply requires --approve {plan_sha}")

        expected_before_graph = plan.get("import_graph_before")
        if not isinstance(expected_before_graph, dict):
            fail("import_graph_drift", "Plan does not bind a Claude import graph")
        observed_before_graph = build_import_graph(config).public_dict()
        if observed_before_graph != expected_before_graph:
            fail(
                "import_graph_drift",
                "Claude import graph changed after planning; generate a new plan",
            )

        targets_raw = manifest.get("targets")
        targets = (
            [item for item in targets_raw if item.get("changed", True)]
            if isinstance(targets_raw, list) and all(isinstance(item, dict) for item in targets_raw)
            else None
        )
        if targets is None:
            fail("archive_corrupt", "Manifest targets are invalid")
        if not targets:
            fail("no_changes", f"Run {run_id} has no target changes to apply")
        _free_space_preflight(config, targets, run_dir)
        allowed = config.allowed_targets
        prepared: list[tuple[dict[str, Any], Path, bytes, bytes]] = []
        for target in targets:
            path = resolve_allowlisted(
                Path(target["path"]), allowed, allow_missing=not bool(target["existed"])
            )
            pre = _verify_blob(run_dir, str(target["pre_blob"]), str(target["pre_sha256"]))
            post = _verify_blob(run_dir, str(target["post_blob"]), str(target["post_sha256"]))
            exists, digest, _mode, _fingerprint = _snapshot(path)
            if exists != bool(target["existed"]) or digest != target["pre_sha256"]:
                fail("source_drift", f"Target changed after planning: {path}")
            prepared.append((target, path, pre, post))

        emergency = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "state": "preallocated",
            "recovery_command": f"meditate restore {run_id} --recover",
            "targets": [
                {
                    "path": target["path"],
                    "pre_sha256": target["pre_sha256"],
                    "post_sha256": target["post_sha256"],
                    "pre_blob": target["pre_blob"],
                }
                for target, _path, _pre, _post in prepared
            ],
        }
        atomic_write_json(run_dir / "emergency-recovery.json", emergency)
        state = _transition(run_dir, state, "applying", consumed=True, mode=mode, index=0)
        try:
            for index, (target, path, _pre, post) in enumerate(prepared, start=1):
                state = _transition(run_dir, state, "applying", index=index, total=len(prepared))
                _replace_target(
                    path,
                    post,
                    int(target["mode"]),
                    expected_exists=bool(target["existed"]),
                    expected_sha256=str(target["pre_sha256"]),
                )
            expected_after_graph = plan.get("import_graph_after")
            if not isinstance(expected_after_graph, dict):
                fail("import_graph_drift", "Plan does not bind a post-apply import graph")
            observed_after_graph = build_import_graph(config).public_dict()
            if observed_after_graph != expected_after_graph:
                fail(
                    "import_graph_drift",
                    "Claude import graph did not match the validated post-plan graph",
                )
        except Exception as apply_error:
            state = _transition(
                run_dir,
                state,
                "rolling_back",
                apply_error=f"{type(apply_error).__name__}:{getattr(apply_error, 'code', '')}",
                reverted=0,
            )
            rollback_errors: list[str] = []
            reverted = 0
            for target, path, pre, _post in reversed(prepared):
                try:
                    exists, digest, _mode, _fingerprint = _snapshot(path)
                    if exists == bool(target["existed"]) and digest == target["pre_sha256"]:
                        continue
                    if not exists or digest != target["post_sha256"]:
                        fail(
                            "rollback_source_drift",
                            f"Target is neither pre- nor post-image: {path}",
                        )
                    if bool(target["existed"]):
                        _replace_target(
                            path,
                            pre,
                            int(target["mode"]),
                            expected_exists=True,
                            expected_sha256=str(target["post_sha256"]),
                        )
                    else:
                        _unlink_target(path, expected_sha256=str(target["post_sha256"]))
                    reverted += 1
                    state = _transition(run_dir, state, "rolling_back", reverted=reverted)
                except Exception as rollback_error:
                    error_code = getattr(rollback_error, "code", "")
                    rollback_errors.append(f"{path}:{type(rollback_error).__name__}:{error_code}")
            if rollback_errors:
                receipt = dict(
                    emergency,
                    state="recovery_required",
                    rollback_errors=rollback_errors,
                    reverted=reverted,
                    observed=[
                        {"path": str(path), "sha256": _snapshot(path)[1]}
                        for _target, path, _pre, _post in prepared
                    ],
                )
                with contextlib.suppress(Exception):
                    atomic_write_json(run_dir / "recovery-required.json", receipt)
                    _transition(
                        run_dir, state, "recovery_required", rollback_errors=rollback_errors
                    )
                fail(
                    "rollback_failed",
                    f"Rollback failed. Run `meditate restore {run_id} --recover`; receipt: "
                    f"{run_dir / 'recovery-required.json'}",
                )
            _transition(run_dir, state, "rolled_back", reverted=reverted)
            raise

        receipt = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "state": "applied",
            "plan_sha256": plan_sha,
            "mode": mode,
            "approval": "plan_sha256" if mode == "attended" else "unattended_policy",
            "minimum_apply_mode": plan.get("minimum_apply_mode"),
            "model_id": plan.get("model_id"),
            "prompt_version": plan.get("prompt_version"),
            "prompt_sha256": plan.get("prompt_sha256"),
            "semantic_verification": plan.get("semantic_verification"),
            "metrics": plan.get("metrics"),
            "targets": [
                {"path": target["logical_path"], "post_sha256": target["post_sha256"]}
                for target in targets
            ],
            "at": _now(),
        }
        try:
            atomic_write_json(run_dir / "apply-receipt.json", receipt)
            state = _transition(run_dir, state, "applied", applied_at=_now(), mode=mode)
        except Exception as finalization_error:
            with contextlib.suppress(Exception):
                _transition(
                    run_dir,
                    state,
                    "recovery_required",
                    finalization_error=type(finalization_error).__name__,
                )
            fail(
                "apply_finalization_failed",
                "Targets changed but finalization failed. "
                f"Run `meditate restore {run_id} --recover`",
            )
        warnings: list[str] = []
        try:
            _record_ledger(config, run_id, mode)
        except Exception:
            warnings.append("ledger_not_updated")
        try:
            append_log(config, {"event": "apply_complete", **receipt, "warnings": warnings})
        except Exception:
            warnings.append("summary_log_not_updated")
        if warnings:
            receipt["warnings"] = warnings
        return receipt


def _archive_diverged(
    config: Config, run_id: str, diverged: list[tuple[Path, bytes, bool]]
) -> Path:
    recovery_root = ensure_private_dir(config.data_root / "recovery")
    recovery_dir = ensure_private_dir(recovery_root / f"{run_id}-{secrets.token_hex(4)}")
    entries: list[dict[str, Any]] = []
    for path, data, existed in diverged:
        digest = sha256_bytes(data)
        blob = recovery_dir / digest
        atomic_write(blob, data)
        if sha256_bytes(blob.read_bytes()) != digest:
            fail("recovery_archive_failed", f"Could not verify diverged-state archive for {path}")
        entries.append({"path": str(path), "sha256": digest, "blob": digest, "existed": existed})
    atomic_write_json(
        recovery_dir / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "source_run_id": run_id,
            "targets": entries,
            "at": _now(),
        },
    )
    return recovery_dir


def restore_run(
    config: Config, run_id: str, *, force: bool = False, recover: bool = False
) -> dict[str, Any]:
    with exclusive_lock(config.state_root / "meditate.lock"):
        run_dir, plan, manifest, state = _verified_artifacts(config, run_id)
        current_state = state.get("state")
        allowed_states = (
            {"applying", "recovery_required", "rolling_back"} if recover else {"applied"}
        )
        if current_state not in allowed_states:
            fail(
                "restore_state",
                f"Run {run_id} is in state {current_state!r}; "
                f"expected one of {sorted(allowed_states)}",
            )
        targets = [item for item in manifest["targets"] if item.get("changed", True)]
        prepared: list[tuple[dict[str, Any], Path, bytes, bool, str]] = []
        diverged: list[tuple[Path, bytes, bool]] = []
        for target in targets:
            path = Path(target["path"]).absolute()
            if path.is_symlink():
                fail("symlink_target", f"Refusing symlinked restore target: {path}")
            pre = _verify_blob(run_dir, target["pre_blob"], target["pre_sha256"])
            exists, digest, _mode, _fingerprint = _snapshot(path)
            known = digest in {target["pre_sha256"], target["post_sha256"]}
            if recover and known:
                pass
            elif not exists or digest != target["post_sha256"]:
                if not force:
                    fail(
                        "restore_would_discard_changes",
                        f"Live target diverged from applied run: {path}; "
                        "rerun with --force after review",
                    )
                live = path.read_bytes() if exists else b""
                diverged.append((path, live, exists))
            prepared.append((target, path, pre, exists, digest))
        recovery_dir = _archive_diverged(config, run_id, diverged) if diverged else None
        state = _transition(run_dir, state, "rolling_back", restore=True, recovered=0)
        restored = 0
        for target, path, pre, exists, digest in prepared:
            if digest == target["pre_sha256"] and exists == bool(target["existed"]):
                restored += 1
                continue
            if bool(target["existed"]):
                _replace_target(
                    path,
                    pre,
                    int(target["mode"]),
                    expected_exists=exists,
                    expected_sha256=digest,
                )
            elif exists:
                _unlink_target(path, expected_sha256=digest)
            restored += 1
            state = _transition(run_dir, state, "rolling_back", restore=True, recovered=restored)
        state = _transition(run_dir, state, "restored", restored_at=_now(), recovered=restored)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "state": "restored",
            "targets": restored,
            "forced": force,
            "recovery_archive": str(recovery_dir) if recovery_dir else None,
            "at": _now(),
        }
        atomic_write_json(run_dir / "restore-receipt.json", receipt)
        append_log(config, {"event": "restore_complete", **receipt})
        return receipt


def purge_run(
    config: Config, run_id: str, *, execute: bool = False, force: bool = False
) -> dict[str, Any]:
    with exclusive_lock(config.state_root / "meditate.lock"):
        run_dir, plan, _manifest, state = _verified_artifacts(config, run_id)
        current = str(state.get("state"))
        if current in {"applied", "applying", "rolling_back", "recovery_required"} and not force:
            fail(
                "purge_requires_force",
                f"Purging run {run_id} in state {current} destroys restore ability",
            )
        decision_resolution = _decision_resolution_marker(plan, run_id)
        report_paths = _purge_run_reports(config, run_id, execute=execute)
        result = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "state": current,
            "would_delete": str(run_dir),
            "executed": execute,
            "decision_resolution": decision_resolution,
            "report_files": [str(path) for path in report_paths],
        }
        if not execute:
            return result
        tombstones = ensure_private_dir(config.data_root / "tombstones")
        tombstone = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "purged_at": _now(),
            "previous_state": current,
            "restore_possible": False,
            "decision_resolution": decision_resolution,
        }
        atomic_write_json(tombstones / f"{run_id}.json", tombstone)
        shutil.rmtree(run_dir)
        with contextlib.suppress(Exception):
            append_log(
                config,
                {
                    "schema_version": SCHEMA_VERSION,
                    "event": "run_purged",
                    "run_id": run_id,
                    "previous_state": current,
                    "decision_resolution": decision_resolution,
                    "report_files_deleted": len(report_paths),
                },
            )
    return result
