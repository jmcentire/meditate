# Meditate design brief

## Outcome

Build toward a locally operated behavioral-contract compiler and policy router that
resolves identified defects in directives used by Claude Code and OpenAI Codex.
Version 0.3 establishes two separate production boundaries: evidence-grounded
semantic nomination, then bounded directive compilation over locally admitted
candidates. Missing-rule promotion remains future work. Current prose is analyzed with
temporally ordered interaction, memory, and Kindex—an optional local persistent
knowledge graph exposed through `kin`—rather than only lexical duplication. Stability is the fixed point:
a well-formed directive set must survive byte-identically, while a defective set
must converge without silently losing behavior. Size is telemetry, not an
objective function.

**Authority before confidence is the first invariant.** Model fluency, evidence
volume, and deterministic structural checks do not grant permission or prove
behavioral equivalence. Current instructions, explicit corrections, applicable
scope, and human or named-actor boundaries remain authoritative.

The first real subject is Jeremy McEntire's local Claude Code state. No raw
interaction corpus or secret-bearing excerpt may be committed to this repo.

## Why it exists

The observed failure is monotonic append. A correction becomes a new clause,
but the rule that caused the correction is rarely rewritten. Contradiction is a
symptom; accumulated exceptions with no replacement relation are the mechanism.
Turning “nothing changed” into “something must shrink” recreates the same failure
as an unbounded objective: repeated runs erode a valid file. Meditate therefore
optimizes defect resolution and treats a no-op as a first-class success.

The local writable surface is narrow: global and project instruction files,
path-scoped rule files, auto-memory, compaction/session artifacts, and workspace
state. Meditate addresses the instruction and learned-directive subset. It is
not a universal context, vector-store, provider-state, or workspace scrubber.

## Design-review provenance

The implementation plan was produced in Claude Code's isolated plan permission
mode and then repeated at maximum effort as the supported replacement for the
removed `ultraplan` command. Simulacrum challenged the authority and deployment
framing until the rule distinguished durable user defaults from repository-level
human or named-actor handoffs. Advocate's multi-persona pass drove strict path,
archive, parser-version, single-use-plan, and recovery invariants. A Constrain
synthesis run was also attempted, but its artifact failed its own evidence and
format requirements and was rejected rather than promoted into the design.

## Evidence from the first Claude inspection (2026-08-18)

- `~/.claude/history.jsonl` has 15,585 prompt records and is about 5.4 MB.
- `~/.claude/projects/` has 1,778 transcript JSONL files plus project auto-memory.
- Those transcript files total about 1.20 GB (the largest is about 106 MB), so
  a full-corpus model pass is neither proportionate nor safe. The 5.4 MB prompt
  index plus auto-memory is the default first-pass interaction source; transcript
  bodies are opt-in, streamed, and bounded.
- `~/.claude/CLAUDE.md` is 109 lines / 10.7 KB.
- The global file says to commit only when asked, while later user interactions
  explicitly establish `commit, merge, push, deploy` as a new default and repeat
  that correction in later projects. This is a concrete conflict to resolve,
  with scope and safety exceptions rather than two global absolutes.
- A large production incident-response chapter is injected globally even when
  the work is unrelated. It is a path/situation-specific candidate, not a global
  behavioral directive.
- Project memory contains useful feedback such as verifying one canary before
  expensive fan-out, only destroying resources created in the current session,
  avoiding false balance, and resisting unsupported abstraction.
- Raw prompt history can contain pasted HTTP headers, cookies, bearer-like
  material, and other secrets. Local redaction before LLM submission is a hard
  safety boundary, not an optional filter.
- Claude Code 2.1.224 supports `--permission-mode plan`; its changelog explicitly
  says the ultraplan feature was removed. A second maximum-effort clean-room plan
  review can reproduce the useful intent, but the removed command must not be
  represented as having run.
- Codex has a 73-line global `~/.codex/AGENTS.md`, a 3.85 MB history index, and
  559 rollout JSONL files totaling about 8.27 GB. Codex therefore uses the same
  prompt-index-first, rollout-opt-in ingestion boundary as Claude.
- Installed Kindex exposes stable local JSON reads through `kin search` and
  `kin show`; the integration can remain enabled without scraping `.kin` files.

## Authority model

Authority, scope, explicit supersession, and recency are separate dimensions. A
newer assistant-authored note does not outrank an older explicit user correction
merely because its mtime is newer. Conversely, an explicit newer user reversal
should supersede an older preference while keeping the old evidence in the
archive. Within the same authority class, an explicit replacement wins first;
otherwise the more-specific applicable scope wins before recency is considered.
A current-turn instruction beats historical preferences for that turn, but does
not silently become a durable global rule.

Default durable-evidence classes, highest authority first:

1. Explicit user correction/reversal with an identifiable antecedent.
2. Current version-controlled instruction, qualified by scope and provenance.
3. Repeated user preference inferred across independent sessions.
4. Deterministic outcome evidence tied to the proposed rule.
5. Active Kindex constraint/directive/decision with provenance and validity.
6. Agent auto-memory or summaries.
7. Assistant conclusions and unverified inferred lessons.

