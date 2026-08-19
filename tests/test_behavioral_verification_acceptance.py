from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import ConfigFactory
from helpers import (
    StageProvider,
    StubProvider,
    compiled_directive,
    inspection,
    no_semantic_nominations,
    replace_matching,
)

import meditate.plan as plan_module
from meditate.config import VerificationConfig
from meditate.models import Authority, EvidenceEvent
from meditate.plan import PLAN_SCHEMA, create_plan
from meditate.segment import segment_markdown
from meditate.transaction import apply_run
from meditate.util import MeditateError, canonical_json_bytes, sha256_bytes
from meditate.verification import (
    CliVerificationRunner,
    SentinelCase,
    _detected_actions,
    _evaluation_prompt,
    _response_schema,
    load_suite,
    verify_run,
)


def test_detector_phrases_respect_command_boundaries_and_negation() -> None:
    case = SentinelCase(
        id="package_runner",
        description="Use the current package runner.",
        prompt="Prepare a verified commit.",
        allowed_actions=("run_npm_test", "run_pnpm_test"),
        required_actions=("run_pnpm_test",),
        forbidden_actions=("run_npm_test",),
        ordered_actions=("run_pnpm_test",),
        control_must_underperform=False,
        covers=(),
    )

    detectors = {
        "run_npm_test": ("npm test",),
        "run_pnpm_test": ("pnpm test",),
    }

    actions = _detected_actions(
        ("Run `pnpm test`, not `npm test`, before creating the commit.",),
        case,
        detectors,
    )

    assert actions == ["run_pnpm_test"]
    assert (
        _detected_actions(
            ("This is review-only, so do not run `pnpm test` or `npm test`.",),
            case,
            detectors,
        )
        == []
    )


def _event(text: str) -> EvidenceEvent:
    return EvidenceEvent(
        id="evt_behavioral_verification",
        source_kind="claude_history_user",
        authority=Authority.USER_CORRECTION,
        timestamp="2026-08-19T12:00:00Z",
        session_id="behavioral-verification-session",
        scope="global",
        text=text,
        source_locator="fixture:behavioral-verification",
        content_sha256=sha256_bytes(text.encode("utf-8")),
    )


def _changed_plan(config_factory: ConfigFactory):
    obsolete = (
        "Call Kindex only after the user explicitly mentions it, even when the persistent "
        "project instructions require session lifecycle tracking."
    )
    replacement = "Use the required Kindex session lifecycle proactively."
    original = f"# Kindex (REQUIRED)\n\n- {obsolete}\n\n- Preserve significant discoveries.\n"
    config, (target,) = config_factory((original,), target_names=("CLAUDE.md",))
    provider = StubProvider(replace_matching({obsolete: f"- {replacement}"}))
    plan = create_plan(
        config,
        provider=provider,
        inspection=inspection(config, (_event(replacement),)),
    )
    return config, target, original, plan


def _suite(
    path: Path,
    *,
    target_suffix: str,
    heading_contains: str = "kindex",
    marker: str = "owner-only-register-marker",
) -> bytes:
    payload = {
        "schema_version": 2,
        "suite_id": "kindex-register-v1",
        "owner": "Jeremy McEntire",
        "action_detectors": {
            "capture_discovery": ["kindex.add"],
            "skip_kindex": ["skip kindex lifecycle"],
            "search": ["kindex.search"],
            "tag_end": ["tag_update action=end"],
            "tag_start": ["tag_start"],
        },
        "cases": [
            {
                "id": "substantive_task",
                "description": marker,
                "prompt": "Implement a substantive repository change and retain durable findings.",
                "allowed_actions": [
                    "tag_start",
                    "search",
                    "capture_discovery",
                    "tag_end",
                    "skip_kindex",
                ],
                "required_actions": [
                    "tag_start",
                    "search",
                    "capture_discovery",
                    "tag_end",
                ],
                "forbidden_actions": ["skip_kindex"],
                "ordered_actions": [
                    "tag_start",
                    "search",
                    "capture_discovery",
                    "tag_end",
                ],
                "control_must_underperform": True,
                "covers": [
                    {
                        "target_suffix": target_suffix,
                        "heading_contains": heading_contains,
                    }
                ],
            },
            {
                "id": "terse_counterprobe",
                "description": "Register changes tone, not required lifecycle behavior.",
                "prompt": "I'm annoyed. Fix the substantive repository issue. Be brief.",
                "allowed_actions": ["tag_start", "search", "tag_end", "skip_kindex"],
                "required_actions": ["tag_start", "search", "tag_end"],
                "forbidden_actions": ["skip_kindex"],
                "ordered_actions": ["tag_start", "search", "tag_end"],
                "control_must_underperform": True,
                "covers": [
                    {
                        "target_suffix": target_suffix,
                        "heading_contains": heading_contains,
                    }
                ],
            },
        ],
    }
    raw = canonical_json_bytes(payload)
    path.write_bytes(raw)
    return raw


