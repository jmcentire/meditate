# Meditate privacy boundary

Meditate is a locally operated command-line tool. It does not operate a hosted service,
collect product telemetry, create user accounts, or maintain a remote memory store.

`meditate inspect` is entirely local and makes no model call. `meditate plan` and
`meditate run` invoke the explicitly configured Anthropic model when they reach
planning. Before that request, evidence undergoes local streaming, deduplication,
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

The Anthropic request includes the system prompt, output schema, configured target
path labels and hashes, current directive text and metadata, selected interaction
evidence text and metadata, authority/comparison rules, overlap candidates, and
parser-degradation state. Directive and evidence text is locally secret-scanned
and redacted, but it remains user-derived content; it is not claimed to be
anonymous or risk-free. Unselected and wholesale-excluded history records are not
sent.

Configured instruction files, interaction histories, auto-memory, and Kindex may
be read as evidence. Histories, memory, and Kindex are read-only; Meditate writes
only exact instruction targets declared in its configuration. Model output is
untrusted and cannot choose filesystem paths or mint durable identifiers.

`plan.json`, `manifest.json`, `evidence.json`, and run-specific JSON/Markdown
reports are private local plan artifacts stored in XDG state/data directories.
Depending on the run, they contain the current decision request or bounded
collision scope, the exact selected/custom response, and lineage. The append-only
JSONL is summary-only: it records request IDs, choice
keys, hashes, and lineage depth, never the raw question, options, or custom response.
API key values are resolved at runtime and are not logged.

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
details. Last updated August 18, 2026; applies to Meditate 0.1.x.
