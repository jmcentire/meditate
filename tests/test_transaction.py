from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import ConfigFactory
from helpers import StubProvider, inspection, keep_all, replace_matching

import meditate.transaction as transaction
from meditate.models import Authority, EvidenceEvent
from meditate.plan import create_plan
from meditate.transaction import apply_run, purge_run, restore_run
from meditate.util import MeditateError, sha256_bytes


def correction(text: str = "New rule: commit completed work after tests.") -> EvidenceEvent:
    return EvidenceEvent(
        id="evt_transaction",
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-18T12:00:00Z",
        session_id="transaction-session",
        scope="global",
        text=text,
        source_locator="fixture:transaction",
        content_sha256=sha256_bytes(text.encode()),
    )


def replacement_plan(config_factory: ConfigFactory):
    original = "# Git\n\n- Commit only when asked.\n\n- Preserve hand edits.\n"
    config, (target,) = config_factory((original,))
    provider = StubProvider(
        replace_matching({"Commit only when asked": "- Commit completed work after tests."})
    )
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (correction(),)),
    )
    return config, target, original, plan


def test_attended_apply_requires_exact_hash_then_restore_round_trips(
    config_factory: ConfigFactory,
) -> None:
    config, target, original, plan = replacement_plan(config_factory)
    with pytest.raises(MeditateError) as missing:
        apply_run(config, plan.run_id, mode="attended")
    assert missing.value.code == "approval_required"

    receipt = apply_run(
        config,
        plan.run_id,
        mode="attended",
        approval_sha256=plan.plan_sha256,
    )
    assert receipt["state"] == "applied"
    assert "Commit completed work" in target.read_text(encoding="utf-8")
    restored = restore_run(config, plan.run_id)
    assert restored["state"] == "restored"
    assert target.read_text(encoding="utf-8") == original
    with pytest.raises(MeditateError) as consumed:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert consumed.value.code == "plan_consumed"


def test_apply_rejects_source_drift_before_consuming_plan(config_factory: ConfigFactory) -> None:
    config, target, _original, plan = replacement_plan(config_factory)
    target.write_text("# Git\n\n- A human edited this after planning.\n", encoding="utf-8")
    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert caught.value.code == "source_drift"
    state = json.loads(
        (config.data_root / "runs" / plan.run_id / "state.json").read_text(encoding="utf-8")
    )
    assert state["state"] == "planned"
    assert state["consumed"] is False


