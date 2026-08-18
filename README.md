# Meditate

[Documentation](https://jmcentire.github.io/meditate/) ·
[Privacy](PRIVACY.md) ·
[Design brief](docs/design-brief.md)

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
8. binds model/prompt provenance, import graphs, semantic status, and pre/post
   directive/byte/line metrics into the plan hash;
9. renders unchanged spans byte-for-byte, archives pre/post images, and writes
   only after an exact plan hash is approved.

Raw histories are read-only. A history record with a high-confidence credential
shape is excluded wholesale before any model call. Reports and archives live in
private XDG data/state directories, not this repository.

## Install

```bash
cd /Users/jmcentire/Code/meditate
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

An unresolved conflict, malformed-corpus degradation, secret scan, unknown
evidence quote, excessive churn, size violation, protected-section edit, changed
config, changed source file, ambiguous high-impact action gate, or truncated
provider response blocks apply.

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
erased” is distinguishable from “never existed” or “corrupt.”

## Development

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
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
