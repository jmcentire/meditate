# Meditate

[Documentation](https://jmcentire.github.io/meditate/) ·
[Privacy](PRIVACY.md) ·
[Design brief](docs/design-brief.md) ·
[Changelog](CHANGELOG.md)

Current package version: **0.2.0 alpha**.

Meditate is a locally operated CLI for resolving defects in the behavioral directives
that Claude Code and OpenAI Codex load. It targets the actual failure mode: corrections
are commonly appended as new exceptions while the obsolete rule remains in place.
Its fixed point is stability, not shrinkage: a well-formed file is a successful,
byte-identical no-op.

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
7. locally identifies confirmed duplicate defects and bounded exception-lineage review
   candidates; when none exist it returns a zero-token successful no-op;
8. asks an exact model for a five-disposition operation list: keep, replace,
   remove, relocate, or report-only escalate. Semantic replacements are typed records
   containing an RFC 2119 keyword, rule, rationale, scope, and optional boundary example;
9. validates every ID, exact evidence quote, destination, size/churn bound, and
   secret scan locally, including external verification and explicit authority
   boundaries for newly introduced merge/release/deploy actions;
10. turns a genuine unresolved authority collision into one bounded
   `a`/`b`/`c`/custom question instead of letting the model choose for the user;
11. binds model/prompt provenance, import graphs, semantic status, and pre/post
   directive/byte/line metrics into the plan hash;
12. runs an owner-authored, planner-blind probe/counter-probe suite against control,
   predecessor, and candidate instructions before any changed plan can apply; and
13. renders unchanged spans byte-for-byte, archives pre/post images, and writes only
   after the verification receipt and exact plan hash are accepted.

Raw histories are read-only. A history record with a high-confidence credential
shape is excluded wholesale before any model call. Reports and archives live in
private XDG data/state directories, not this repository.

## Install

### GitHub Release wheel

The canonical public distribution surface for v0.2.0 is the versioned wheel
attached to its GitHub Release. After that release asset is published:

```bash
python3 -m venv .venv
.venv/bin/pip install https://github.com/jmcentire/meditate/releases/download/v0.2.0/meditate_agent-0.2.0-py3-none-any.whl
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

The deterministic preflight currently distinguishes:

- `exact_duplicate`, a confirmed local defect; and
- `exception_lineage`, a conservative same-heading, shared-subject review candidate,
  not proof that the prose is wrong.

Density, file age, history overlap, and byte count do not create a defect. If no
candidate exists, `plan` does not resolve credentials or construct a provider. It
exits successfully with `outcome=stable_noop`, zero model calls, unchanged target
hashes, and `semantic_verification.status=not_applicable`. If candidates exist but
the model finds no admissible resolution, the report says `reviewed_noop`; it does
not disguise that state as “nothing detected.”

A successful changed plan receives the complete non-overlapping candidate set.
Each change stays within one heading and subject. Local code renders the entire
post-image and rejects it with `non_idempotent_proposal` if a confirmed defect is
still detectable. The acceptance suite covers an unchanged well-formed fixture,
a corrected defective fixture, a second invocation over each result, ten no-drift
iterations, and a multi-defect fixture that must reach its fixed point in one
successful plan.

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
fails. Unchanged plans need no semantic run. Unattended mutation additionally
requires the explicit config switch, probation history, and a structurally
low-blast-radius plan; a verification receipt alone grants no ambient authority.

### v0.2.0 live qualification receipts

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

These are bounded qualification receipts for six owner-authored Kindex behaviors
on the named consumer versions and models. They are not a universal claim about
all instructions or future model versions.

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
disposition of the configured directive set, temporal interaction evidence, and
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