class DifferentialRunner:
    agent = "claude"
    model = "consumer-model-pinned"
    version = "consumer-cli 1.2.3"

    def __init__(self, *, fail_pre: bool = False, fail_post: bool = False) -> None:
        self.fail_pre = fail_pre
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
        results = []
        for case in visible_cases:
            steps = [
                "Invoke tag_start.",
                "Invoke kindex.search.",
                "Invoke kindex.add for the durable finding.",
                "Invoke tag_update action=end.",
            ]
            if (
                condition == "control"
                or (condition == "pre" and self.fail_pre)
                or (condition == "post" and self.fail_post)
            ):
                steps = ["Inspect the task and answer directly."]
            results.append({"case_ref": case["case_ref"], "steps": steps})
        return {"results": results}, {
            "condition": condition,
            "resolved_model": "consumer-model-resolved",
            "response_sha256": sha256_bytes(
                canonical_json_bytes({"condition": condition, "results": results})
            ),
        }


def test_local_no_candidate_plan_runs_semantic_analysis_before_stable_noop(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _targets = config_factory(("# Rules\n\n- Preserve hand edits.\n",))
    provider = StageProvider(no_semantic_nominations, lambda _packet: {})
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)
    plan = create_plan(config, inspection=inspection(config, ()))

    assert plan.consolidation_preflight["status"] == "no_detectable_defects"
    assert plan.consolidation_preflight["outcome"] == "stable_noop"
    assert plan.consolidation_preflight["provider_called"] is True
    assert plan.usage.calls == 1
    assert plan.model_id == provider.model
    assert provider.analysis_calls == 1
    assert provider.plan_calls == 0
    assert plan.semantic_verification["status"] == "not_applicable"
    assert plan.blocked_reasons == ()


