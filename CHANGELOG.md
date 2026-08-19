# Changelog

All notable changes to Meditate are documented here.

## 0.3.0 - 2026-08-19

Meditate v0.3.0 adds the semantic candidate boundary that v0.2.0 lacked. It ships two
separate production boundaries on the road to a local behavioral-contract compiler:
evidence-grounded semantic nomination, then bounded directive compilation over only
locally admitted candidates. Current directives, temporally ordered interactions,
auto-memory, and required Kindex—an optional local persistent knowledge graph exposed
through `kin`—can nominate defects and
missing behaviors that exact lexical deduplication cannot see. This release does not
promote missing-rule hypotheses. The model has no authority to write, choose an
unconfigured target, or declare its own output correct.

### Added

- A read-only semantic Analyst, separate from the consolidation Drafter. It can
  nominate `contradiction`, `temporal_supersession`, `underspecified`,
  `overspecified`, `wrong_scope`, `enforcement_candidate`, and `missing_rule`
  candidates in an explicit semantic domain. Every nomination carries exact
  source IDs, submitted evidence IDs, an intent, a reason, and positive
  and negative applicability boundaries.
- Deterministic local admission after the Analyst returns. Unknown or protected
  directive IDs, invented evidence IDs, too-small evidence records, weak grounding, unsupported
  temporal claims, one-observation enforcement claims, and unsupported missing
  rules fail before any plan is archived. The Analyst cannot draft prose,
  choose a destination, assign authority, answer a collision, or mint durable IDs.
- Stable local nomination IDs plus intent and evidence fingerprints. Same-target,
  same-heading existing-rule nominations may enter the bounded Drafter packet;
  cross-target or cross-heading nominations remain report-only. Semantic domains
  prevent superficially similar rules in different domains from being collapsed.
- Evidence-backed missing-rule hypotheses. The Drafter may render an RFC-shaped
  candidate (`MUST`/`MUST NOT`/`SHOULD`/`SHOULD NOT`/`MAY`, rule, reason, scope,
  and optional boundary example), but it has `write_authority=none`, never enters
  proposed target bytes, cannot be applied, and requires a later explicit
  promotion plus owner-authored behavioral qualification. Version 0.3 deliberately
  ships no promotion command.
- A private, content-addressed semantic-analysis cache. An exact sanitized input,
  config, provider/model, prompt, schema, and parser tuple reuses the validated
  result without another Analyst call. The first exact snapshot is analyzed;
  stable repeats are byte-identical cache-backed no-ops.
- Hash-bound `analysis.json` run artifacts, semantic summaries in plans,
  manifests, reports, CLI JSON, and JSONL, and archive verification that rejects
  tampering or prompt/parser drift.
- Synthetic acceptance coverage for conversation-driven supersession, report-only
  missing rules, cross-scope contradiction reporting, under/over/scope candidates,
  repeated-evidence enforcement, Analyst smuggling attempts, and ten-run stability.
- Boundary-aware verifier protocol v3. Literal command detectors use alphanumeric
  boundaries and clause-local negation filtering, preventing `npm test` from matching
  inside `pnpm test` or a prohibition from being counted as an execution.
- Parser v32 rejects a second embedded uppercase RFC 2119 keyword inside a typed rule,
  preserving the single locally rendered normative operator.

### Live v0.3.0 receipts

- Claude `20260819T200834Z-321749c4` found four semantic nominations and compiled one
  report-only enforcement escalation plus one missing-rule suggestion. Outcome
  `enforcement_candidates` preserved 65 directives/10,703 bytes and target SHA-256
  `441fe6e9af0302329b753fa9138f6a5fc5c556637991bfec679700adea1acb76`.
- Codex `20260819T200912Z-ef9020d0` found five semantic nominations. Its Drafter introduced
  unsupported force, so `drafter_rejected` preserved 33 directives/4,276 bytes and target
  SHA-256 `0dd415bb140f10fe95c70005e33ca523f1ed60419a79bbfeabdf9a31446c6b63`.
- Both exact-repeat receipts used the Analyst cache and current Analyst v4/parser v5 plus
  Drafter v16/parser v32. Neither changed target bytes or established behavioral equivalence.
