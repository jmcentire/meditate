# Changelog

All notable changes to Meditate are documented here.

## 0.2.0 - 2026-08-19

Meditate v0.2.0 now treats a stable, defect-free directive set as its fixed point.
The objective is defect resolution. Size is telemetry rather than an objective,
and every changed plan must pass an independent consumer-agent qualification
before apply.

### Added

- Local defect preflight with a confirmed `exact_duplicate` class and a
  conservative same-heading/shared-subject `exception_lineage` review class.
  A file with no candidates produces a successful zero-token `stable_noop` and
  never resolves provider credentials: zero model calls.
- Complete-set fixed-point planning: the provider receives every non-overlapping
  candidate but only candidate directive IDs; unrelated directives are locally
  kept. A changed post-image retaining a confirmed defect fails with
  `non_idempotent_proposal`.
- Typed directive compilation. Providers supply an RFC 2119 keyword, concrete
  rule, behavioral rationale, scope, and optional boundary example; local code
  validates and renders canonical Markdown instead of accepting replacement prose.
- Planner-blind owner-authored sentinel suites and `meditate verify`; the planner
  never receives the suite or its outcomes. Every case runs against control,
  predecessor, and candidate bundles on Claude or Codex. The consumer sees only
  neutral scenarios and opaque case references and returns a free-form ordered
  plan; semantic case/action IDs, assertions, and bounded literal detectors remain
  local. Suite, verifier prompt/schema/system prompts, plan, target, agent/version,
  model, repeat, response, and outcome hashes are bound into immutable artifacts.
  A pass is not universal behavioral equivalence; it proves only the recorded cases
  and consumer.
- Owner Kindex probe/counter-probe suites for Claude and Codex, including
  substantive lifecycle, irritated-register, trivial-task, topic-switch,
  long-material, and durable-deduplication boundaries.
- Acceptance fixtures for unchanged input, corrected input, second-run byte
  identity, ten-iteration stability, complete multi-defect convergence, partial-
  resolution rejection, and checkability-anchor preservation.

### Changed

- Byte growth is permitted when otherwise valid and justified; reports label
  byte counts as telemetry. The configured size floor, absolute growth headroom,
  Claude line guidance, and Codex configured-target byte budget remain safety
  constraints.
- Reports lead with `stable_noop`, `reviewed_noop`, or qualification-required
  defect outcomes and enumerate detected, resolved, and unresolved classes.
- `run --apply` executes the configured owner suite before requesting unattended
  apply. A passed suite does not bypass the unattended config, probation, or
  low-blast-radius gates.
- When Kindex is enabled and `kin` is installed, every configured search and node
  read is required. Failure aborts before planning with `kindex_required_failed`
  instead of silently dropping durable evidence.
- Public runtime credentials are exclusively `ANTHROPIC_API_KEY` for planning and
  `OPENAI_API_KEY` for clean-room Codex consumer verification; private
  organization-specific key names do not appear in source, tests, documentation,
  or release artifacts.
- Live qualification rejected verifier v1 because model-visible semantic action
  labels leaked the grading key to the cold control. Verifier schema/prompt v2
  uses hidden local detectors, rejects detector vocabulary in visible scenarios,
  and binds exact prompt provenance. The same qualification pass also made RFC
  keywords exempt from the legacy intensifier check, admitted source-grounded
  universal restatements, and canonicalized the archive root before any provider
  call so macOS `/tmp` aliases cannot create an unverifiable run.
- Prompt version 10, SHA-256
  `d277c05dee519d697586dcf3a1cdf74c3a848ee2297e83985d7c96b66ff50d72`, and
  parser version `meditate-parser-v25` invalidate prior plans rather than
  reinterpreting them under the new objective and schema.
- Candidate qualification now requires every case on every repeat, forbids any
  per-case predecessor-to-candidate regression, and requires designated controls
  to underperform the candidate. Predecessor misses remain visible as
  `baseline_gap_cases`; candidate repairs remain visible as
  `candidate_improvement_cases` instead of making a flaky predecessor an oracle.
- Codex verification creates a private temporary `CODEX_HOME`, ignores ambient
  user config/rules, and requires `OPENAI_API_KEY`; global `AGENTS.md`, memories,
  and user configuration cannot leak into the cold control.

### Live qualification receipts

- Restored live Claude target SHA
  `441fe6e9af0302329b753fa9138f6a5fc5c556637991bfec679700adea1acb76`
  and Codex target SHA
  `0dd415bb140f10fe95c70005e33ca523f1ed60419a79bbfeabdf9a31446c6b63`
  produced zero-call, byte-identical `stable_noop` runs
  `20260819T161206Z-d6dbad85` and `20260819T161218Z-834d615b`.
- Disposable Claude plan `20260819T165955Z-1987f9ef` resolved one exact duplicate
  (67 to 66 directives; 11,606 to 11,378 bytes). Claude Code 2.1.224 with
  `claude-sonnet-4-6` scored pre 18/18, post 18/18, and control 0/18; receipt SHA
  `4f1851d08ddb4047243f6978204bda6b29ad59d245dd744a020e31321eb878aa`
  authorized attended disposable apply. Run `20260819T170602Z-39e3bba4` then
  returned a zero-call byte-identical no-op.
- Claude run `20260819T165129Z-70f323ea` scored pre 18/18 and post 17/18 after a
  lower-position rewrite. It failed closed and was never applied.
- Disposable Codex plan `20260819T171655Z-546b02cd` resolved one exact duplicate
  (35 to 34 directives; 5,269 to 4,830 bytes). Codex CLI 0.147.0 with
  `gpt-5.6-sol` in a fresh private `CODEX_HOME` scored post 18/18 and control 0/18;
  one predecessor repeat gap was repaired and recorded as an improvement. Receipt
  SHA `0376960893146c8f9f29559da0fee2a9f14a0b182eae3759689dda2b0e915b1d`
  authorized attended disposable apply. Run `20260819T171954Z-d68b18c5` then
  returned a zero-call byte-identical no-op.

These receipts qualify only the six owner-authored Kindex cases on the recorded
consumer versions and models. They do not establish universal behavioral
equivalence or future-model performance.

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
