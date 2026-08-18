# Meditate privacy boundary

Meditate is a locally operated command-line tool. It does not operate a hosted service,
collect product telemetry, create user accounts, or maintain a remote memory store.

`meditate inspect` is entirely local and makes no model call. `meditate plan` and
`meditate run` invoke the explicitly configured Anthropic model when they reach
planning. Before that request, evidence undergoes local streaming, deduplication,
secret detection, redaction, deterministic selection, and hard token limits.
High-confidence secret-bearing records are excluded wholesale. Meditate never
silently chooses a different provider or model.

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

Reports and archives are stored in private local XDG state/data directories. API
key values are resolved at runtime and are not logged. Archives can contain
sanitized behavioral evidence and should still be treated as private.

The documentation site at <https://jmcentire.github.io/meditate/> is static. It
sets no cookies and loads no third-party analytics, scripts, fonts, or images.
GitHub Pages may process ordinary request metadata under GitHub's own terms.

The operator controls evidence sources, model/provider configuration, retention,
writable targets, and whether a reviewed proposal is applied. Operators should
review their model provider's data-handling terms before enabling model calls or
opt-in transcript bodies.

See the [full privacy page](https://jmcentire.github.io/meditate/privacy.html) for
details. Last updated August 18, 2026; applies to Meditate 0.1.x.