- Disposable package-manager plans `20260819T204620Z-53e25b49` (Claude) and
  `20260819T204859Z-ab0a357e` (Codex) each compiled an admitted temporal `npm`→`pnpm`
  rewrite. Claude Code 2.1.224/`claude-sonnet-4-6` and Codex CLI 0.147.0/`gpt-5.6-sol`
  each passed three repeats of two trigger probes plus one counter-probe. Verification
  SHAs were `608c186ffa650fd7f6373c586811e926d299b48ca1da378b0ca4de5d29ee8c8c`
  and `5aa093c94010685ecf9278eafe06b12fda5cc628f0019b5e8e4fc3182cc3f241`.
  Only the disposable Codex-qualified plan was applied. Its target reached SHA-256
  `838ce9afe2405bb6ff999dc64722cc89191ece65b35b786ab6dd2615e0135f2b`; repeat run
  `20260819T205423Z-f3b11c4a` was byte-identical `reviewed_noop`, preserving the
  historical nomination for audit with zero confirmed unresolved defects. Real Claude
  and Codex instruction files were unchanged.

### Changed

- The default call budget is two: at most one read-only Analyst call and one
  bounded Drafter call on a fresh semantic run. Newly generated configs use
  aggregate input/output defaults of 160,000/16,384 tokens so two allowed calls
  do not inherit a one-call total. Existing explicit budgets remain unchanged,
  cover both stages, and fail before the Drafter when insufficient. Cache hits
  consume no Analyst call.
- `stable_noop` remains the fixed point, but the first exact snapshot is no longer
  claimed to be a zero-provider-call run. It may require one Analyst call to know
  that there is no semantic nomination; exact subsequent runs reuse the cache.
- Interaction history and Kindex are now semantic evidence, not merely weights on
  lexical candidates. When Kindex is enabled and available, every configured
  query and requested node read remains mandatory; failure aborts with
  `kindex_required_failed` rather than silently weakening the analysis.
- Analyst packets publish exact `allowed_source_ids` and `allowed_evidence_ids` arrays;
  ID-shaped strings inside untrusted histories or directive prose cannot become references.
- Both model stages cite evidence by immutable ID only. Local code materializes the exact
  sanitized text into artifacts, eliminating stochastic quote-copying from the trust boundary.
- Per-nomination rejection: malformed top-level output still aborts, while an invalid
  nomination is rejected and counted without discarding independently valid siblings. When all
  nominations are rejected, the result is `semantic_analysis_inconclusive`, never `stable_noop`.
- A semantic Drafter proposal that parses but fails an explicitly allowlisted semantic-quality
  gate now archives an unchanged `drafter_rejected` receipt with its rejection code. Authority,
  schema, secrecy, scope, candidate-boundary, and malformed top-level failures still abort, and
  no validator is weakened to make a model proposal pass.
- Drafter prompt version 16, SHA-256
  `5f3863095efd232010b596bdefb35bde79ace8047ac595757f03115064fb5a51`, and
  parser `meditate-parser-v32`; Analyst prompt version 4, SHA-256
  `254f2afb6ccb583146823ff96396dc6c7cf8099f1e1754c9e2fea780b8118847`, and
  parser `meditate-analyst-parser-v5`. Older plans fail closed rather than being
  reinterpreted under the new two-stage contract.
- Missing-rule drafts now return only an exact allowlisted nomination ID. Local code inherits the
  nomination's complete immutable evidence set, eliminating a stochastic provenance-copy step;
  unknown nomination IDs still abort.
- Existing-rule changes inside an admitted semantic candidate likewise inherit that candidate's
  complete evidence set. Model-supplied IDs may only be a subset of the bound set; unrelated IDs
  abort, while structural single-rule rewrites still require explicit evidence.
- Single-source semantic observations with no external evidence are now report-only instead of
  mutable. Multi-source source-grounded candidates remain eligible without external history.
- Report-only escalations now use the distinct `enforcement_candidates` outcome. They do not claim
  behavioral qualification or defect resolution, and target bytes remain unchanged.
- A total keep disposition over an admitted semantic hypothesis now reports
  `review_candidates_preserved`/`reviewed_noop` with zero confirmed unresolved defects.
  The nomination remains in the immutable report; a review hypothesis is not relabeled as a fact.
- Promotion remains explicit: single-source existing-rule observations require external evidence
  or corroborating sources; missing rules require operator promotion plus an owner suite; and
  escalations require deliberate enforcement installation plus qualification.

### Boundary

Semantic nomination is not semantic proof. Existing-rule changes still require
the planner-blind owner suite before apply. Missing-rule hypotheses are not
writeable in this release. The system can expose a likely gap and the evidence
for it; it cannot let the same model invent the grading criterion, promote the
rule, and then certify itself.

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
