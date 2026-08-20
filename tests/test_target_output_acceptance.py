from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import ConfigFactory
from helpers import StubProvider, keep_all, replace_matching

from meditate.cli import build_parser
from meditate.config import with_archived_target_selection, with_target_overrides
from meditate.models import Authority, EvidenceEvent
from meditate.plan import create_plan, inspect_state
from meditate.transaction import apply_run, restore_run
from meditate.util import MeditateError, sha256_bytes


def _correction(text: str) -> EvidenceEvent:
    return EvidenceEvent(
        id="evt_target_output",
        source_kind="claude_history_user",
        authority=Authority.REPEATED_USER_PREFERENCE,
        timestamp="2026-08-19T12:00:00Z",
        session_id="target-output-session",
        scope="global",
        text=text,
        source_locator="fixture:target-output",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def test_cli_accepts_ordered_repeatable_targets_and_optional_output() -> None:
    args = build_parser().parse_args(
        [
            "run",
            "--target",
            "first/SKILL.md",
            "--target",
            "second/CLAUDE.md",
            "--output",
            "compiled/AGENTS.md",
        ]
    )
    assert args.targets == [Path("first/SKILL.md"), Path("second/CLAUDE.md")]
    assert args.output == Path("compiled/AGENTS.md")


def test_target_override_rejects_output_without_inputs_and_duplicate_inputs(
    config_factory: ConfigFactory,
) -> None:
    config, (target,) = config_factory()
    with pytest.raises(MeditateError) as missing:
        with_target_overrides(config, output=target)
    assert missing.value.code == "output_requires_targets"

    with pytest.raises(MeditateError) as duplicate:
        with_target_overrides(config, targets=(target, target))
    assert duplicate.value.code == "duplicate_target"


def test_archived_config_selection_discards_unrelated_runtime_overrides(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, _targets = config_factory()
    unrelated = with_target_overrides(
        config,
        targets=(tmp_path / "other.md",),
    )

    assert with_archived_target_selection(unrelated, config.target_selection) == config


def test_same_physical_input_cannot_be_selected_twice(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, (target,) = config_factory()
    alias = tmp_path / "hardlink.md"
    alias.hardlink_to(target)
    effective = with_target_overrides(config, targets=(target, alias))

    with pytest.raises(MeditateError) as caught:
        inspect_state(effective)
    assert caught.value.code == "duplicate_target"


def test_arbitrary_skill_target_changes_in_place_preserves_frontmatter_and_restores(
    config_factory: ConfigFactory,
) -> None:
    original = (
        "---\n"
        "name: concise-review\n"
        "description: Résumé review — without losing exact paths.\n"
        "---\n\n"
        "# Review\n\n"
        "- SHOULD write vague summaries.\n"
    )
    config, (skill,) = config_factory((original,), target_names=("SKILL.md",))
    base_config = config
    effective = with_target_overrides(config, targets=(skill,))
    inspected = inspect_state(effective)
    provider = StubProvider(
        replace_matching(
            {"SHOULD write vague summaries": "SHOULD write concrete summaries with exact paths"}
        )
    )
    event = _correction("New rule: write concrete summaries with exact paths.")
    inspected = replace(
        inspected,
        events=(event,),
        selected_events=(event,),
    )
    plan = create_plan(effective, provider=provider, inspection=inspected)
    receipt = apply_run(
        base_config,
        plan.run_id,
        mode="attended",
        approval_sha256=plan.plan_sha256,
    )

    changed = skill.read_text(encoding="utf-8")
    assert changed.startswith(
        "---\nname: concise-review\ndescription: Résumé review — without losing exact paths.\n---"
    )
    assert "SHOULD write concrete summaries with exact paths." in changed
    assert receipt["backup_archive"].endswith(plan.run_id)
    assert receipt["backups"][0]["pre_sha256"] == sha256_bytes(original.encode("utf-8"))

    restore_run(base_config, plan.run_id)
    assert skill.read_bytes() == original.encode("utf-8")


def test_multiple_targets_change_in_place_with_independent_exact_backups(
    config_factory: ConfigFactory,
) -> None:
    originals = (
        "# Review\n\n- SHOULD write vague summaries.\n",
        "# Review\n\n- SHOULD write vague summaries.\n",
    )
    config, targets = config_factory(
        originals,
        target_names=("CLAUDE.md", "SKILL.md"),
    )
    base_config = config
    effective = with_target_overrides(config, targets=targets)
    event = _correction("New rule: write concrete summaries with exact paths.")
    inspected = inspect_state(effective)
    inspected = replace(inspected, events=(event,), selected_events=(event,))
    plan = create_plan(
        effective,
        provider=StubProvider(
            replace_matching(
                {"SHOULD write vague summaries": "SHOULD write concrete summaries with exact paths"}
            )
        ),
        inspection=inspected,
    )
    receipt = apply_run(
        base_config,
        plan.run_id,
        mode="attended",
        approval_sha256=plan.plan_sha256,
    )

    assert [item["path"] for item in receipt["targets"]] == [str(path) for path in targets]
    assert len(receipt["backups"]) == 2
    assert all("concrete summaries" in path.read_text(encoding="utf-8") for path in targets)
    restore_run(base_config, plan.run_id)
    assert tuple(path.read_text(encoding="utf-8") for path in targets) == originals


def test_distinct_output_combines_bodies_preserves_primary_envelope_and_restores_output(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    primary = (
        "---\nname: primary-skill\ndescription: Primary identity.\n---\n\n"
        "# Primary\n\n- SHOULD preserve primary behavior.\n"
    )
    secondary = (
        "---\nname: secondary-skill\ndescription: Secondary identity.\n---\n\n"
        "# Secondary\n\n- SHOULD preserve secondary behavior.\n"
    )
    config, inputs = config_factory(
        (primary, secondary), target_names=("one-SKILL.md", "two-SKILL.md")
    )
    output = tmp_path / "compiled" / "SKILL.md"
    output.parent.mkdir()
    legacy = b"legacy output that is not semantic input\n"
    output.write_bytes(legacy)
    effective = with_target_overrides(config, targets=inputs, output=output)
    inspected = inspect_state(effective)
    assert inspected.targets[0].frontmatter_source == str(inputs[0])
    assert inspected.targets[0].secondary_frontmatter_sources == (str(inputs[1]),)
    assert any(item.startswith("secondary_frontmatter_not_emitted:") for item in inspected.warnings)
    assert "cli_target_selection_is_ephemeral" in inspected.warnings
    assert {directive.source_path for directive in inspected.targets[0].directives} == {
        str(inputs[0]),
        str(inputs[1]),
    }

    provider = StubProvider(keep_all)
    plan = create_plan(effective, provider=provider, inspection=inspected)
    apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)

    compiled = output.read_text(encoding="utf-8")
    assert compiled.startswith("---\nname: primary-skill\n")
    assert "name: secondary-skill" not in compiled
    assert "preserve primary behavior" in compiled
    assert "preserve secondary behavior" in compiled
    assert inputs[0].read_text(encoding="utf-8") == primary
    assert inputs[1].read_text(encoding="utf-8") == secondary
    assert "legacy output" not in json.dumps(provider.last_packet)
    assert {
        directive["source_path"]
        for target in provider.last_packet["targets"]
        for directive in target["directives"]
    } == {str(inputs[0]), str(inputs[1])}

    restore_run(config, plan.run_id)
    assert output.read_bytes() == legacy


def test_output_may_duplicate_input_and_restores_only_overwritten_input(
    config_factory: ConfigFactory,
) -> None:
    agents_original = "# Agent defaults\n\n- SHOULD preserve named handoffs.\n"
    claude_original = "# Claude defaults\n\n- SHOULD inspect loaded instructions.\n"
    config, (agents, claude) = config_factory(
        (agents_original, claude_original),
        target_names=("AGENTS.md", "CLAUDE.md"),
    )
    effective = with_target_overrides(
        config,
        targets=(agents, claude),
        output=agents,
    )
    inspected = inspect_state(effective)
    assert f"output_overwrites_input:{agents}" in inspected.warnings
    plan = create_plan(effective, provider=StubProvider(keep_all), inspection=inspected)
    run_dir = config.data_root / "runs" / plan.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert [item["path"] for item in manifest["input_documents"]] == [
        str(agents),
        str(claude),
    ]
    assert [item["path"] for item in manifest["targets"]] == [str(agents)]
    assert manifest["targets"][0]["pre_sha256"] == sha256_bytes(agents_original.encode("utf-8"))
    assert with_archived_target_selection(config, manifest["target_selection"]) == effective

    apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert "preserve named handoffs" in agents.read_text(encoding="utf-8")
    assert "inspect loaded instructions" in agents.read_text(encoding="utf-8")
    assert claude.read_text(encoding="utf-8") == claude_original

    compiled_once = agents.read_bytes()
    second_inspection = inspect_state(effective)
    assert second_inspection.targets[0].content_bytes == compiled_once
    assert second_inspection.targets[0].represented_input_sources == (str(claude),)
    assert f"input_already_represented_in_output:{claude}" in second_inspection.warnings
    second_plan = create_plan(
        effective,
        provider=StubProvider(keep_all),
        inspection=second_inspection,
    )
    second_manifest = json.loads(
        (config.data_root / "runs" / second_plan.run_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert second_manifest["targets"][0]["changed"] is False
    assert second_manifest["targets"][0]["represented_input_sources"] == [str(claude)]
    assert agents.read_bytes() == compiled_once

    restore_run(config, plan.run_id)
    assert agents.read_text(encoding="utf-8") == agents_original
    assert claude.read_text(encoding="utf-8") == claude_original


def test_output_representation_requires_the_complete_exact_directive_multiset(
    config_factory: ConfigFactory,
) -> None:
    output_original = "# Shared\n\n- SHOULD preserve alpha.\n"
    secondary = "# Shared\n\n- SHOULD preserve alpha.\n- SHOULD preserve beta.\n"
    config, (output, source) = config_factory(
        (output_original, secondary),
        target_names=("AGENTS.md", "CLAUDE.md"),
    )
    effective = with_target_overrides(config, targets=(output, source), output=output)

    inspected = inspect_state(effective)

    assert inspected.targets[0].represented_input_sources == ()
    assert len(inspected.targets[0].directives) == 3
    assert not any(
        warning.startswith("input_already_represented_in_output:") for warning in inspected.warnings
    )


def test_new_output_is_the_only_write_and_restore_removes_it(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    original = "# Source\n\n- SHOULD preserve this behavior.\n"
    config, (source,) = config_factory((original,), target_names=("source.md",))
    output = tmp_path / "new-output.md"
    effective = with_target_overrides(config, targets=(source,), output=output)
    plan = create_plan(
        effective,
        provider=StubProvider(keep_all),
        inspection=inspect_state(effective),
    )

    apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert source.read_text(encoding="utf-8") == original
    assert output.read_text(encoding="utf-8") == original

    restore_run(config, plan.run_id)
    assert not output.exists()


def test_read_only_input_drift_blocks_output_apply_before_any_write(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, inputs = config_factory(
        ("# One\n\n- SHOULD keep one.\n", "# Two\n\n- SHOULD keep two.\n"),
        target_names=("one.md", "two.md"),
    )
    output = tmp_path / "compiled.md"
    output.write_text("original output\n", encoding="utf-8")
    effective = with_target_overrides(config, targets=inputs, output=output)
    plan = create_plan(
        effective,
        provider=StubProvider(keep_all),
        inspection=inspect_state(effective),
    )
    inputs[1].write_text("# Two\n\n- SHOULD use a later edit.\n", encoding="utf-8")

    with pytest.raises(MeditateError) as caught:
        apply_run(config, plan.run_id, mode="attended", approval_sha256=plan.plan_sha256)
    assert caught.value.code == "source_drift"
    assert output.read_text(encoding="utf-8") == "original output\n"