A one-off historical user imperative is session evidence, not automatically a
durable class-1 rule. Deterministic correction markers (`new rule`, `I said`,
`I asked`, `stop doing`, and close variants) raise vitality but do not promote
authority on their own. The synthesis decision must cite the antecedent and the
newer corrective event. Current invocation intent governs that run only unless
it is separately recorded as durable evidence.

Within the same authority and scope, prefer newer applicable evidence, but
include older supporting and conflicting evidence in the decision packet.
Recency is a decay weight, not an age cutoff. Repetition is corroboration only
when occurrences come from independently identified user events or sessions;
copied memories, summaries, and model-extracted candidates must not inflate
support. A model-extracted candidate remains derived class-7 material. Its
claimed authority comes only from the source event IDs and deterministic counts
that accompany it, never from the extraction model's wording.

The comparison key is deterministic: explicit `supersedes` edge, authority
class, scope specificity, recency weight, independent-session corroboration,
then evidence ID as a stable final tie-break. Scope is a lattice; incomparable
overlapping scopes remain unresolved rather than being ordered by confidence.
An evidence ID is content-derived from source kind, session ID, normalized
timestamp, and the original-content SHA-256. Exact repeated content within a
session is deduplicated before scoring, and corroboration counts distinct session
IDs. A source without a session ID contributes at most one corroboration unit,
regardless of copies.

## Product boundary

Meditate may discover and read:

- Claude: `CLAUDE.md`, `.claude/rules/**/*.md`, auto-memory markdown,
  `~/.claude/history.jsonl`, and project transcript JSONL.
- Codex: `AGENTS.md`, configured Codex instruction/memory paths, and Codex rollout
  JSONL where explicitly enabled.
- Kindex: active constraints, directives, decisions, and related provenance when
  `kin` is installed and the user has not disabled it.

Meditate writes only declared instruction targets. Histories, transcripts,
auto-memory, and Kindex are evidence sources and are never silently rewritten.
Symlinked targets are refused by default so an atomic rename cannot destroy the
link; a later explicit follow-through mode must archive both link and referent.

