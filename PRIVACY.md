# Meditate privacy boundary

Meditate is a locally operated command-line tool. It does not operate a hosted service,
collect product telemetry, create user accounts, or maintain a remote memory store.

`meditate inspect` is entirely local and makes no model call. On a fresh exact
snapshot, `meditate plan` and `meditate run` invoke the explicitly configured
Anthropic model for a read-only semantic Analyst pass even when the correct result
is a stable no-op. The validated analysis is content-addressed; an exact cache hit
makes no Analyst call, and no Drafter call occurs unless an admitted existing-rule
candidate or missing-rule hypothesis exists. Fresh semantic planning is bounded to
at most one Analyst and one Drafter call by default.
Before either planning request, evidence undergoes local streaming, deduplication,
secret detection, redaction, deterministic selection, and hard token limits.
High-confidence secret-bearing records are excluded wholesale. Meditate never
silently chooses a different provider or model.

`meditate decide` transmits the frozen parent context and exact selected archived
option or byte-preserved custom response, plus bounded decision lineage, to
Anthropic rather than transmitting newly appended live history. Anthropic's
response becomes a fresh read-only successor plan. The input is recorded as
operator-asserted user authority, but identity is not authenticated or attested,
and Meditate cannot prove that an invoking agent faithfully relayed the user's real
answer. `meditate decide` rejects a recognized high-confidence secret shape in a
custom response before submission. Other selected-option
and custom text is still user-derived content; it is not anonymous or risk-free.

The Analyst request includes its system prompt and schema, configured target path
labels and hashes, the complete sanitized configured directive set, bounded imported
immutable context, and selected temporally ordered interaction, auto-memory, and
Kindex evidence with metadata. When Kindex is enabled, selected node content is
therefore provider-bound user data even though Kindex itself is read-only. The
Drafter request includes its separate prompt/schema, only admitted mutable candidate
directive IDs/text, bounded related immutable context, the validated semantic artifact,
and evidence required by admitted nominations or missing-rule hypotheses. Unrelated
directive IDs are not sent to the Drafter.

Directive and evidence text is locally secret-scanned and redacted, but it remains
user-derived content; it is not claimed to be anonymous or risk-free. Unselected and
wholesale-excluded history records are not sent. A semantic cache entry stores the
sanitized model response plus prompt/schema/parser/model and packet hashes locally;
it does not contain a provider credential.

`meditate verify` is a separate model-backed operation. It sends the owner-authored
neutral probe/counter-probe scenarios with opaque case references and, in predecessor
and candidate conditions, the complete archived instruction bundle to the selected
local Claude or Codex CLI. Private action IDs, literal detector phrases, case
descriptions, and required/forbidden/order assertions are not sent to the consumer.
That CLI may transmit the material to its configured provider under the CLI's own
account and retention settings. The consolidation planner never receives the suite
or verifier outcomes. Suite files are rejected if they contain a recognized
high-confidence secret shape, but they are still user-authored content and are not
anonymous. Codex verification replaces ambient `CODEX_HOME` with a fresh private
directory, ignores user config and rules, and requires `OPENAI_API_KEY`; this keeps
global `AGENTS.md`, memories, and configuration out of the control condition. The
frozen suite and verification receipt are private local artifacts.

Configured instruction files, interaction histories, auto-memory, and Kindex may
be read as evidence. Histories, memory, and Kindex are read-only; Meditate writes
only exact instruction targets declared in its configuration. Model output is
untrusted and cannot choose filesystem paths or mint durable identifiers.

`analysis.json`, `plan.json`, `manifest.json`, `evidence.json`, semantic cache
entries, frozen `verification-suite.json`, `verification.json`, and run-specific JSON/Markdown
reports are private local plan artifacts stored in XDG state/data directories.
Depending on the run, they contain the current decision request or bounded
collision scope, the exact selected/custom response, private verifier assertions
and detector phrases, derived verifier actions, and lineage. The append-only
JSONL is summary-only: it records request IDs, choice
keys, hashes, and lineage depth, never the raw question, options, or custom response.
Anthropic planning uses the standard `ANTHROPIC_API_KEY`; clean-room Codex
verification uses the standard `OPENAI_API_KEY`. API key values are resolved at
runtime and are not logged.

During successor purge, its exact run-ID JSON and Markdown reports are deleted.
The replay tombstone/marker retains only IDs and hashes; it does not retain raw
response text. The append-only summary likewise retains only parent, request, and
successor IDs, the conflict fingerprint, and plan/response hashes needed to prevent
replay. A still-retained parent run continues to contain its own archived question
until it too is explicitly purged.

The documentation site at <https://jmcentire.github.io/meditate/> is static. It
sets no cookies and loads no third-party analytics, scripts, fonts, or images.
GitHub Pages may process ordinary request metadata under GitHub's own terms.

The operator controls evidence sources, model/provider configuration, retention,
writable targets, and whether a reviewed proposal is applied. Operators should
review their model provider's data-handling terms before enabling model calls or
opt-in transcript bodies.

See the [full privacy page](https://jmcentire.github.io/meditate/privacy.html) for
details. Last updated August 19, 2026; applies to Meditate 0.3.x.
