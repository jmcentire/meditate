# Meditate design brief

## Outcome

Build a locally operated CLI that consolidates, compresses, and simplifies behavioral
directives used by Claude Code and OpenAI Codex. Its job is conflict resolution,
not summary-by-deletion: it must replace obsolete or contradictory rules with a
smaller coherent set while retaining recoverable provenance.

The first real subject is Jeremy McEntire's local Claude Code state. No raw
interaction corpus or secret-bearing excerpt may be committed to this repo.

## Why it exists

The observed failure is monotonic append. A correction becomes a new clause,
but the rule that caused the correction is rarely rewritten. Contradiction is a
symptom; accumulated exceptions with no replacement relation are the mechanism.

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

## Command contract

- `meditate init`: write a commented TOML configuration.
- `meditate inspect`: local-only inventory, secret counts, candidate directive
  statistics, potential conflicts/overlaps, and token estimate. It makes no
  claim of semantic conflict unless a deterministic rule proves one, and makes
  no model call.
- `meditate plan`: build a sanitized evidence packet, call the selected model,
  validate structured output, and write a proposal/report. It changes no target.
- `meditate apply RUN_ID`: revalidate source hashes, archive every target plus a
  manifest, atomically replace targets, and emit an apply receipt.
- `meditate run`: inspect + plan; apply only with both configuration permission
  and an explicit `--apply` flag. Cron uses this surface.
- `meditate restore RUN_ID`: restore archived targets transactionally, refusing
  to overwrite post-run changes unless `--force` is given.
- `meditate cron`: print a locked cron entry or check its dependencies. Meditate
  never edits the user's crontab.

Dry-run is the default everywhere. A high-confidence secret match after local
redaction blocks the evidence packet before the first model call; model output is
scanned again before it is persisted. Model failure, parse failure, surviving
secret detection, missing evidence references, source drift, concurrent
execution, or a non-recoverable archive all fail closed and cannot produce a
rewrite.

## Model and budget contract

Support explicit provider and model targeting behind a provider interface. The
first live provider is Anthropic through its official Python SDK; OpenAI remains
an interface-backed extension rather than untested surface. Configuration
exposes maximum input tokens per call, maximum output tokens per call, total
input-token budget, total output-token budget, and maximum calls. No fallback
model is selected silently. Pre-call accounting uses a conservative upper bound;
actual usage is reconciled after every call, and budget exhaustion cancels later
stages. Truncated/max-token output is an invalid plan.

Anthropic key lookup supports, in order, the actual local
`WANDER_ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY`, `JMC_ANTHROPIC_API_KEY`, then the
deprecated misspelled compatibility alias `WANDER_ANTRHOPIC_API_KEY`. Values are
never logged.

Large corpora use a bounded pipeline:

1. Local parsing, deduplication, classification, and redaction.
2. Deterministic selection of high-signal events within a configured budget.
3. One consolidation call over current directives plus locally derived candidate
   evidence. Model-based candidate extraction is not part of the first version.
4. Deterministic validation; a second model judging the first is not an authority
   or a required safety gate.

Source readers process JSONL line by line, bound individual record size, and do
not need a corpus-sized in-memory parse. Malformed/unknown records are counted and
skipped; a partial or degraded corpus run is visible and blocks apply. The parser
version is bound into every archived plan so a validator change invalidates old
plans rather than silently reinterpreting them.

## Structured synthesis contract

Instruction documents are deterministically segmented using ATX
headings, top-level list items (nested items stay attached), blank-line-delimited
paragraphs, and opaque fenced code blocks. Pre-image directive IDs are minted
locally from the schema version, target identity, heading path, and normalized
content; the model may reference only existing IDs and cannot mint durable IDs.
Output must provide a disposition for every pre-image directive exactly once:
kept, replaced, removed, or relocated.

The model returns JSON operations, not regenerated files. Unchanged spans are
copied byte-for-byte from the pre-image; edited/consolidated operations carry
only replacement text and predecessor IDs; relocation names an allowed target
and heading. Meditate renders complete proposals deterministically. This makes
byte-identical unchanged directives and no-op convergence construction
properties rather than hopes about model formatting.

The model returns JSON with:

- kept directive IDs;
- replacement/removal/relocation operations with predecessor IDs, exact
  allowlisted destination, heading, replacement text, reason, and evidence;
- exact evidence IDs and matching sanitized quotes for every change;
- unresolved conflicts that block apply;
- a concise human report.

Validation rejects unknown evidence IDs, evidence citations without a quoted
span matching the sanitized record, missing or duplicate directive dispositions,
unknown IDs, empty targets, unresolved conflicts, targets outside configuration,
size below the configured floor or above the ceiling, directive-count growth,
excessive churn, protected-section changes, unsupported urgency or operational
actions, self-attested verification, vague high-impact action authority, and any
surviving secret match. Re-running on unchanged sources should converge to a
near-zero proposal rather than rephrasing everything.

Configured protected headings or marker-delimited blocks are copied through
byte-identically and are excluded from model mutation. They remain present in
the evidence packet so the proposed surrounding rules cannot contradict them.

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
available because it is a product requirement, but requires
`allow_unattended_apply = true` in config plus `--apply`, the configured attended
probation count, and an exact cited evidence ID that an operator has placed in
`apply.unattended_evidence_ids`. The evidence allowlist is execution authority,
not an upgrade to the evidence's epistemic rank. A copied cron line therefore
cannot unexpectedly enable rewriting.

The initial local overlap detector has named, bounded heuristics only:
`negation_pair` for the same normalized subject with opposite modal patterns,
and `scope_overlap` for intersecting scopes with a shared normalized subject.
Reports call these overlap candidates, not proven semantic conflicts. Offline
token estimates use a documented conservative bytes heuristic and are labeled
with the estimator version; the provider enforces configured limits again at the
call boundary.

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
