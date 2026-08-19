# Changelog

All notable changes to Meditate are documented here.

## 0.1.0 - 2026-08-18

First public alpha release, prepared for distribution as a versioned wheel on the
[`v0.1.0` GitHub Release](https://github.com/jmcentire/meditate/releases/tag/v0.1.0).
PyPI publication is not claimed.

### Added

- Total keep, replace, remove, relocate, or report-only escalate disposition for
  every configured pre-image directive.
- Exact model/prompt provenance, semantic-verification status, Claude import
  graphs, and pre/post product metrics bound into recoverable plans.
- Attended exact-hash apply with archive-before-write, drift checks, rollback,
  restore, redaction, token limits, and explicit import trust boundaries.
- Scope-aware Claude rules, Codex instruction budgets, and release CI across the
  supported Python versions.
- A bounded `a`/`b`/`c`/custom decision request for each genuine unresolved collision,
  with equal-authority/scope/same-time precedence gates, local conflict
  fingerprints, immutable frozen-context successor plans, exact operator-response
  provenance, replay/depth gates, and no model self-answer.
- Post-provider configured-target reloads prevent stale Claude or Codex proposals;
  pending-decision queries become resolved successor records after a choice.
- Decision resolution shares the mutation lock with purge/apply, and successor
  purge removes run reports while retaining only a hash/ID replay tombstone;
  append-only JSONL decision events contain no raw request or response text.

### Corrected before release

- Operational action lists now establish coverage rather than universal order.
  High-impact directives must follow the loaded repository workflow and use
  stage-local checks that are applicable, project-required, and available before
  each action; all CI before commit is rejected.
- Planner prompt version 6 and parser version `meditate-parser-v20` make plans
  created under the prior interpretation fail closed at apply.
- Prompt v5 requires every change to copy an opaque `destination_target`
  byte-for-byte from `allowed_targets`: non-relocates retain the exact source
  target, while relocation selects another configured target without expanding
  `~`, normalizing, absolutizing, or inventing a path.
- Prompt v6 removes model-authored summaries; deterministic report summaries use
  validated disposition, conflict, and aggregate metric counts. Parser v20 also
  rejects repeated normalized eight-word replacement phrases and unsupported
  open-ended action catch-alls.
- Aggregate byte growth now archives a blocked `compression_regression` proposal
  with no apply command instead of treating expansion as consolidation. Live
  prompt-v5 run `20260819T013715Z-67de2a2b` was rejected and never applied after
  growing by 898 bytes, repeating workflow prose, adding “other applicable
  actions,” and disagreeing with the locally validated directive count.
- Final prompt-v6 live receipts used prompt SHA `61f949...`, parser
  `meditate-parser-v20`, model `claude-sonnet-4-6`, and
  `semantic_verification=not_run`. Claude run `20260819T015515Z-120c6869` covered 65 directives as 64
  keep/1 replace; its +720-byte proposal was blocked `compression_regression`,
  emitted no apply command, and left target SHA `441fe6e9...` unchanged. Codex run
  `20260819T015632Z-a4fde49b` kept 33/33 with zero changes/conflicts/delta,
  reported 4,276/32,768 configured-target bytes, emitted no apply command, and
  left target SHA `0dd415bb...` unchanged. These receipts qualify safe no-op and
  fail-closed blocking only, not behavioral equivalence.
- Decision display fields are single-line, human CLI output labels model framing
  untrusted/advisory, and Markdown escapes untrusted inline structure without
  modifying indented target diffs. Opposite-polarity collision inference now
  needs two shared subject-relevant terms; one generic shared action is insufficient.
- The provider-facing JSON schema now stays within Anthropic's strict supported
  subset and is stable across packets, without private target/directive/evidence
  enums; exact membership, decision cardinality, text bounds, and single-line
  constraints remain fail-closed in local validation.
- Release review rejected and never applied restored-baseline run
  `20260818T231558Z-6e8e4703`; the prior validator admitted the form, so the run is
  now a fixture the new gate must reject. This is not semantic qualification;
  semantic verification remains `not_run`.