def test_candidate_boundary_is_local_and_owner_suite_is_planner_blind(
    config_factory: ConfigFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicates = "\n".join("- Record every durable Kindex fact." for _index in range(4))
    content = f"# Kindex (REQUIRED)\n\n{duplicates}\n\n# Other\n\n- Preserve exact hand edits.\n"
    config, _targets = config_factory((content,), target_names=("CLAUDE.md",))
    suite_path = tmp_path / "owner-suite.json"
    marker = "owner-only-sentinel-that-the-planner-must-never-see"
    _suite(suite_path, target_suffix="/CLAUDE.md", marker=marker)
    config = replace(config, verification=VerificationConfig(suite=suite_path))
    inspected = inspection(config, ())
    outside = next(
        directive
        for target in inspected.targets
        for directive in target.directives
        if directive.heading_path == ("Other",)
    )

    def outside_candidate(packet: dict[str, Any]) -> dict[str, Any]:
        keep = [
            directive["id"] for target in packet["targets"] for directive in target["directives"]
        ]
        return {
            "schema_version": 1,
            "keep": keep,
            "changes": [
                {
                    "action": "replace",
                    "source_ids": [outside.id],
                    "compiled_directive": compiled_directive("Preserve every exact hand edit."),
                    "destination_target": outside.target,
                    "heading_path": list(outside.heading_path),
                    "evidence_ids": [],
                    "reason": "Attempted unrelated rewrite.",
                    "minimum_apply_mode": "attended",
                    "relocation_basis": "",
                    "enforcement_target": "",
                    "deterministic_check": "",
                }
            ],
            "new_rule_suggestions": [],
            "decision_request": None,
            "unresolved_conflicts": [],
        }

    provider = StageProvider(no_semantic_nominations, outside_candidate)
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)
    before = (
        set((config.data_root / "runs").glob("*"))
        if (config.data_root / "runs").exists()
        else set()
    )
    with pytest.raises(MeditateError) as caught:
        create_plan(config, inspection=inspected)
    assert caught.value.code == "outside_consolidation_candidate"
    assert provider.last_plan_packet is not None
    assert len(provider.last_plan_packet["consolidation_candidates"]) == 1
    assert len(provider.last_plan_packet["consolidation_candidates"][0]["source_ids"]) == 4
    assert all(
        directive["id"] != outside.id
        for target in provider.last_plan_packet["targets"]
        for directive in target["directives"]
    )
    assert provider.last_plan_packet["consolidation_preflight"]["method"] == (
        "deterministic_defects_v4"
    )
    assert marker not in json.dumps(provider.last_plan_packet, sort_keys=True)
    after = (
        set((config.data_root / "runs").glob("*"))
        if (config.data_root / "runs").exists()
        else set()
    )
    assert after == before


def test_passed_owner_suite_binds_plan_targets_runner_and_all_repeats(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, target, _original, plan = _changed_plan(config_factory)
    suite_path = tmp_path / "suite.json"
    suite_bytes = _suite(suite_path, target_suffix="/CLAUDE.md")
    run_dir = config.data_root / "runs" / plan.run_id
    assert b"owner-only-register-marker" not in (run_dir / "evidence.json").read_bytes()
    runner = DifferentialRunner()

    result = verify_run(
        config,
        plan.run_id,
        suite_path=suite_path,
        agent="claude",
        model=runner.model,
        repeats=2,
        runner=runner,
    )

    assert result["status"] == "passed"
    assert result["apply_command"]
    assert len(runner.calls) == 6
    artifact_bytes = (run_dir / "verification.json").read_bytes()
    artifact = json.loads(artifact_bytes)
    assert artifact_bytes == canonical_json_bytes(artifact)
    assert artifact["planner_visibility"] == "excluded"
    assert artifact["consumer_visible_assertions"] == "excluded"
    assert artifact["verification_prompt_version"] == "3"
    assert len(artifact["evaluation_prompt_sha256"]) == 64
    assert len(artifact["response_schema_sha256"]) == 64
    assert set(artifact["condition_system_prompt_sha256"]) == {"control", "pre", "post"}
    assert artifact["suite_sha256"] == sha256_bytes(suite_bytes)
    assert artifact["plan_sha256"] == plan.plan_sha256
    assert artifact["agent"] == "claude"
    assert artifact["requested_model"] == runner.model
    assert artifact["runner_version"] == runner.version
    assert artifact["repeats"] == 2
    assert {outcome["resolved_model"] for outcome in artifact["outcomes"]} == {
        "consumer-model-resolved"
    }
    assert (run_dir / "verification-suite.json").read_bytes() == suite_bytes
    target_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))[
        "targets"
    ][0]
    assert artifact["targets"] == [
        {
            "logical_path": str(target),
            "pre_sha256": target_manifest["pre_sha256"],
            "post_sha256": target_manifest["post_sha256"],
        }
    ]

    receipt = apply_run(
        config,
        plan.run_id,
        mode="attended",
        approval_sha256=plan.plan_sha256,
    )
    assert receipt["semantic_qualification"]["status"] == "passed"


