# Meditate

[Documentation](https://jmcentire.github.io/meditate/) ·
[Privacy](PRIVACY.md) ·
[Design brief](docs/design-brief.md)

Meditate is a locally operated CLI for consolidating the behavioral directives that
Claude Code and OpenAI Codex load. It targets the actual failure mode: corrections
are commonly appended as new exceptions while the obsolete rule remains in place.

Meditate does not let an LLM directly regenerate or write your instruction file. It:

1. segments configured instruction files into locally identified directives;
2. streams Claude/Codex history and auto-memory through local secret detection;
3. preserves temporal order and scores recency without an age cutoff;
4. gives repeated, independently observed user corrections more weight while
   keeping older supporting and conflicting evidence in the packet;
5. asks an exact model for a total-disposition operation list;
6. validates every ID, exact evidence quote, destination, size/churn bound, and
   secret scan locally, including external verification and explicit authority
   boundaries for newly introduced merge/release/deploy actions;
7. renders unchanged spans byte-for-byte, archives pre/post images, and writes
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

`meditate cron --apply` only prints a mutation-capable entry. At runtime it still
requires all of the following: `--apply`, `allow_unattended_apply = true`, a plan
whose locally computed minimum mode is unattended, no blocked condition, and the
configured number of prior successful attended applies. Evidence becomes
unattended-eligible only when its exact ID from an attended report is listed in
`apply.unattended_evidence_ids`; editing that list changes the config hash and
requires a fresh plan. An attended plan hash is never reused as ambient cron
authority.

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
