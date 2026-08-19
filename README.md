# Meditate

[Documentation](https://jmcentire.github.io/meditate/) ·
[Privacy](PRIVACY.md) ·
[Design brief](docs/design-brief.md) ·
[Changelog](CHANGELOG.md)

Current package version: **0.1.0 alpha**.

Meditate is a locally operated CLI for consolidating the behavioral directives that
Claude Code and OpenAI Codex load. It targets the actual failure mode: corrections
are commonly appended as new exceptions while the obsolete rule remains in place.

> **Authority before confidence.** A fluent or high-confidence rewrite has no
> authority of its own. Current instructions, explicit corrections, applicable
> scope, and named handoff boundaries come before model confidence.

Meditate does not let an LLM directly regenerate or write your instruction file. It:

1. segments configured instruction files into locally identified directives;
2. streams Claude/Codex history and auto-memory through local secret detection;
3. preserves temporal order and scores recency without an age cutoff;
4. gives repeated, independently observed user corrections more weight while
   keeping older supporting and conflicting evidence in the packet;
5. validates Claude `@path` imports and sends imported documents only as sanitized,
   explicitly read-only context;
6. asks an exact model for a five-disposition operation list: keep, replace,
   remove, relocate, or report-only escalate;
7. validates every ID, exact evidence quote, destination, size/churn bound, and
   secret scan locally, including external verification and explicit authority
   boundaries for newly introduced merge/release/deploy actions;
8. turns a genuine unresolved authority collision into one bounded
   `a`/`b`/`c`/custom question instead of letting the model choose for the user;
9. binds model/prompt provenance, import graphs, semantic status, and pre/post
   directive/byte/line metrics into the plan hash;
10. renders unchanged spans byte-for-byte, archives pre/post images, and writes
   only after an exact plan hash is approved.

Raw histories are read-only. A history record with a high-confidence credential
shape is excluded wholesale before any model call. Reports and archives live in
private XDG data/state directories, not this repository.

## Install

### GitHub Release wheel

The canonical public distribution surface for v0.1.0 is the versioned wheel
attached to its GitHub Release. After that release asset is published:

```bash
python3 -m venv .venv
.venv/bin/pip install https://github.com/jmcentire/meditate/releases/download/v0.1.0/meditate_agent-0.1.0-py3-none-any.whl
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

The Anthropic key lookup order is:

1. `WANDER_ANTHROPIC_API_KEY`
2. `ANTHROPIC_API_KEY`
3. `JMC_ANTHROPIC_API_KEY`
4. deprecated compatibility alias `WANDER_ANTRHOPIC_API_KEY`

The misspelled name is accepted because early requirements used it, but it does
not outrank the correctly spelled variable.

## Workflow

```bash
# Local-only inventory. No model call and no target mutation.
meditate inspect --json

# Read evidence and create a recoverable proposal. Still no target mutation.
meditate plan --model claude-sonnet-4-6 --max-output-tokens 8192

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

An unresolved conflict or decision request, malformed-corpus degradation, secret scan, unknown
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
self-answering path exists. Semantic verification still remains `not_run`.

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
replacement is behaviorally equivalent. Semantic verification remains `not_run`,
so attended exact-hash human review is still required.

## Deterministic consolidation quality

Live prompt-v5 qualification run `20260819T013715Z-67de2a2b` was rejected and
never applied. It grew the configured instruction set by 898 aggregate bytes,
repeated a workflow-order clause, introduced the unsupported catch-all “other
applicable actions,” and claimed 62 remaining directives where local validation
counted 64. Those are deterministic proposal-quality failures, not a semantic
judgment about a replacement.

Prompt v6 and parser v20 remove summary authorship from the model: reports derive
their summary only from locally validated disposition, conflict, and metric
counts. A replacement is rejected if any normalized contiguous phrase of eight
or more words repeats within it. New open-ended action catch-alls such as “other
applicable actions,” “additional applicable actions,” “and similar,” “etc,” or
“and so on” are rejected unless the exact phrase already exists in a source
directive or cited evidence. If aggregate `post_bytes` exceeds `pre_bytes`, the
proposal is still archived for review but gains `compression_regression`, emits
no apply command, and cannot be applied. This is an aggregate boundary: one
corrective directive may grow when the configured target set becomes smaller
overall.

### Final prompt-v6 live receipts

- Claude run `20260819T015515Z-120c6869` dispositioned 65 pre-image directives
  as 64 keep/1 replace. The proposal was +720 aggregate bytes and was
  blocked with `compression_regression`, emitted no apply command, and left the
  target SHA unchanged at `441fe6e9...`.
- Codex run `20260819T015632Z-a4fde49b` dispositioned 33/33 directives as keep,
  with zero changes/conflicts/delta. It reported 4,276/32,768
  configured-target bytes, emitted no apply command, and left the target SHA
  unchanged at `0dd415bb...`.

Both used prompt v6 SHA `61f949...`, parser `meditate-parser-v20`, model
`claude-sonnet-4-6`, and `semantic_verification=not_run`. These receipts qualify
safe no-op and fail-closed blocking behavior only; they do not prove behavioral
equivalence.

## Structural validation is not behavioral qualification

Every new `plan.json` and `manifest.json` retains `model` as the requested model
and records `model_id` as the API-returned resolved identifier (falling back to
the requested identifier only when the response omits it), plus public
`prompt_version`, SHA-256 of the exact system prompt, and
`semantic_verification = {"status":"not_run","method":"owner_defined_behavioral_suite"}`.
The plan hash binds all of them. Apply cross-checks both artifacts and rejects
local prompt drift.

That chain proves what was proposed and that the local renderer obeyed its
mechanical constraints. It does **not** prove that consolidated prose preserves
the behavior of its predecessors. Until an owner authors an independent
behavioral qualification suite, every mutating operation is attended-only and
requires the exact plan SHA. `apply --unattended`, `run --apply`, and cron apply
fail with `semantic_verification_required`; evidence allowlisting cannot upgrade
semantic status. Human review of the report and diff remains required.

The five dispositions are:

- **keep**: copy the current directive bytes unchanged;
- **replace**: render a cited replacement at the same location;
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
pre/post directive, byte, and line counts plus deltas. A Claude `CLAUDE.md` over
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

`meditate cron --apply` can still render the explicit command, but runtime
mutation is unavailable while semantic verification is `not_run`. Cron remains
a useful inspect/plan/report surface; it cannot supply the missing owner-authored
behavioral qualification or reuse an attended hash as ambient authority.

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