def test_apply_rejects_validator_version_drift(
    config_factory: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _target, _original, plan = replacement_plan(config_factory)
    monkeypatch.setattr(transaction, "PARSER_VERSION", "future-validator")
    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert caught.value.code == "parser_version_drift"


def test_apply_refuses_target_replaced_by_symlink(
    config_factory: ConfigFactory, tmp_path: Path
) -> None:
    config, target, _original, plan = replacement_plan(config_factory)
    referent = tmp_path / "outside.md"
    referent.write_text("outside", encoding="utf-8")
    target.unlink()
    target.symlink_to(referent)
    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert caught.value.code == "symlink_target"
    assert referent.read_text(encoding="utf-8") == "outside"


def test_post_rename_failure_is_detected_and_rolled_back(
    config_factory: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, target, original, plan = replacement_plan(config_factory)
    actual_replace = transaction._replace_target
    injected = False

    def fail_after_rename(
        path: Path,
        data: bytes,
        mode: int,
        *,
        expected_exists: bool,
        expected_sha256: str,
    ) -> None:
        nonlocal injected
        actual_replace(
            path,
            data,
            mode,
            expected_exists=expected_exists,
            expected_sha256=expected_sha256,
        )
        if not injected and b"Commit completed work" in data:
            injected = True
            raise OSError("injected post-rename failure")

    monkeypatch.setattr(transaction, "_replace_target", fail_after_rename)
    with pytest.raises(OSError, match="post-rename"):
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert target.read_text(encoding="utf-8") == original
    state = json.loads(
        (config.data_root / "runs" / plan.run_id / "state.json").read_text(encoding="utf-8")
    )
    assert state["state"] == "rolled_back"


def test_second_target_failure_rolls_back_first(
    config_factory: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    originals = ("# One\n\n- Old one.\n", "# Two\n\n- Old two.\n")
    config, paths = config_factory(originals)
    provider = StubProvider(replace_matching({"Old one": "- New one.", "Old two": "- New two."}))
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (correction("Replace both old placeholder entries."),)),
    )
    actual_replace = transaction._replace_target

    def fail_second(
        path: Path,
        data: bytes,
        mode: int,
        *,
        expected_exists: bool,
        expected_sha256: str,
    ) -> None:
        if path == paths[1] and b"New two" in data:
            raise OSError("injected second-target failure")
        actual_replace(
            path,
            data,
            mode,
            expected_exists=expected_exists,
            expected_sha256=expected_sha256,
        )

    monkeypatch.setattr(transaction, "_replace_target", fail_second)
    with pytest.raises(OSError, match="second-target"):
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert tuple(path.read_text(encoding="utf-8") for path in paths) == originals


def test_force_restore_archives_diverged_bytes_and_existence(
    config_factory: ConfigFactory,
) -> None:
    config, target, original, plan = replacement_plan(config_factory)
    apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    manual = "# Git\n\n- A later human edit.\n"
    target.write_text(manual, encoding="utf-8")
    with pytest.raises(MeditateError) as caught:
        restore_run(config, plan.run_id)
    assert caught.value.code == "restore_would_discard_changes"
    receipt = restore_run(config, plan.run_id, force=True)
    assert target.read_text(encoding="utf-8") == original
    recovery = Path(receipt["recovery_archive"])
    manifest = json.loads((recovery / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["targets"][0]["existed"] is True
    blob = recovery / manifest["targets"][0]["blob"]
    assert blob.read_text(encoding="utf-8") == manual


def test_recover_accepts_interrupted_applying_state(config_factory: ConfigFactory) -> None:
    config, target, original, plan = replacement_plan(config_factory)
    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    post = (run_dir / manifest["targets"][0]["post_blob"]).read_bytes()
    target.write_bytes(post)
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"state": "applying", "consumed": True})
    state_path.write_text(json.dumps(state), encoding="utf-8")
    receipt = restore_run(config, plan.run_id, recover=True)
    assert receipt["state"] == "restored"
    assert target.read_text(encoding="utf-8") == original


def test_noop_plan_cannot_be_counted_as_an_apply(config_factory: ConfigFactory) -> None:
    config, _paths = config_factory()
    plan = create_plan(config, provider=StubProvider(keep_all), inspection=inspection(config, ()))
    with pytest.raises(MeditateError) as caught:
        apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert caught.value.code == "no_changes"


def test_unattended_apply_needs_reviewed_evidence_and_local_policy(
    config_factory: ConfigFactory,
) -> None:
    original = "# Git\n\n- Commit only when asked.\n"
    config, (target,) = config_factory((original,))
    config = replace(
        config,
        apply=replace(
            config.apply,
            allow_unattended_apply=True,
            minimum_attended_applies=0,
        ),
    )
    reviewed = replace(correction(), unattended_eligible=True)
    provider = StubProvider(
        replace_matching(
            {"Commit only when asked": "- Commit completed work after project tests pass."}
        )
    )
    plan = create_plan(config, provider=provider, inspection=inspection(config, (reviewed,)))
    receipt = apply_run(config, plan.run_id, mode="unattended")
    assert receipt["approval"] == "unattended_policy"
    assert "Commit completed work" in target.read_text(encoding="utf-8")


def test_purge_is_preview_only_then_leaves_tombstone(config_factory: ConfigFactory) -> None:
    config, _target, _original, plan = replacement_plan(config_factory)
    preview = purge_run(config, plan.run_id)
    assert preview["executed"] is False
    run_dir = config.data_root / "runs" / plan.run_id
    assert run_dir.is_dir()
    result = purge_run(config, plan.run_id, execute=True)
    assert result["executed"] is True
    assert not run_dir.exists()
    tombstone = config.data_root / "tombstones" / f"{plan.run_id}.json"
    assert tombstone.is_file()
    with pytest.raises(MeditateError) as caught:
        restore_run(config, plan.run_id)
    assert caught.value.code == "archive_explicitly_purged"


def test_target_mode_is_preserved(config_factory: ConfigFactory) -> None:
    config, target, _original, plan = replacement_plan(config_factory)
    target.chmod(0o640)
    # The mode is part of the planning snapshot, so regenerate after changing it.
    purge_run(config, plan.run_id, execute=True)
    provider = StubProvider(
        replace_matching({"Commit only when asked": "- Commit completed work after tests."})
    )
    fresh = create_plan(config, provider=provider, inspection=inspection(config, (correction(),)))
    apply_run(config, fresh.run_id, mode="attended", approval_sha256=fresh.plan_sha256)
    assert os.stat(target).st_mode & 0o777 == 0o640
