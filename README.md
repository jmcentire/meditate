# Meditate

[Documentation](https://jmcentire.github.io/meditate/) ·
[Privacy](PRIVACY.md) ·
[Design brief](docs/design-brief.md) ·
[Changelog](CHANGELOG.md)

Current package version: **0.3.0 alpha**.

Meditate's product goal is a locally operated behavioral-contract compiler and policy
router for the directives Claude Code and OpenAI Codex load. Version 0.3 delivers two
separate production boundaries: an evidence-grounded semantic Analyst that nominates
possible defects, and a bounded directive compiler that can act only on locally admitted
candidates. It reads current prose together with temporally ordered interactions and
Kindex—an optional local persistent knowledge graph exposed through `kin`—then identifies
contradictions, supersession, under- and over-specification, wrong scope, enforcement
candidates, and evidence-backed missing-rule hypotheses. Missing rules are still
report-only; v0.3 does not yet promote them into the durable contract. Its fixed point is
stability, not shrinkage: a well-formed file is a successful, byte-identical no-op.

> **Authority before confidence.** A fluent or high-confidence rewrite has no
> authority of its own. Current instructions, explicit corrections, applicable
> scope, and named handoff boundaries come before model confidence.

Meditate does not let an LLM directly regenerate or write your instruction file. It:

1. segments configured instruction files into locally identified directives;
2. streams Claude/Codex history and auto-memory through local secret detection;
3. preserves temporal order and scores recency without an age cutoff;
4. gives repeated, independently observed user corrections more weight while
   keeping older supporting and conflicting evidence in the packet;
5. requires configured Kindex searches when `kin` is installed, failing before planning
   rather than silently omitting that durable evidence source;
6. validates Claude `@path` imports and sends imported documents only as sanitized,
   explicitly read-only context;
7. runs a separate read-only semantic Analyst over the complete sanitized directive
   set and selected evidence; the Analyst may nominate seven bounded candidate classes
   but cannot draft prose, choose a path, assign authority, or authorize a write;
8. validates every Analyst citation and source ID locally, admits only same-target,
   same-heading existing-rule candidates to the mutable boundary, and keeps missing
   rules and cross-scope findings report-only;
9. asks an exact model for a five-disposition operation list: keep, replace,
   remove, relocate, or report-only escalate. Semantic replacements are typed records
   containing an RFC 2119 keyword, rule, rationale, scope, and optional boundary example;
10. accepts model citations only as exact allowed evidence IDs, materializes their
   substantive sanitized text locally (at least 12 characters and two meaningful
   terms), and validates every destination, size/churn bound, and secret scan locally,
   including external verification and explicit authority
   boundaries for newly introduced merge/release/deploy actions;
11. turns a genuine unresolved authority collision into one bounded
   `a`/`b`/`c`/custom question instead of letting the model choose for the user;
12. binds both stage prompts/models, the semantic artifact, import graphs, semantic
   status, and pre/post directive/byte/line metrics into the plan hash;
13. runs an owner-authored, planner-blind probe/counter-probe suite against control,
   predecessor, and candidate instructions before any changed plan can apply; and
14. renders unchanged spans byte-for-byte, archives pre/post images, and writes only
   after the verification receipt and exact plan hash are accepted.

Raw histories are read-only. A history record with a high-confidence credential
shape is excluded wholesale before any model call. Reports and archives live in
private XDG data/state directories, not this repository.

## Install

### GitHub Release wheel

The canonical public distribution surface for v0.3.0 is the versioned wheel
attached to its GitHub Release. After that release asset is published:

```bash
python3 -m venv .venv
.venv/bin/pip install https://github.com/jmcentire/meditate/releases/download/v0.3.0/meditate_agent-0.3.0-py3-none-any.whl
.venv/bin/meditate init
```

PyPI publication is not claimed, and CI builds but does not publish artifacts.

### Contributor editable install

```bash
git clone https://github.com/jmcentire/meditate.git
cd meditate
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/meditate init
```

The default config is `~/.config/meditate/config.toml`. It targets
`~/.claude/CLAUDE.md`, reads Claude's prompt index and auto-memory, leaves full
transcript bodies disabled, and enables Kindex when `kin` is available. Add
`~/.codex/AGENTS.md` to `targets` and `codex` to `sources.agents` to include
Codex. Every writable file must appear in the exact `targets` allowlist.
Fresh semantic planning can use one Analyst call and one Drafter call, so the v0.3
default is `llm.max_calls = 2`; new configs default aggregate input/output budgets to
160,000/16,384 tokens across both. Existing explicit budgets remain unchanged and
fail closed if they cannot cover a required Drafter call. An exact Analyst cache hit
consumes no provider call.

Configured `.claude/rules/**/*.md` targets may declare a simple YAML frontmatter
`paths:` list. Contextual guidance may relocate only into one of those exact,
preconfigured scoped targets; Meditate never invents a glob. For configured
Claude roots named `CLAUDE.md` or `CLAUDE.local.md`, official `@path` imports are
resolved recursively to four hops. Relative, absolute, and `~/` imports are
supported; dangling, circular, over-depth, non-regular, and non-UTF-8 graphs fail
before the model call. See Claude's official
[memory semantics](https://code.claude.com/docs/en/memory) and Codex's official
[AGENTS.md semantics](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

**Import threat boundary.** Meditate faithfully follows each configured Claude
root's documented relative, absolute, and `~/` `@path` imports, so operators must
trust those roots and their import graphs. An import may read any process-readable
file it names. Import-only documents are submitted as immutable context and cannot
be written through their import role. Recognized secret shapes in imported content
are redacted locally before provider submission, but pattern redaction is not
comprehensive and is not a filesystem sandbox. Same-user filesystem compromise is
outside Meditate's threat boundary.

Anthropic planning calls use the standard `ANTHROPIC_API_KEY` environment
variable. Clean-room Codex consumer verification requires the standard
`OPENAI_API_KEY` variable. Provider-specific credentials are read only at runtime
and are never written to plans, reports, or archives.

## Workflow

```bash
# Local-only inventory. No model call and no target mutation.
meditate inspect --json

# Read evidence and create a recoverable proposal. Still no target mutation.
meditate plan --model claude-sonnet-4-6 --max-output-tokens 8192

# For a changed plan, run the owner-authored suite the planner never received.
meditate verify 20260818T120000Z-deadbeef \
  --suite sentinels/claude-kindex-v2.json --agent claude --repeats 3

# If the plan has a genuine authority collision, show the exact bounded question.
meditate decisions 20260818T120000Z-deadbeef

# Relay the user's explicit answer into a fresh read-only plan; custom is also valid.
meditate decide 20260818T120000Z-deadbeef decision-0123456789abcdef --choice a

# Review the Markdown report path printed above, then bind approval to its hash.
meditate apply 20260818T120000Z-deadbeef --approve PLAN_SHA256

# Restore only if the live file is still the applied post-image.
meditate restore 20260818T120000Z-deadbeef

# Preserve later hand edits before forcing a restore.
meditate restore 20260818T120000Z-deadbeef --force
```

`plan` is always read-only. `apply` consumes a plan once, rechecks the config and
source hashes, verifies every archived blob, and uses same-directory atomic
replacement. If a multi-file write fails, it restores every target found at the
post-image hash; ambiguous drift produces a recovery receipt instead of guessing.
Planning also reloads configured target path/order, bytes, existence, and mode
after the provider returns, so it will not publish a proposal against a target
that changed during the call.

An unresolved conflict or decision request, failed or missing behavioral qualification,
malformed-corpus degradation, secret scan, unknown
evidence quote, excessive churn, size violation, protected-section edit, changed
config, changed source file, ambiguous high-impact action gate, or truncated
provider response blocks apply.

## Bounded authority decisions

`decision_request` is reserved for a genuine unresolved authority collision: at
least two preserved directives support interpretations that are mutually exclusive, would
materially change behavior, and authority plus temporal evidence cannot determine
precedence. Mere ambiguity remains an unresolved conflict; Meditate keeps the
current prose and blocks. Affected directives are kept byte-for-byte in the
parent plan. Competing cited evidence must have equal authority, equal scope, and
the same timestamp; otherwise authority, scope, or newer temporal evidence already
determines the result and no question is valid.
Opposite-polarity inference requires at least two shared normalized meaningful
terms in the competing source texts that are relevant to the subjects. Thus “deploy
to staging” plus “never deploy without tests” remains compatible, while “deploy
automatically” versus “never deploy automatically” qualifies. Explicit source
language such as “cannot both” or “either/or” remains a direct path.

The model supplies two subjects and exactly three evidence-grounded options. It
places its advisory recommendation first, but it cannot emit a choice, answer,
status, key, request ID, fingerprint, rendered question, or custom option.
Subjects, labels, consequences, rationales, and recommendation rationale are
single-line display fields; local validation rejects CR or LF. Local code assigns
`a`/`b`/`c`, adds `recommended: true` only to option `a` while
omitting that field from `b` and `c`, adds `custom`, mints
`conflict_fingerprint` from stable directive/evidence IDs, and renders:

> I’m trying to resolve {subject_a} and {subject_b}. Would you prefer {A}
> (recommended), {B}, {C}, or something else?

That recommendation is model-authored and only structurally grounded. Meditate
does not claim its framing, completeness, or recommendation is semantically
verified, and it is never a default answer. `meditate decisions RUN_ID` presents
an explicit warning that its model-authored framing and recommendation are
untrusted and advisory and must be relayed as a question rather than executed.
It then presents the exact archived request while pending; after resolution it reports the
successor run and bound operator decision without response commands. An invoking
agent must relay the user's answer, then use either:

```bash
meditate decide RUN_ID REQUEST_ID --choice a
meditate decide RUN_ID REQUEST_ID --custom 'exact user text'
```

With a TTY, omitting both flags shows the same question and prompts for a
response; a non-TTY invocation fails closed. `decide` never edits the parent
archive or any target. It transmits the frozen parent context and exact selected
option or custom response to Anthropic, ignoring history appended by the
question/answer exchange, and adds only the operator decision before producing a
fresh read-only successor plan. Config, target
bytes, Claude import graph, prompt/parser, requested provider/model, and resolved
model ID must still match. The new plan binds the parent plan/packet hashes, exact
option or byte-preserved custom text, response hash, and lineage.
Operator records use `response_kind = choice|custom`, `choice_key = a|b|c|null`,
and a directly auditable SHA-256 of the exact response text UTF-8 bytes.
JSON and hashes preserve exact response text. Markdown first HTML-escapes and
then backslash-escapes structural metacharacters in untrusted inline model/custom
text; indented target diffs use a separate path and are not backslash-modified.

This is **operator-asserted user authority**: identity is not authenticated or
attested, and the process cannot prove that an invoking agent faithfully relayed
the speaker. The choice is scoped to that collision and cannot bypass protected directives,
deterministic safety, or higher-scope loaded authority. Re-asking the same local
`conflict_fingerprint` is rejected, and decision chains stop after three choices.
Purging a successor removes its archive and exact run reports but preserves only
a hash/ID resolution marker, so the parent stays resolved and cannot be asked
again. Applying a pending parent fails specifically with `decision_required`
before the generic blocked-plan path. No manual artifact editing or model
self-answering path exists. A successor that changes a target still requires its own
planner-blind owner-suite receipt.

## Workflow order and stage-local verification

Cited operational-action lists establish coverage, never a universal sequence.
Meditate requires a proposed high-impact directive to follow the exact order in
the loaded repository instructions and documented workflow. Before each action,
only checks that are applicable, project-required, and available before that
action are prerequisites. Push-, PR-, and merge-triggered CI, approvals, and
named-actor handoffs are each evaluated at their own stage, where they exist; all CI must not be
required before commit. Every replacement or relocation containing that unsafe
universal gate is rejected, even when the underlying remote actions already
existed in the source.

The restored-baseline evaluation run `20260818T231558Z-6e8e4703` was rejected and
never applied because it required all project tests and CI before commit and
treated `commit`, `merge`, and `push` as a universal order. Release review, not
the prior validator, caught that form; the run is now a concrete regression
fixture the stage-local structural gate must reject. It is not proof that any
replacement is behaviorally equivalent. Behavioral qualification is a separate
consumer-agent run, not a claim made by the planner or structural validator.

## The fixed point is stability

Meditate resolves identified defects; it does not optimize for smaller files.
Byte count is telemetry. A rationale that replaces four brittle exception clauses
may make a directive larger and still be the correct result. The configured size
floor, absolute growth headroom, Claude line guidance, and Codex byte budget remain
safety boundaries, not quality targets.

The deterministic lexical preflight distinguishes:

- `exact_duplicate`, a confirmed local defect; and
- `exception_lineage`, a conservative same-heading, shared-subject review candidate,
  not proof that the prose is wrong.

Density, file age, history overlap, and byte count do not create a defect. Lexical
preflight is not the whole detector: a separate semantic Analyst sees the complete
sanitized directive set, temporal interactions, memory, and required Kindex evidence.
It may nominate `contradiction`, `temporal_supersession`, `underspecified`,
`overspecified`, `wrong_scope`, `enforcement_candidate`, or `missing_rule` in an
explicit semantic domain. The first exact snapshot may therefore consume one Analyst
call even when the correct result is `outcome=stable_noop`. Its validated result is
content-addressed; exact repeats make no Analyst call, make no Drafter call, preserve
target bytes, and record `semantic_verification.status=not_applicable`.

The distinction in reports is deliberate. `stable_noop` means neither local preflight
nor the semantic Analyst nominated work. `semantic_review_required` means the Analyst
found a report-only issue that local policy did not admit to mutation.
`new_rule_hypotheses` means interaction or active Kindex evidence supports a missing
behavior, but no target bytes changed. `reviewed_noop` means an admitted candidate was
examined and deliberately preserved; the hypothesis remains auditable but is not mislabeled
as a confirmed unresolved defect. `enforcement_candidates` means one or more directives
were preserved in prose and reported for hook/settings enforcement; the underlying defect remains
unresolved until that enforcement is deliberately installed and qualified.
`semantic_analysis_inconclusive` means every
Analyst nomination failed local validation; it is never reported as a clean file.
`drafter_rejected` means semantic nominations survived, but the proposed rewrite failed an
explicitly allowlisted semantic-quality gate; Meditate archives the analysis and rejection code
while preserving every target byte. Authority, schema, secrecy, scope, and candidate-boundary
violations still abort before publication. None is disguised as another. A malformed top-level
response still aborts, while invalid individual Analyst nominations are rejected and counted
without discarding valid siblings.

A successful changed plan receives the complete non-overlapping admitted candidate set.
Each change stays within one heading and subject. Local code renders the entire
post-image and rejects it with `non_idempotent_proposal` if a confirmed defect is
still detectable. The acceptance suite covers an unchanged well-formed fixture,
a corrected defective fixture, a second invocation over each result, ten no-drift
iterations, and a multi-defect fixture that must reach its fixed point in one
successful plan.

## Semantic nominations are not authority

The Analyst returns hypotheses, not defects or directives. Local code rejects unknown
or protected directive IDs, invented evidence IDs, minimal evidence records, intent with fewer
than three shared grounding terms, unsupported temporal claims, one-observation
enforcement claims, and missing-rule
claims without explicit durability, an active Kindex directive, or repeated independent
corrections. Stable local IDs and evidence/intent fingerprints are computed after
validation; the model cannot mint them.

Same-target, same-heading nominations about existing prose may become bounded Drafter
candidates. Cross-target and cross-heading findings remain report-only because scope
cannot be averaged safely. For admitted semantic changes, local code inherits the complete
candidate evidence set; any model-supplied evidence IDs must belong to that set. A single-source
semantic observation without external evidence is report-only rather than mutation authority. A `missing_rule`
has no source directive and remains a
report-only RFC-shaped suggestion with `write_authority=none`; it is never rendered into
the proposed file and cannot be applied. The Drafter returns only an exact allowlisted
nomination ID; local code inherits that nomination's immutable evidence set instead of asking
the model to copy provenance. Promotion is a later explicit authority act, and a promoted rule
still needs owner-authored behavioral qualification. Conversation
review is therefore load-bearing evidence without becoming silent policy creation.

Promotion thresholds are explicit:

- an existing-rule nomination grounded in only one current source stays report-only until
  external evidence or corroborating current sources establish a bounded review candidate;
- a missing-rule hypothesis stays report-only until an operator explicitly promotes it and an
  owner-authored probe/counter-probe suite qualifies the resulting directive; and
- an escalation stays prose plus a report until an operator deliberately installs the named
  enforcement surface and qualifies that enforcement within the consuming agent's limits.

When Kindex is enabled and `kin` is installed, every configured search and requested
node read is required. A failure aborts with `kindex_required_failed`; Meditate does not
fall back to a weaker corpus while pretending it reviewed durable knowledge.

## Typed directive compilation

The provider cannot return replacement Markdown. For each semantic replacement it
must return exactly five fields:

- `normative_keyword`: `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, or `MAY` with
  RFC 2119 semantics;
- `rule`: the concrete behavior;
- `reason`: the rationale that generates legitimate exceptions;
- `scope`: where the rule applies; and
- `boundary_example`: one optional example only when it materially pins the edge.

Local validation rejects missing fields, multiline display data, invalid keywords,
and rules that smuggle their own Markdown marker or keyword. Meditate renders a
canonical Markdown block. The boundary example remains untrusted prose—not an
executable test—and the owner suite remains the behavioral oracle. Byte-exact
single-directive relocation and report-only remove/escalate operations use an
empty compiled record.

## Structural validation and behavioral qualification

Every changed plan begins with
`semantic_verification={"status":"required","method":"owner_defined_hidden_detector_suite_v2"}`.
The owner-authored JSON suite is not included in planner input. `meditate verify`
runs every probe in three conditions—control, complete predecessor bundle, and
complete candidate bundle—on the named Claude or Codex consumer CLI. The consumer
sees only neutral scenarios with opaque case references and returns free-form
ordered plans; action IDs, detector phrases, and required/forbidden/order assertions
remain private local data. Bounded literal detectors score the plans after generation.
Detector protocol v3 uses alphanumeric command boundaries and clause-local negation filtering,
so `npm test` does not match inside `pnpm test` and a prohibition such as “do not run npm test”
is not counted as an execution.
The receipt binds the pre-execution suite hash, verifier prompt/schema/system-prompt
hashes, agent/version, requested and resolved model, target hashes, plan hash,
responses, and pass counts. Apply independently reconstructs and verifies it.

A pass requires the candidate to satisfy every case on every repeat, forbids any
per-case regression from predecessor to candidate, and requires each designated
control to remain strictly weaker than the candidate. A predecessor miss is
reported as `baseline_gap_cases`; a candidate that repairs it is reported as
`candidate_improvement_cases`. Neither excuses a candidate miss. Codex verification
replaces ambient `CODEX_HOME` with a new private directory, ignores user config and
rules, and requires `OPENAI_API_KEY`, so the control cannot inherit global
`AGENTS.md`, memories, or configuration.

A pass proves only the recorded cases on the recorded consumer agent/version/model.
It is not universal behavioral equivalence, and the planner cannot select the
criteria on which it is graded. Missing coverage for any changed source directive
fails. Unchanged target bytes need no consumer-agent verification, but a fresh exact
snapshot may still need its read-only semantic Analyst pass. Unattended mutation additionally
requires the explicit config switch, probation history, and a structurally
low-blast-radius plan; a verification receipt alone grants no ambient authority.

### v0.3.0 live semantic receipts

- Restored Claude baseline run `20260819T200834Z-321749c4` found four semantic
  nominations: two enforcement candidates, one missing rule, and one underspecified rule.
  Local admission produced two mutable, one report-only, and one suggestion-only record.
  The Drafter returned one report-only escalation and one missing-rule suggestion, yielding
  `enforcement_candidates`; the 65-directive/10,703-byte target remained byte-identical at
  SHA-256 `441fe6e9af0302329b753fa9138f6a5fc5c556637991bfec679700adea1acb76`.
- Restored Codex baseline run `20260819T200912Z-ef9020d0` found five semantic nominations:
  three underspecified, one wrong-scope, and one enforcement candidate. Three were mutable and
  two report-only. The Drafter added unsupported force, so the run was `drafter_rejected`; the
  33-directive/4,276-byte target remained byte-identical at SHA-256
  `0dd415bb140f10fe95c70005e33ca523f1ed60419a79bbfeabdf9a31446c6b63`.
- Both receipts used the cached Analyst result on an exact repeat and current Analyst prompt
  v4/parser v5 plus Drafter prompt v16/parser v32. Neither changed a target or ran consumer-agent
  verification. They demonstrate semantic nomination, report-only compilation, deterministic
  rejection, and fixed target bytes—not behavioral equivalence.
- A separate disposable package-manager fixture exercised the full semantic path. Claude plan
  `20260819T204620Z-53e25b49` and Codex plan `20260819T204859Z-ab0a357e` each replaced an older
  `npm` directive with a typed, evidence-grounded `pnpm` directive. Claude Code 2.1.224 with
  `claude-sonnet-4-6` and Codex CLI 0.147.0 with `gpt-5.6-sol` each passed all three repeats of
  two trigger probes plus one counter-probe. Verification SHAs were
  `608c186ffa650fd7f6373c586811e926d299b48ca1da378b0ca4de5d29ee8c8c` and
  `5aa093c94010685ecf9278eafe06b12fda5cc628f0019b5e8e4fc3182cc3f241`. Only the disposable
  Codex-qualified plan was applied. Its target reached SHA-256
  `838ce9afe2405bb6ff999dc64722cc89191ece65b35b786ab6dd2615e0135f2b`; repeat run
  `20260819T205423Z-f3b11c4a` was byte-identical and reported `reviewed_noop` with the historical
  nomination preserved for audit and zero confirmed unresolved defects. No real Claude or Codex
  instruction file was changed.

### Historical v0.2.0 live qualification receipts

- The restored live Claude target (SHA-256
  `441fe6e9af0302329b753fa9138f6a5fc5c556637991bfec679700adea1acb76`)
  produced zero-call `stable_noop` run `20260819T161206Z-d6dbad85`; the live Codex
  target (SHA-256
  `0dd415bb140f10fe95c70005e33ca523f1ed60419a79bbfeabdf9a31446c6b63`)
  produced zero-call `stable_noop` run `20260819T161218Z-834d615b`. Both remained
  byte-identical.
- On a disposable Claude copy containing one exact duplicate, plan
  `20260819T165955Z-1987f9ef` changed 67 directives to 66 and 11,606 bytes to
  11,378. Claude Code 2.1.224 with `claude-sonnet-4-6` passed all 18 predecessor
  and candidate probe repeats while the control passed 0/18. Verification receipt
  `4f1851d08ddb4047243f6978204bda6b29ad59d245dd744a020e31321eb878aa`
  authorized attended apply to that disposable copy only. Second run
  `20260819T170602Z-39e3bba4` was a zero-call byte-identical no-op.
- A lower-position Claude rewrite, run `20260819T165129Z-70f323ea`, scored 18/18
  before and 17/18 after. It failed closed and was never applied. That receipt is
  the concrete proof that compression does not get a pass merely because it is
  smaller or coherent.
- On a disposable Codex copy containing one exact duplicate, plan
  `20260819T171655Z-546b02cd` changed 35 directives to 34 and 5,269 bytes to
  4,830. Codex CLI 0.147.0 with `gpt-5.6-sol` in a fresh private `CODEX_HOME`
  passed all 18 candidate repeats while the control passed 0/18. The predecessor
  missed one of three trivial counter-probe repeats; the candidate repaired it,
  so the receipt records both the baseline gap and candidate improvement rather
  than mistaking baseline flakiness for a candidate failure. Verification receipt
  `0376960893146c8f9f29559da0fee2a9f14a0b182eae3759689dda2b0e915b1d`
  authorized attended apply to that disposable copy only. Second run
  `20260819T171954Z-d68b18c5` was a zero-call byte-identical no-op.

The historical receipts are bounded qualification evidence for six owner-authored Kindex
behaviors. The new disposable receipt qualifies only the three named package-manager cases.
Together they support the fixed-point, semantic-compilation, and verifier mechanisms on the
recorded consumers; they are not universal behavioral equivalence or a promise about future
models.

The five dispositions are:

- **keep**: copy the current directive bytes unchanged;
- **replace**: locally render a typed directive record at the same location;
- **remove**: delete a directive only with strong exact evidence;
- **relocate**: move specific prose to an exact configured target, recording
  either a `contextual` or `organization` basis;
- **escalate**: preserve source prose byte-for-byte and report a candidate for a
  deterministic Claude hook or settings control. It requires two independent
  evidence groups, is always `candidate_only`, never writes the enforcement
  surface, and is counted separately from churn and changed directives.

Every change, including remove and escalate, carries a `destination_target`
copied byte-for-byte from `allowed_targets`. Target strings are opaque: Meditate's
planner must not expand `~`, normalize, absolutize, or invent a spelling.
Replace/remove/escalate copy the source target exactly; relocate selects another
exact configured target. Local allowlist validation remains authoritative.

Plan artifacts, JSON/Markdown reports, CLI JSON, and the JSONL summary log expose
defect classes and outcomes plus pre/post directive, byte, and line telemetry. A
Claude `CLAUDE.md` over
200 post-plan lines produces a guidance warning, not a claimed vendor hard limit.
The configured writable Codex `AGENTS*.md` set is checked against
`project_doc_max_bytes` from the configured Codex home (32,768 bytes by default).
Coverage is reported as `configured_targets_only`; a pass does not prove every
cwd-specific Codex instruction chain fits.

## Model and token controls

`[llm]` in TOML pins the provider/model, effort, maximum calls, per-call input and
output limits, total input/output budgets, and timeout. `plan` and `run` accept
temporary `--model`, `--effort`, `--max-input-tokens`, `--max-output-tokens`,
`--max-total-input-tokens`, and `--max-total-output-tokens` overrides. Meditate
never silently falls back to another model.

The pre-call input estimate is the UTF-8 byte count of the system prompt, JSON
schema, and sanitized packet. That deliberately overestimates normal tokenizer
usage. Low-ranked events are removed until the configured budget fits; older
evidence is represented through a reserved temporal-breadth sample rather than a
hard cutoff.

## Cron

Meditate prints a cron entry; it does not silently edit your crontab:

```bash
meditate cron --check
meditate cron --schedule '0 3 * * 0'
```

The entry pins the current Python executable, config path, working directory,
`~/.profile`, and a private log path. `run` takes a non-blocking run lock, so
overlap fails closed. The generated job is a dry-run by default: it inspects,
plans, archives, and reports, but does not rewrite instructions.

`meditate cron --apply` renders an explicit `run --apply` job. A changed run first
executes the configured owner suite and stops if it fails; apply then still needs
the unattended config switch, attended-history threshold, and low-blast-radius
classification. A no-op exits successfully without verification or mutation.
Cron cannot invent a suite, reuse another plan's receipt, or treat a prior attended
hash as ambient authority.

## Why not a linter?

Snapshot: 2026-08-18. This is an adjacent, capable category—not an empty one.
[claudelint](https://claudelint.com/) advertises 116 rules across 10 categories
and plugin-assisted restructuring;
[cclint](https://www.npmjs.com/package/@felixgeelhaar/cclint) checks imports,
hierarchy conflicts, and duplicates; [AgentLint](https://github.com/0xmariowu/AgentLint)
and [agentlinter.com](https://agentlinter.com/) describe static, AI, and
session-aware checks and fixes; [Reporails](https://reporails.com/) offers local
deterministic diagnostics and healing. Meditate's narrower distinction is total
disposition of the configured directive set, semantic nomination from temporal
interaction/Kindex evidence, typed report-only missing-rule hypotheses, and
recoverable exact-hash apply—not a claim that these tools do nothing. “Total”
means every configured pre-image record receives a disposition, not that every
possible behavior is covered.

The exact purported title `A Taxonomy of Agent Instruction Failures` by Gloaguen
et al. was not verified and is not load-bearing. The verified paper is
[`Coding Agents Don't Know When to Act`](https://arxiv.org/abs/2605.07769).

## Recovery and erasure

Run archives are under `~/.local/share/meditate/runs/`; reports and JSONL summary
logs are under `~/.local/state/meditate/`. A forced restore first archives the
diverged live bytes and whether the file existed. Archive deletion is preview-only
unless both the explicit run ID and `--execute` are supplied; active recovery
material additionally needs `--force`. Purge leaves a tombstone so “explicitly
erased” is distinguishable from “never existed” or “corrupt,” deletes the exact
run-ID JSON/Markdown reports, and retains only non-sensitive decision hashes/IDs
needed to prevent replay. JSONL decision records are summary-only and never retain
raw questions, options, or custom responses.

## Development

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy --strict src/meditate
.venv/bin/pytest
```

The tests use synthetic histories only. See [the design brief](docs/design-brief.md)
for authority, transaction, and acceptance contracts. The dependency-free static
documentation site lives in `docs/` and is published from `main:/docs` at
<https://jmcentire.github.io/meditate/>.

The first attended Claude pass on 2026-08-18 inspected 15,531 unique evidence
events, selected 180 within budget, excluded nine secret-bearing records wholesale,
and changed one of 65 directives. The applied run and exact pre/post images remain
recoverable outside the repository under the configured data root.