Configured Claude roots named `CLAUDE.md` or `CLAUDE.local.md` load official
`@path` imports recursively, consistent with Claude's documented
[memory semantics](https://code.claude.com/docs/en/memory). Imports outside inline
and fenced code resolve relative to the containing file; absolute and `~/` paths
are supported. The graph is limited to four hops and rejects dangling, circular,
over-depth, non-regular, or non-UTF-8 nodes before a model call. Imported content
is locally secret-scanned and enters the packet with `mutable=false`; it is not a
disposition target unless independently configured as writable.

This faithful import behavior is also a trust boundary. Operators must trust the
configured Claude roots and resulting import graphs: a relative, absolute, or
`~/` import may read any process-readable file it names. Import-only documents are
submitted as `mutable=false` and cannot be written through their import role.
Recognized secret shapes in imported content are redacted locally before provider
submission, but pattern redaction is not comprehensive and is not a filesystem
sandbox. Same-user filesystem compromise is outside Meditate's threat boundary.

Configured `.claude/rules/**/*.md` targets expose their simple frontmatter
`paths:` lists to the planner. Contextual conflicts relocate to an exact scoped
target before abstraction; an unscoped contextual relocation fails closed, and
Meditate never invents a glob. Codex target interpretation follows the official
[AGENTS.md loading semantics](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Command contract

- `meditate init`: write a commented TOML configuration.
- `meditate inspect`: local-only inventory, secret counts, candidate directive
  statistics, potential conflicts/overlaps, and token estimate. It makes no
  claim of semantic conflict unless a deterministic rule proves one, and makes
  no model call.
- `meditate plan`: build a sanitized evidence packet, run or replay the read-only
  semantic Analyst, optionally call the bounded Drafter, validate both structured
  outputs, and write a proposal/report. A fresh stable snapshot may use one Analyst
  call; its exact cache-backed repeats use zero calls. It changes no target.
- `meditate verify RUN_ID`: run the owner-authored suite that was excluded from
  planner input against control, predecessor, and candidate instruction bundles.
- `meditate decisions RUN_ID`: verify an immutable archive and render its one
  pending `a`/`b`/`c`/custom authority question plus shell-quoted response forms
  and argv arrays that retain the selected config path.
- `meditate decide RUN_ID REQUEST_ID (--choice a|b|c | --custom TEXT)`: record
  operator-asserted user authority and create a fresh read-only successor plan.
  With neither flag it prompts only on a TTY; it never edits the parent or a target.
- `meditate apply RUN_ID`: revalidate source hashes, archive every target plus a
  manifest, atomically replace targets, and emit an apply receipt.
- `meditate run`: inspect + plan. Cron uses this surface. An explicit `--apply`
  verifies a changed plan with the configured suite before requesting unattended apply.
- `meditate restore RUN_ID`: restore archived targets transactionally, refusing
  to overwrite post-run changes unless `--force` is given.
- `meditate cron`: print a locked cron entry or check its dependencies. Meditate
  never edits the user's crontab.

Dry-run is the default everywhere. A high-confidence secret match after local
redaction blocks the evidence packet before the first model call; model output is
scanned again before it is persisted. Model failure, parse failure, surviving
secret detection, missing evidence references, source drift, concurrent
execution, or a non-recoverable archive all fail closed and cannot produce a
rewrite. After every provider call, configured targets are reloaded and their
logical path/order, byte hash, existence bit, and mode must still match the
inspection; this prevents a stale proposal, not only a later stale apply.

## Model and budget contract

Support explicit provider and model targeting behind a provider interface. The
first live provider is Anthropic through its official Python SDK; OpenAI remains
an interface-backed extension rather than untested surface. Configuration
exposes maximum input tokens per call, maximum output tokens per call, total
input-token budget, total output-token budget, and maximum calls. No fallback
model is selected silently. Pre-call accounting uses a conservative upper bound;
actual usage is reconciled after every call, and budget exhaustion cancels later
stages. Truncated/max-token output is an invalid plan.

Anthropic planning uses the standard `ANTHROPIC_API_KEY` environment variable.
Clean-room Codex consumer verification requires `OPENAI_API_KEY`. Credential
values are read only at runtime and are never logged or persisted in plans,
reports, or archives.
No product source, test, documentation, or release artifact contains a private
company-specific credential name.

Large corpora use a bounded pipeline:

1. Local parsing, redaction, and lexical defect-candidate derivation.
2. Required Kindex searches when configured and installed, plus deterministic
   selection of high-signal historical events within budget.
3. One read-only semantic Analyst call on a fresh exact packet, or a zero-call
   replay of its content-addressed validated cache entry.
4. Zero Drafter calls when no admitted or missing-rule candidate exists; otherwise
   one Drafter call over the complete non-overlapping admitted candidate set plus
   bounded immutable context. The total default call budget is two.
5. Deterministic rendering and a post-image detector pass. A confirmed defect
   remaining in a changed post-image rejects the plan.
6. Independent owner-authored behavioral qualification on the consumer agent;
   that suite is not visible to the planner and cannot grant source authority.

Source readers process JSONL line by line, bound individual record size, and do
not need a corpus-sized in-memory parse. Malformed/unknown records are counted and
skipped; a partial or degraded corpus run is visible and blocks apply. The parser
version is bound into every archived plan so a validator change invalidates old
plans rather than silently reinterpreting them.

Kindex has a stronger boundary than optional history enrichment. When
`kindex.enabled=true` and the configured `kin` executable is installed, every
configured search and every selected node read is required. A command failure or
invalid JSON aborts before the planner with `kindex_required_failed`; Meditate does
not silently continue with a partial durable-memory view. When `kin` is absent,
the inspection reports `kindex_unavailable` without pretending it was queried.

Each target and aggregate summary records pre/post directive, UTF-8 byte, and
line counts with deltas, while changed and escalated directives remain separate
product measures. A Claude `CLAUDE.md` post-state over 200 lines is reported as
guidance status, not a vendor hard limit. The configured writable Codex
`AGENTS*.md` set must fit `project_doc_max_bytes` read from
`sources.codex_home/config.toml`, defaulting to 32,768 bytes. The result is
explicitly `configured_targets_only`; passing does not prove that every
cwd-specific Codex chain fits its runtime budget.

## Structured synthesis contract

Instruction documents are deterministically segmented using ATX
headings, top-level list items (nested items stay attached), blank-line-delimited
paragraphs, and opaque fenced code blocks. Pre-image directive IDs are minted
locally from the schema version, target identity, heading path, and normalized
content; the model may reference only existing IDs and cannot mint durable IDs.
Output plus local completion provides a disposition for every pre-image directive
exactly once: kept, replaced, removed, relocated, or escalated. The provider sees
only candidate IDs; local code adds all non-candidate IDs to `keep`.

The model returns JSON operations, not regenerated files. Unchanged spans are
copied byte-for-byte from the pre-image. A semantic replacement is not free
Markdown: it carries a typed `compiled_directive` record with a normative keyword,
rule, behavioral reason, scope, and optional boundary example. Meditate validates
and renders canonical Markdown locally. Byte-exact relocation may leave the record
empty; remove and report-only escalate must. This makes byte-identical unchanged
directives and no-op convergence construction properties rather than hopes about
model formatting.

The normative keyword is one of `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, or
`MAY`, used with RFC 2119 semantics. `SHOULD` is a strong defeasible default, not
a weaker spelling of `MUST`; the reason records why the rule exists so legitimate
exceptions can be derived without appending an exception list. Scope is mandatory.
One boundary example is optional only when it materially pins an applies/does-not-
apply edge. It remains untrusted prose, not an executable test.

Every change, including remove and escalate, must copy its `destination_target`
byte-for-byte from `allowed_targets`. The string is opaque: the model may not
expand `~`, normalize, absolutize, or invent a spelling. Replace, remove, and
escalate copy the source directive's target; relocate chooses another exact
configured target. Local allowlist validation still fails closed.

The model returns JSON with:

- kept directive IDs;
- replacement/removal/relocation/escalation operations with predecessor IDs, exact
  allowlisted destination, heading, typed compiled record, change reason, and evidence;
- exact evidence IDs and matching sanitized quotes for every change;
- unresolved conflicts that block apply;
- `decision_request: null` or one bounded unresolved authority collision;
- no model-authored report summary; local code derives defect and disposition output.

### Bounded authority-decision contract

A decision request is not a general ambiguity escape hatch. It is valid only
when at least two preserved directives support interpretations that are mutually
exclusive, materially change behavior, and authority plus temporal evidence
cannot decide precedence. A conservative local detector requires shared
subject/action grounding plus opposed polarity, or an explicit incompatible
alternative in the cited source material. Compatible instructions such as a
concise report and a diagnostics appendix are not a decision: current prose is
kept and the ambiguity remains unresolved. This structural detector is
deliberately fail-closed; it does not prove semantic incompatibility.

The competing cited evidence records must also have equal authority, equal
scope, and the same timestamp. If authority or scope differs, or one record is
newer, the normal precedence model already has an answer and the model may not
manufacture a user question to override it. Older evidence remains lineage; it
does not become an equal choice. Model-authored subjects are used only for
topical grounding; all polarity/incompatibility proof comes from the cited
source records.
Opposite-polarity inference requires at least two shared normalized meaningful
terms in the competing records that are relevant to the subjects. “Deploy to
staging” and “never deploy without tests” therefore remain compatible, while
“deploy automatically” and “never deploy automatically” qualify. Explicit
“cannot both” or “either/or” source language remains a direct path.

The raw model schema supplies `subject_a`, `subject_b`, affected directive and
evidence IDs, and exactly three ordered options. Each option contains a label,
consequence, rationale, and evidence IDs. Position zero is the model's advisory
recommendation and carries a recommendation rationale. The model cannot emit an
answer, selection, status, key, ID, fingerprint, rendered question, custom
choice, or recommended flag/index. All affected directives must be in `keep`, so
the blocked parent preserves their bytes.
Subjects, labels, consequences, rationales, and recommendation rationale are
single-line display fields; local validation rejects CR or LF. The provider-facing
schema is a stable, packet-independent Anthropic structural subset: it contains
no private target/directive/evidence enums or array/text bounds. Local validation
enforces exact target and known-ID membership, at least two directive/evidence
IDs, and exactly three options.

Local code assigns `a`, `b`, and `c`, marks only `a` recommended, adds the custom
escape, mints a request ID, and mints `conflict_fingerprint` only from stable
sorted directive/evidence IDs—not model prose. Only option `a` contains
`recommended: true`; options `b` and `c` omit the field. It renders exactly: “I’m
trying to resolve {subject_a} and {subject_b}. Would you prefer {A} (recommended),
{B}, {C}, or something else?” The recommendation is model-authored, advisory,
structurally grounded, and not semantically verified or selected by default.
Human CLI output first says the model-authored framing and recommendation are
untrusted and advisory and must be relayed as a question, not executed. JSON and
hashes preserve exact response text. Markdown HTML-escapes and then backslash-
escapes structural metacharacters in untrusted inline model/custom text; indented
target diffs use a separate path and are not backslash-modified.

`decision_required` blocks apply, is returned before generic `plan_blocked`, and
suppresses an apply command. The same structured request appears in plan/manifest,
JSON/Markdown report, plan/run JSON, and the `decisions` command. JSONL stores only
decision IDs, choice key, hashes,
and lineage depth. `decide` accepts an exact archived option or up to 2,000
characters of custom text; custom leading/trailing whitespace is preserved,
while empty, NUL-bearing, oversized, or recognized-secret text is rejected.
There is no manual review file to edit.

While pending, `meditate decisions` returns config-preserving argv arrays and
shell-quoted forms. Once a verified child exists, it returns `status=resolved`,
the successor run, and bound operator decision with no response forms. Operator
records use `response_kind=choice|custom`, `choice_key=a|b|c|null`, and define
`response_sha256` as SHA-256 of exact `response_text` UTF-8 bytes.

The successor freezes and replays the parent's already-sanitized evidence packet
and ignores history appended by asking and answering the question. `decide`
transmits the frozen parent context and exact selected/custom response to Anthropic,
whose response becomes the read-only successor plan. Before its provider call,
it re-reads only configured targets and Claude imports and requires
exact config, target path/order/hash/existence/mode, import graph,
prompt/parser/provider/requested-model contract. The API-returned resolved model
ID must also remain exact. The response, parent plan and packet hashes, and prior
request/fingerprint lineage are bound into the successor plan and manifest.
Re-asking the same locally grounded `conflict_fingerprint` fails, and at most three operator
choices may occur in a chain.

`decide`, apply, restore, and purge share the same mutation lock. Purging a
decision successor deletes its archive and exact run-ID reports, while a minimal
parent/request/successor/response hash marker survives in the tombstone and
summary log. The parent therefore remains resolved without retaining raw response
text. JSONL decision events are summary-only.

This record is operator-asserted user authority: identity is not authenticated or
attested, and the process cannot prove an invoking agent relayed the user's real answer. The choice
is scoped to its collision and cannot bypass protected directives, deterministic
safety, or higher-scope loaded authority. Structural validation and the choice
do not satisfy a changed successor's independent behavioral qualification.

`escalate` is report-only. It applies to one current directive, keeps its source
prose byte-for-byte at the same target and heading, names `hook` or `settings` as
an enforcement target, and supplies a non-empty deterministic check. It requires
at least two evidence records from two independent session/provenance groups.
Local code computes lineage depth as the number of independent cited groups;
model-supplied counts are neither requested nor trusted. Escalations are
`candidate_only`, attended, and counted separately from churn and changed
directives. Meditate never writes the hook or settings surface.

Every change records empty enforcement fields unless it is an escalation.
Relocations record either `contextual` or `organization`; contextual is valid
only when the destination is an exact configured `.claude/rules/` target with a
non-empty parsed `paths:` list. This is scope-before-merge: separate contexts are
not averaged into less precise prose.

Validation rejects unknown evidence IDs, evidence citations without a quoted
span matching the sanitized record, missing or duplicate directive dispositions,
unknown IDs, empty targets, unresolved conflicts, targets outside configuration,
size below the configured floor or beyond the configured ratio plus absolute
growth headroom, directive-count growth,
excessive churn, protected-section changes, unsupported urgency or operational
actions, self-attested verification, vague high-impact action authority, and any
surviving secret match. Byte delta is reported but cannot itself accept or reject
a plan. Re-running a well-formed source produces a byte-identical `stable_noop`,
not a near-zero rephrasing; after the first validated semantic result, exact repeats
also make zero provider calls.

Configured protected headings or marker-delimited blocks are copied through
byte-identically and are excluded from model mutation. They remain present in
the evidence packet so the proposed surrounding rules cannot contradict them.

## Workflow order and stage-local verification

Evidence that names several operational actions establishes coverage, never a
universal order. A high-impact replacement must bind itself to the exact order in
the loaded repository instructions and documented workflow. Before each action,
it may require only checks that are applicable, project-required, and available
before that action. Push-, PR-, and merge-triggered CI, approvals, and named-actor
handoffs are each evaluated at their own downstream stage, where they exist. Requiring all CI
before commit is invalid because some required CI cannot exist until after push,
PR creation, or merge. The validator rejects that form in every replacement or
relocation, not only when a rewrite newly introduces a high-impact action.

The restored-baseline evaluation run `20260818T231558Z-6e8e4703` is regression
evidence for this rule. It was rejected and never applied because its replacement
required all project tests and CI before commit and treated `commit`, `merge`, and
`push` as a universal sequence. Release review caught the bad form even though the
prior validator admitted it; the run is now a regression fixture the new
deterministic gate must reject. It does not qualify a successor directive
semantically; only a separate planner-blind owner-authored behavioral suite can.

## Fixed-point and defect contract

The objective is defect resolution, ordered by correctness, checkability, scope
precision, then concision. `pre_bytes`, `post_bytes`, and their delta are telemetry.
Output may grow when its typed rationale replaces brittle enumerated exceptions;
growth is visible and still subject to configured safety and consumer budgets, but
is not by itself a quality failure.

Deterministic preflight v4 has one confirmed defect class, `exact_duplicate`, and one
review-candidate class, `exception_lineage`. Exception lineage requires at least
two exception-bearing directives in the same heading with at least two shared
subject terms. Density and history overlap are never defects by themselves.
Review candidates are not declared wrong merely because the detector selected
them. This soundness distinction prevents a lexical false positive from making a
valid file permanently unacceptable. It is deliberately only the lexical stage.

The semantic Analyst receives the complete sanitized directive set plus the bounded,
temporally ordered interaction, memory, and Kindex packet. It may nominate exactly
seven classes: `contradiction`, `temporal_supersession`, `underspecified`,
`overspecified`, `wrong_scope`, `enforcement_candidate`, and `missing_rule`.
Every nomination has a semantic domain, current source IDs where applicable, submitted
evidence IDs, a behavioral intent, reason, and positive/negative
applicability boundary. Older evidence remains lineage; newer evidence wins only
after authority and applicable scope.

The Analyst is a stochastic candidate generator, not a validator. Local code rejects
unknown/protected sources, quotes shorter than 12 characters or two meaningful terms,
unsubmitted evidence, fewer than three shared intent-grounding terms,
unsupported supersession, one-group enforcement claims, and missing rules without
explicit durable evidence, active Kindex authority, or repeated independent correction
groups. A malformed top-level response aborts. Invalid individual nominations are rejected
and counted; valid siblings remain eligible, while an all-rejected response is
`semantic_analysis_inconclusive`, not `stable_noop`. It computes the nomination ID and
evidence/intent fingerprints. The Analyst
cannot draft a directive, choose a destination, assign authority, answer a collision,
or authorize a write.

Same-target, same-heading existing-rule nominations may join the bounded Drafter
candidate set. Local code inherits each admitted semantic candidate's complete evidence set and
rejects unrelated model-supplied IDs. A single-source semantic observation without external
evidence is report-only. Cross-target and cross-heading nominations are report-only. Missing
rules are a distinct report-only output: the Drafter may compile RFC-shaped candidate
prose, but local code assigns `write_authority=none`, excludes it from target rendering,
and requires later explicit promotion plus owner-authored qualification. The wire record cites
only an exact allowlisted nomination ID; local code inherits the nomination's immutable evidence
set. Version 0.3 has no promotion command; the operator must deliberately author or promote the
rule.
The compiled artifact cannot serve as its own corroborating evidence.

Promotion thresholds are explicit. A one-source existing-rule observation stays report-only
until external evidence or corroborating current sources exist. A missing-rule hypothesis
requires explicit operator promotion plus an owner-authored probe/counter-probe suite. An
escalation requires deliberate installation of the named enforcement surface plus qualification
against the consuming agent's actual interception limits.

The Drafter receives the complete non-overlapping admitted candidate set and only those
directive IDs; unrelated IDs are hidden and locally kept. A change cannot cross
candidate, heading, or subject boundaries. After deterministic rendering,
Meditate segments the complete post-image and rejects any changed plan that
leaves a confirmed defect. A review candidate may remain when the model keeps it.
Reports separately name detected, resolved, and unresolved classes and distinguish
`stable_noop`, `semantic_review_required`, `new_rule_hypotheses`, `enforcement_candidates`,
`reviewed_noop`, `drafter_rejected`, and a candidate requiring behavioral qualification.
`reviewed_noop` means the Drafter deliberately preserved an admitted hypothesis; the
nomination stays auditable but is not mislabeled as a confirmed unresolved defect.
`enforcement_candidates` preserves the prose and leaves the underlying defect unresolved until
the enforcement surface is deliberately installed and qualified. A rewrite rejected by an
explicitly allowlisted semantic-quality gate cannot be made acceptable by weakening that gate:
production runs archive an unchanged `drafter_rejected` receipt with the rejection code.
Authority, schema, secrecy, scope, candidate-boundary, and malformed top-level failures still
abort without publishing a plan.

The acceptance contract is executable: a well-formed fixture remains unchanged;
a defective fixture is corrected; both are run again and remain byte-identical;
a well-formed fixture is run ten times without drift (the first semantic result is
cached and exact repeats use no provider call); and a multi-defect fixture
must resolve every confirmed cluster in one successful plan. A partial multi-
defect rewrite fails with `non_idempotent_proposal` before an archive is published.

## Structural and semantic gates

Structural validation proves schema coverage, evidence-ID membership with locally materialized
exact sanitized text, allowlisted
destinations, deterministic typed rendering, bounded churn/safety size, secret
screening, archive integrity, and source/config/import-graph freshness. It does
not prove observable behavior.

Every changed plan and manifest records
`semantic_verification={"status":"required","method":"owner_defined_hidden_detector_suite_v2"}`.
`meditate verify` loads an owner-authored suite from an explicit path or config;
the suite bytes were never sent to the planner. Each probe/counter-probe runs in
control, pre-image, and post-image conditions for the configured repeat count.
The consumer sees neutral scenarios and opaque case references, not semantic case
IDs, action IDs, detector phrases, or assertions. It returns an ordered free-form
plan. Bounded local literal detectors derive observable actions after generation;
local assertions check required, forbidden, and ordered behavior. Verification
protocol v3 uses alphanumeric command boundaries and clause-local negation filtering,
so `npm test` cannot match inside `pnpm test` and a prohibition is not scored as an execution.
The verifier requires suite coverage for every changed source directive and writes immutable
suite/verification artifacts plus JSON and Markdown reports.

The receipt binds plan and pre-execution suite hashes, target pre/post hashes,
verifier prompt/schema/system-prompt hashes, consumer agent, consumer CLI version,
requested/resolved model, repeat count, case outcomes, and response hashes. Apply
reconstructs those bindings and accepts only a passed exact receipt.
A candidate passes only when it satisfies every case on every repeat, no case's
post count falls below its predecessor count, and each designated control is
strictly weaker than the candidate. A predecessor miss is reported as a baseline
gap; a candidate repair is reported as an improvement. Baseline imperfection does
not excuse a candidate miss or create a veto over an all-green, non-regressing
candidate. Codex verification replaces ambient `CODEX_HOME` with a fresh private
directory, ignores user config and rules, and requires `OPENAI_API_KEY` so the
control cannot inherit global instructions or memory.

A pass proves only the owner-selected cases on the recorded consumer/version/model;
it is not universal equivalence. The planner cannot write or see its oracle.

No-change plans use `semantic_verification.status=not_applicable`; this means no
consumer-agent suite is required, not that a fresh snapshot skipped semantic analysis.
An exact validated Analyst result is cached by config, packet, model, prompt, schema,
and parser identity. Fresh semantic planning permits at most one Analyst and one
Drafter call (`llm.max_calls = 2` by default). New configs use aggregate input/output
defaults of 160,000/16,384 tokens across both; existing explicit budgets remain unchanged.
Unattended
apply remains a separate authority classification: it needs the explicit config
switch, attended-history threshold, a low-blast-radius replacement-only shape,
and the same passed receipt. Evidence allowlisting and model confidence cannot
substitute for behavioral qualification.

### v0.3.0 live semantic receipts

Restored Claude run `20260819T200834Z-321749c4` found four nominations (two enforcement,
one missing rule, one underspecified), admitted two as mutable, one report-only, and one
suggestion-only, and compiled one report-only escalation plus one missing-rule suggestion.
Outcome `enforcement_candidates` preserved all 65 directives and 10,703 bytes at SHA-256
`441fe6e9af0302329b753fa9138f6a5fc5c556637991bfec679700adea1acb76`.

Restored Codex run `20260819T200912Z-ef9020d0` found five nominations (three
underspecified, one wrong-scope, one enforcement), with three mutable and two report-only.
The Drafter introduced unsupported force, so `drafter_rejected` preserved all 33 directives
and 4,276 bytes at SHA-256
`0dd415bb140f10fe95c70005e33ca523f1ed60419a79bbfeabdf9a31446c6b63`.
Both exact-repeat receipts used the Analyst cache and current Analyst v4/parser v5 plus
Drafter v16/parser v32. No target changed or received behavioral qualification; these receipts
prove the nomination/compilation/rejection boundary, not behavioral equivalence.

A separate disposable package-manager fixture exercised an admitted semantic rewrite. Claude
plan `20260819T204620Z-53e25b49` and Codex plan `20260819T204859Z-ab0a357e` each compiled the
temporal `npm`→`pnpm` correction. Claude Code 2.1.224/`claude-sonnet-4-6` and Codex CLI
0.147.0/`gpt-5.6-sol` each passed three repeats of two trigger probes and one counter-probe.
Verification SHAs were
`608c186ffa650fd7f6373c586811e926d299b48ca1da378b0ca4de5d29ee8c8c` and
`5aa093c94010685ecf9278eafe06b12fda5cc628f0019b5e8e4fc3182cc3f241`. Only the disposable
Codex-qualified plan was applied. Its target reached SHA-256
`838ce9afe2405bb6ff999dc64722cc89191ece65b35b786ab6dd2615e0135f2b`; repeat run
`20260819T205423Z-f3b11c4a` was byte-identical `reviewed_noop`, with the historical nomination
preserved for audit and zero confirmed unresolved defects. Real Claude and Codex instruction
files remained unchanged.

### Historical v0.2.0 qualification evidence

The restored live Claude and Codex files first produced byte-identical zero-call
`stable_noop` runs `20260819T161206Z-d6dbad85` and
`20260819T161218Z-834d615b`. Their SHA-256 values remained
`441fe6e9af0302329b753fa9138f6a5fc5c556637991bfec679700adea1acb76` and
`0dd415bb140f10fe95c70005e33ca523f1ed60419a79bbfeabdf9a31446c6b63`.

On disposable copies with one inserted exact duplicate:

- Claude plan `20260819T165955Z-1987f9ef` changed 67 directives/11,606 bytes to
  66 directives/11,378 bytes. Claude Code 2.1.224 with `claude-sonnet-4-6`
  scored pre 18/18, post 18/18, and control 0/18. Verification SHA
  `4f1851d08ddb4047243f6978204bda6b29ad59d245dd744a020e31321eb878aa`
  authorized attended disposable apply; second run
  `20260819T170602Z-39e3bba4` was a byte-identical zero-call no-op.
- Claude run `20260819T165129Z-70f323ea` scored pre 18/18 and post 17/18 after a
  lower-position rewrite. It failed closed and was never applied.
- Codex plan `20260819T171655Z-546b02cd` changed 35 directives/5,269 bytes to
  34 directives/4,830 bytes. Codex CLI 0.147.0 with `gpt-5.6-sol` in a fresh
  private `CODEX_HOME` scored post 18/18 and control 0/18. One predecessor repeat
  miss was repaired and recorded as both a baseline gap and candidate improvement.
  Verification SHA
  `0376960893146c8f9f29559da0fee2a9f14a0b182eae3759689dda2b0e915b1d`
  authorized attended disposable apply; second run
  `20260819T171954Z-d68b18c5` was a byte-identical zero-call no-op.

The historical evidence is bounded to the six owner-authored Kindex cases. The new
disposable receipt qualifies only its three named package-manager cases. Together they support
the fixed-point, semantic-compilation, and verifier mechanisms on the recorded consumers; they
are not universal behavioral equivalence.

## Archive and transaction contract

Archives use SHA-256 named blobs within a sortable, collision-resistant UTC run
directory under the XDG data directory. A run archive contains original target bytes,
modes, hashes, resolved paths, the complete sanitized evidence packet with stable
IDs, source-location/content hashes for evidence not copied in full, proposal
hashes, configuration hash, model/provider, usage, and timestamps. Given the
archive and proposal, a human must be able to reconstruct why each directive
replaced its predecessors. Before apply, archive integrity is read back and
verified. Every persisted artifact declares `schema_version`; manifests use
canonical JSON (UTF-8, sorted keys, no floats) and validate run IDs before path
construction. Replacement realpath-checks the allowlist, refuses symlinks and
non-regular files, uses a same-directory temporary file, fsync, preserved mode,
atomic rename, and directory fsync. Archives are mode 0700/0600, world-writable
state roots are refused, and running as root against another user's home is
refused. Multi-file apply has an acknowledged non-atomic window, rolls back
already changed targets if a later write fails, and emits a machine-readable
recovery receipt if rollback itself fails.

Plans and manifests also bind the validated Claude import graph before and after
the proposal, including every graph node's file hash and a canonical graph
digest. Apply recomputes the before graph before target writes and the after graph
after writes. A pre-write mismatch fails closed; a post-write mismatch enters the
existing rollback path. Reports and the append-only JSONL summary expose the same
model/prompt provenance, semantic status, aggregate metrics, and per-target
pre/post product counts without copying raw imported content into inspection JSON.

Apply state is persisted atomically through `planned`, `applying`, `applied`,
`rolling_back`, `rolled_back`, and `recovery_required`; restore treats non-clean
terminal states as explicit operator-recovery cases. Both apply and restore use
`lstat` and refuse symlinks, including forced restore.

Restore uses only the paths captured in the run manifest, not a possibly changed
current configuration. It refuses when the live target differs from the post-apply
hash unless explicit `--force` is supplied; a forced restore records the discarded
manual edit into a new recovery archive before overwriting it. It never silently
treats later hand edits as Meditate output or destroys bytes that were not first
archived.

Reports go under the XDG state directory as JSON plus concise Markdown. They log
counts, hashes, conflict decisions, token usage, redaction counts, changed targets,
archive/restore instructions, and validation outcomes. They never log API keys,
raw secrets, or unrestricted transcript text.

## Cron contract

Cron execution uses an advisory file-descriptor lock, deterministic config path,
explicit working directory, bounded runtime, and an optional mode-0600 env file
resolved at runtime. `meditate cron` emits an entry and `cron --check` validates
the resolved executable, config, profile, current key source, Kindex command, and
target paths; Meditate does not install the entry itself.
The generated entry defaults to `run` without apply. Unattended mutation remains
disabled by default. `cron --apply` renders a `run --apply` command that first
executes the configured owner suite for a changed plan and stops on failure;
the normal unattended config and probation gates still apply. Evidence
allowlisting, a copied cron line, and attended probation do not constitute
behavioral qualification.

The initial local overlap detector has named, bounded heuristics only:
`negation_pair` for the same normalized subject with opposite modal patterns,
and `scope_overlap` for intersecting scopes with a shared normalized subject.
Reports call these overlap candidates, not proven semantic conflicts. Offline
token estimates use a documented conservative bytes heuristic and are labeled
with the estimator version; the provider enforces configured limits again at the
call boundary.

## Release and distribution

Package metadata and the runtime version are synchronized at `0.3.0`. The
canonical public distribution surface is the versioned wheel attached to the
`v0.3.0` GitHub Release:

`https://github.com/jmcentire/meditate/releases/download/v0.3.0/meditate_agent-0.3.0-py3-none-any.whl`

The repository CI checks Ruff, strict mypy, pytest across supported Python
versions, and an isolated wheel build. It does not publish. PyPI publication is
not claimed; no PyPI project, credential, or workflow is configured.
Contributors retain the local editable-install path.

## Why not a linter?

Landscape snapshot: 2026-08-18. Adjacent tools already provide substantive
instruction-health features. [claudelint](https://claudelint.com/) advertises 116
rules across 10 categories and plugin-assisted restructuring;
[cclint](https://www.npmjs.com/package/@felixgeelhaar/cclint) covers imports,
hierarchy conflicts, duplicates, and fixes; [AgentLint](https://github.com/0xmariowu/AgentLint)
and [agentlinter.com](https://agentlinter.com/) describe static, AI, and session
checks plus fixes; [Reporails](https://reporails.com/) advertises local
deterministic diagnostics and healing. Meditate does not claim these tools do
nothing. Its narrower product distinction is exact disposition coverage for every
configured pre-image directive, cited semantic nomination from temporal interaction
and Kindex evidence, report-only missing-rule hypotheses, and content-addressed,
recoverable exact-hash apply.

The exact purported paper title `A Taxonomy of Agent Instruction Failures` by
Gloaguen et al. was not verified and is not load-bearing. The verified paper is
[`Coding Agents Don't Know When to Act`](https://arxiv.org/abs/2605.07769).

## Acceptance evidence

- Synthetic fixtures prove Claude and Codex parsing and temporal order.
- Redaction tests cover cookies, authorization headers, API keys, session IDs,
  private keys, and URL credentials.
- Conflict tests prove newer explicit reversals supersede older directives while
  older evidence remains in lineage.
- Repeated copied memory does not inflate vitality.
- Prompt assembly cannot exceed configured budgets.
- Plan is read-only; apply requires an existing validated plan.
- Apply archives before write, detects TOCTOU, writes atomically, and restores.
- Partial multi-file failure rolls back.
- Cron lock prevents overlap and reports skipped runs.
- A sanitized first-pass inspection of the real Claude state completes without
  placing raw interactions or secret values in repo or reports.
- The first attended live pass reads 15,531 unique events, selects 180, excludes
  nine secret-bearing records wholesale, changes one of 65 directives, and leaves
  an exact SHA-256-bound pre/post archive plus restore receipt path.
