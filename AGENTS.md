# Meditate contributor instructions

- Keep raw Claude/Codex interactions, credentials, generated reports, archives,
  and local configuration out of Git.
- Treat source histories, auto-memory, and Kindex as read-only evidence.
- Any change to apply/restore must preserve archive-before-write, source-hash
  revalidation, symlink refusal, atomic per-file replacement, and rollback tests.
- Any change to prompt assembly must preserve local redaction, bounded selection,
  data-only delimiters, exact evidence lineage, and hard token limits.
- Model output is untrusted input. It never chooses filesystem paths outside the
  configured allowlist and never mints durable IDs.
- Use synthetic fixtures. Tests must not copy content from personal histories.
- Refresh `.kin/index.json` with `kin index --project-path . --output-dir . --json`
  when committing substantive code-map changes.