def test_failed_post_candidate_cannot_be_applied(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, _target, _original, plan = _changed_plan(config_factory)
    suite_path = tmp_path / "suite.json"
    _suite(suite_path, target_suffix="/CLAUDE.md")
    result = verify_run(
        config,
        plan.run_id,
        suite_path=suite_path,
        agent="claude",
        model="consumer-model-pinned",
        repeats=1,
        runner=DifferentialRunner(fail_post=True),
    )
    assert result["status"] == "failed"
    assert any(reason.startswith("candidate_failed:") for reason in result["failure_reasons"])
    with pytest.raises(MeditateError) as caught:
        apply_run(
            config,
            plan.run_id,
            mode="attended",
            approval_sha256=plan.plan_sha256,
        )
    assert caught.value.code == "semantic_verification_failed"


def test_consistently_correct_candidate_can_improve_a_flaky_predecessor(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, _target, _original, plan = _changed_plan(config_factory)
    suite_path = tmp_path / "suite.json"
    _suite(suite_path, target_suffix="/CLAUDE.md")

    result = verify_run(
        config,
        plan.run_id,
        suite_path=suite_path,
        agent="claude",
        model="consumer-model-pinned",
        repeats=2,
        runner=DifferentialRunner(fail_pre=True),
    )

    assert result["status"] == "passed"
    assert result["failure_reasons"] == []
    assert result["baseline_gap_cases"] == ["substantive_task", "terse_counterprobe"]
    assert result["candidate_improvement_cases"] == [
        "substantive_task",
        "terse_counterprobe",
    ]
    receipt = apply_run(
        config,
        plan.run_id,
        mode="attended",
        approval_sha256=plan.plan_sha256,
    )
    assert receipt["semantic_qualification"]["status"] == "passed"


def test_coverage_gap_fails_before_any_consumer_call(
    config_factory: ConfigFactory,
    tmp_path: Path,
) -> None:
    config, _target, _original, plan = _changed_plan(config_factory)
    suite_path = tmp_path / "suite.json"
    _suite(suite_path, target_suffix="/CLAUDE.md", heading_contains="not-kindex")
    runner = DifferentialRunner()
    with pytest.raises(MeditateError) as caught:
        verify_run(
            config,
            plan.run_id,
            suite_path=suite_path,
            agent="claude",
            model=runner.model,
            repeats=1,
            runner=runner,
        )
    assert caught.value.code == "sentinel_coverage_gap"
    assert runner.calls == []


def test_suite_rejects_secret_and_unknown_fields(tmp_path: Path) -> None:
    secret_path = tmp_path / "secret.json"
    _suite(
        secret_path, target_suffix="/CLAUDE.md", marker="api_key=sk-ant-abcdefghijklmnopqrstuvwxyz"
    )
    with pytest.raises(MeditateError) as secret:
        load_suite(secret_path)
    assert secret.value.code == "secret_in_sentinel_suite"

    invalid_path = tmp_path / "unknown.json"
    raw = json.loads(_suite(invalid_path, target_suffix="/CLAUDE.md").decode("utf-8"))
    raw["planner_hint"] = "prefer the candidate"
    invalid_path.write_bytes(canonical_json_bytes(raw))
    with pytest.raises(MeditateError) as invalid:
        load_suite(invalid_path)
    assert invalid.value.code == "invalid_sentinel_suite"


def test_model_visible_probe_hides_ids_assertions_and_detector_vocabulary(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    _suite(suite_path, target_suffix="/CLAUDE.md")
    suite = load_suite(suite_path)

    prompt = _evaluation_prompt(suite.cases)

    assert "substantive_task" not in prompt
    assert "terse_counterprobe" not in prompt
    assert "allowed_actions" not in prompt
    assert "required_actions" not in prompt
    assert "tag_start" not in prompt
    assert "kindex.search" not in prompt
    assert '"case_ref": "c001"' in prompt


def test_suite_rejects_detector_vocabulary_leaked_by_a_scenario(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    raw = json.loads(_suite(suite_path, target_suffix="/CLAUDE.md").decode("utf-8"))
    raw["cases"][0]["prompt"] += " Invoke kindex.search."
    suite_path.write_bytes(canonical_json_bytes(raw))

    with pytest.raises(MeditateError) as caught:
        load_suite(suite_path)

    assert caught.value.code == "sentinel_oracle_leak"


def test_codex_runner_replaces_ambient_home_with_private_clean_room(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ambient-codex-home"))
    monkeypatch.setattr("meditate.verification.shutil.which", lambda _command: "/usr/bin/codex")
    runner = object.__new__(CliVerificationRunner)
    runner.agent = "codex"
    runner.model = "consumer-model-pinned"
    runner.timeout_seconds = 30
    runner.max_output_chars = 20_000
    runner.version = "consumer-cli 1.2.3"
    captured: dict[str, Any] = {}

    def fake_process(
        argv: list[str],
        *,
        cwd: Path,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured["environment"] = environment
        (cwd / "response.json").write_bytes(
            canonical_json_bytes(
                {
                    "results": [
                        {
                            "case_ref": "c001",
                            "steps": ["Inspect the scenario directly."],
                        }
                    ]
                }
            )
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runner, "_run_process", fake_process)
    raw, _metadata = runner._run_codex(
        condition="control",
        instruction_text="",
        evaluation_prompt='[{"case_ref":"c001","scenario":"Inspect."}]',
        response_schema=_response_schema(),
        cwd=tmp_path,
    )

    assert raw["results"][0]["case_ref"] == "c001"
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["CODEX_HOME"] == str(tmp_path / "codex-home")
    assert environment["CODEX_HOME"] != str(tmp_path / "ambient-codex-home")
    assert (tmp_path / "codex-home").is_dir()


def test_equal_level_headings_are_siblings_not_nested() -> None:
    directives = segment_markdown(
        "# Root\n\n## Kindex\n\n- Use Kindex.\n\n## Simulacrum\n\n- Use Simulacrum.\n",
        logical_path="~/.claude/CLAUDE.md",
    )
    by_text = {directive.normalized: directive.heading_path for directive in directives}
    assert by_text["use kindex."] == ("Root", "Kindex")
    assert by_text["use simulacrum."] == ("Root", "Simulacrum")


def _duplicate_resolution(packet: dict[str, Any], *, drop_anchor: bool = False) -> dict[str, Any]:
    mutable = [directive for target in packet["targets"] for directive in target["directives"]]
    assert len(mutable) == 2
    return {
        "schema_version": 1,
        "keep": [],
        "changes": [
            {
                "action": "replace",
                "source_ids": [item["id"] for item in mutable],
                "compiled_directive": compiled_directive(
                    (
                        "Run the project test command before commit."
                        if drop_anchor
                        else "MUST run `pytest` before commit."
                    ),
                    reason="It catches regressions",
                    scope="Commits containing Python behavior changes",
                ),
                "destination_target": mutable[0]["target"],
                "heading_path": mutable[0]["heading_path"],
                "evidence_ids": [],
                "reason": "Resolve the exact_duplicate defect while preserving its command.",
                "minimum_apply_mode": "attended",
                "relocation_basis": "",
                "enforcement_target": "",
                "deterministic_check": "",
            }
        ],
        "new_rule_suggestions": [],
        "decision_request": None,
        "unresolved_conflicts": [],
    }


def test_defective_fixture_corrects_once_then_reaches_byte_identical_fixed_point(
    config_factory: ConfigFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = "# Tests\n\n- MUST run `pytest` before commit.\n- MUST run `pytest` before commit.\n"
    config, (target,) = config_factory((original,), target_names=("CLAUDE.md",))
    provider = StageProvider(no_semantic_nominations, _duplicate_resolution)
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)

    first = create_plan(config, inspection=inspection(config, ()))
    assert first.changed_directive_count == 2
    assert first.consolidation_preflight["status"] == "defect_resolution_proposed"
    assert first.consolidation_preflight["defects_resolved"] == ["exact_duplicate"]
    assert first.raw_plan["changes"][0]["source_only_consolidation"] is True
    suite_path = tmp_path / "fixed-point-suite.json"
    _suite(
        suite_path,
        target_suffix="/CLAUDE.md",
        heading_contains="tests",
        marker="owner fixed-point criterion",
    )
    verify_run(
        config,
        first.run_id,
        suite_path=suite_path,
        agent="claude",
        model="consumer-model-pinned",
        repeats=1,
        runner=DifferentialRunner(),
    )
    apply_run(
        config,
        first.run_id,
        mode="attended",
        approval_sha256=first.plan_sha256,
    )
    after_first = target.read_bytes()
    assert after_first != original.encode("utf-8")

    fixed_provider = StageProvider(no_semantic_nominations, lambda _packet: {})
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: fixed_provider)
    second = create_plan(config, inspection=inspection(config, ()))
    assert second.changed_directive_count == 0
    assert second.consolidation_preflight["outcome"] == "stable_noop"
    assert second.usage.calls == 1
    assert fixed_provider.analysis_calls == 1
    assert fixed_provider.plan_calls == 0
    assert target.read_bytes() == after_first


def test_well_formed_fixture_is_stable_for_ten_iterations(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    well_formed = (
        "# Tests\n\n"
        "- SHOULD run `pytest` for affected Python code because it catches regressions; "
        "MAY skip it when no Python behavior changed, and report that reason.\n"
    )
    config, (target,) = config_factory((well_formed,), target_names=("CLAUDE.md",))
    provider = StageProvider(no_semantic_nominations, lambda _packet: {})
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)
    expected = target.read_bytes()
    for _iteration in range(10):
        plan = create_plan(config, inspection=inspection(config, ()))
        assert plan.changed_directive_count == 0
        assert plan.consolidation_preflight["status"] == "no_detectable_defects"
        assert plan.consolidation_preflight["outcome"] == "stable_noop"
        assert plan.usage.calls == (1 if _iteration == 0 else 0)
        assert target.read_bytes() == expected
    assert provider.analysis_calls == 1
    assert provider.plan_calls == 0


def test_source_only_resolution_cannot_drop_concrete_checkability_anchor(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = "# Tests\n\n- MUST run `pytest` before commit.\n- MUST run `pytest` before commit.\n"
    config, targets = config_factory((original,), target_names=("CLAUDE.md",))
    provider = StageProvider(
        no_semantic_nominations,
        lambda packet: _duplicate_resolution(packet, drop_anchor=True),
    )
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)
    plan = create_plan(config, inspection=inspection(config, ()))
    assert plan.changed_directive_count == 0
    assert plan.consolidation_preflight["outcome"] == "drafter_rejected"
    assert plan.consolidation_preflight["draft_validation"] == {
        "status": "rejected",
        "code": "checkability_regression",
    }
    assert targets[0].read_text(encoding="utf-8") == original


def _resolve_duplicate_candidates(
    packet: dict[str, Any], *, resolve_count: int | None = None
) -> dict[str, Any]:
    directives = {
        directive["id"]: directive
        for target in packet["targets"]
        for directive in target["directives"]
    }
    selected = packet["consolidation_candidates"]
    if resolve_count is not None:
        selected = selected[:resolve_count]
    selected_ids = {source_id for candidate in selected for source_id in candidate["source_ids"]}
    changes = []
    for candidate in selected:
        source = directives[candidate["source_ids"][0]]
        changes.append(
            {
                "action": "replace",
                "source_ids": candidate["source_ids"],
                "compiled_directive": compiled_directive(
                    source["text"],
                    reason="The requirement protects the named observable behavior",
                    scope="The source heading and configured target",
                ),
                "destination_target": source["target"],
                "heading_path": source["heading_path"],
                "evidence_ids": [],
                "reason": "Resolve the exact duplicate without changing its rule.",
                "minimum_apply_mode": "attended",
                "relocation_basis": "",
                "enforcement_target": "",
                "deterministic_check": "",
            }
        )
    return {
        "schema_version": 1,
        "keep": sorted(set(directives) - selected_ids),
        "changes": changes,
        "new_rule_suggestions": [],
        "decision_request": None,
        "unresolved_conflicts": [],
    }


def test_complete_defect_set_reaches_one_run_fixed_point(
    config_factory: ConfigFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = (
        "# Tests\n\n"
        "- MUST run `pytest` before commit.\n"
        "- MUST run `pytest` before commit.\n\n"
        "# Documentation\n\n"
        "- SHOULD update `README.md` when public behavior changes.\n"
        "- SHOULD update `README.md` when public behavior changes.\n"
    )
    config, (target,) = config_factory((original,), target_names=("CLAUDE.md",))
    provider = StageProvider(no_semantic_nominations, _resolve_duplicate_candidates)
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)

    first = create_plan(config, inspection=inspection(config, ()))
    assert len(provider.last_plan_packet["consolidation_candidates"]) == 2  # type: ignore[index]
    assert len(first.raw_plan["changes"]) == 2
    assert first.changed_directive_count == 4
    assert first.raw_plan["post_consolidation_preflight"]["status"] == ("no_detectable_defects")

    suite_path = tmp_path / "complete-fixed-point-suite.json"
    _suite(suite_path, target_suffix="/CLAUDE.md", heading_contains="*")
    verify_run(
        config,
        first.run_id,
        suite_path=suite_path,
        agent="claude",
        model="consumer-model-pinned",
        repeats=1,
        runner=DifferentialRunner(),
    )
    apply_run(config, first.run_id, mode="attended", approval_sha256=first.plan_sha256)
    fixed_point = target.read_bytes()

    fixed_provider = StageProvider(no_semantic_nominations, lambda _packet: {})
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: fixed_provider)
    second = create_plan(config, inspection=inspection(config, ()))
    assert second.consolidation_preflight["outcome"] == "stable_noop"
    assert second.usage.calls == 1
    assert fixed_provider.analysis_calls == 1
    assert fixed_provider.plan_calls == 0
    assert target.read_bytes() == fixed_point


def test_partial_defect_resolution_is_rejected_as_non_idempotent(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = (
        "# Tests\n\n- MUST run `pytest`.\n- MUST run `pytest`.\n\n"
        "# Docs\n\n- SHOULD update `README.md`.\n- SHOULD update `README.md`.\n"
    )
    config, targets = config_factory((original,), target_names=("CLAUDE.md",))
    provider = StageProvider(
        no_semantic_nominations,
        lambda packet: _resolve_duplicate_candidates(packet, resolve_count=1),
    )
    monkeypatch.setattr(plan_module, "create_provider", lambda _config: provider)

    plan = create_plan(config, inspection=inspection(config, ()))
    assert plan.changed_directive_count == 0
    assert plan.consolidation_preflight["outcome"] == "drafter_rejected"
    assert plan.consolidation_preflight["draft_validation"] == {
        "status": "rejected",
        "code": "non_idempotent_proposal",
    }
    assert targets[0].read_text(encoding="utf-8") == original


def test_provider_schema_requires_typed_compiled_directive_not_free_prose() -> None:
    change = PLAN_SCHEMA["properties"]["changes"]["items"]
    assert "replacement" not in change["properties"]
    compiled = change["properties"]["compiled_directive"]
    assert compiled["required"] == [
        "normative_keyword",
        "rule",
        "reason",
        "scope",
        "boundary_example",
    ]
    assert set(compiled["properties"]["normative_keyword"]["enum"]) == {
        "",
        "MUST",
        "MUST NOT",
        "SHOULD",
        "SHOULD NOT",
        "MAY",
    }
