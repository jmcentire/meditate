from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from meditate.redact import surviving_high_confidence

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []
        self.title_depth = 0
        self.title_text: list[str] = []
        self.description_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self.title_depth += 1
        if tag == "meta" and values.get("name") == "description":
            self.description_count += 1
        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value:
                self.references.append((attribute, value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_text.append(data)


def _parse(path: Path) -> _ReferenceParser:
    parser = _ReferenceParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def _local_target(page: Path, reference: str) -> Path | None:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:")):
        return None

    relative = parsed.path
    if not relative:
        return None
    target = DOCS / relative.lstrip("/") if relative.startswith("/") else page.parent / relative
    if relative.endswith("/"):
        target = target / "index.html"
    return target.resolve()


def test_static_pages_have_metadata_and_resolvable_local_links() -> None:
    pages = sorted(DOCS.glob("*.html"))
    assert {page.name for page in pages} >= {"index.html", "privacy.html"}

    failures: list[str] = []
    for page in pages:
        parser = _parse(page)
        if not "".join(parser.title_text).strip():
            failures.append(f"{page.name}: missing title")
        if parser.description_count != 1:
            failures.append(
                f"{page.name}: expected one meta description, got {parser.description_count}"
            )
        for attribute, reference in parser.references:
            target = _local_target(page, reference)
            if target is None:
                continue
            if DOCS.resolve() not in target.parents and target != DOCS.resolve():
                failures.append(f"{page.name}: {attribute} escapes docs/: {reference}")
            elif not target.exists():
                failures.append(f"{page.name}: missing {attribute} target: {reference}")

    assert failures == []


def test_pages_root_and_agent_discovery_contract() -> None:
    assert (DOCS / ".nojekyll").is_file()
    assert (DOCS / "robots.txt").is_file()
    assert (DOCS / "sitemap.xml").is_file()
    llms = (DOCS / "llms.txt").read_text(encoding="utf-8")
    assert "https://jmcentire.github.io/meditate/" in llms
    assert "llms-full.txt" in llms
    assert (DOCS / "llms-full.txt").is_file()


def test_documented_commands_match_cli_surface() -> None:
    index = (DOCS / "index.html").read_text(encoding="utf-8")
    for command in (
        "init",
        "inspect",
        "plan",
        "verify",
        "run",
        "apply",
        "restore",
        "purge",
        "cron",
        "decisions",
        "decide",
    ):
        assert f"meditate {command}" in index


def test_public_docs_do_not_contain_key_material() -> None:
    forbidden = ("sk-ant-", "sk-proj-", "-----BEGIN PRIVATE KEY-----")
    for path in DOCS.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path.name} contains forbidden key marker"


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"style", "script"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"}:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _visible_text(path: Path) -> str:
    parser = _VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return " ".join(" ".join(parser.parts).split()).lower()


def _assert_core_semantic_boundary(text: str, *, surface: str) -> None:
    dispositions = ("keep", "replace", "remove", "relocate", "escalate")
    positions = [text.find(disposition) for disposition in dispositions]
    assert all(position >= 0 for position in positions), (
        f"{surface}: missing one of five dispositions"
    )
    authority_confidence = text.find("authority before confidence")
    temporal = text.find("temporal")
    assert authority_confidence >= 0, f"{surface}: missing authority-before-confidence rule"
    assert temporal >= 0, f"{surface}: missing temporal guidance"
    assert authority_confidence < temporal, (
        f"{surface}: authority-before-confidence must precede temporal guidance"
    )
    assert "structural validation is not behavioral qualification" in text
    assert re.search(r"why\s+not\s+(?:just\s+)?a\s+linter", text), (
        f"{surface}: missing why-not-a-linter comparison"
    )


def test_public_surfaces_document_semantic_scope_import_and_budget_contract() -> None:
    index = _visible_text(DOCS / "index.html")
    llms_full = (DOCS / "llms-full.txt").read_text(encoding="utf-8").lower()
    _assert_core_semantic_boundary(index, surface="index.html")
    _assert_core_semantic_boundary(llms_full, surface="llms-full.txt")
    assert "illustrative proposal — not a verdict" in index
    assert "illustration, not behavioral-equivalence proof" in index

    combined = index + "\n" + llms_full
    assert ".claude/rules" in combined
    assert "paths:" in combined
    assert "@path" in combined
    assert "four hops" in combined or "4 hops" in combined
    assert "configured_targets_only" in combined or "configured targets only" in combined
    assert re.search(r"200\s+lines", combined)
    assert "guidance" in combined and "not a hard" in combined
    assert (
        "32768" in combined or "32,768" in combined or "32 kib" in combined or "32 kb" in combined
    )
    assert "project_doc_max_bytes" in combined


def test_public_docs_disclose_claude_import_filesystem_threat_boundary() -> None:
    index = _visible_text(DOCS / "index.html")
    llms_full = (DOCS / "llms-full.txt").read_text(encoding="utf-8").lower()
    combined = index + "\n" + llms_full

    assert re.search(r"configured(?:\s+claude)?\s+roots?\b", combined)
    assert "import graph" in combined
    assert (
        "operator-trusted" in combined
        or "operator trusted" in combined
        or re.search(
            r"operators?\s+must\s+trust.{0,100}roots?.{0,100}(?:import\s+)?graphs?",
            combined,
        )
    )

    for path_form in ("relative", "absolute", "~/"):
        assert path_form in combined
    assert "referenced file" in combined or "file it names" in combined
    assert "process-readable" in combined or re.search(
        r"readable\s+by\s+(?:the\s+)?(?:meditate\s+)?process",
        combined,
    )

    assert re.search(
        (
            r"(?:local\s+redaction|redacted\s+locally|pattern[- ]redaction)"
            r".{0,180}(?:is|does|provides?)?\s*not.{0,60}filesystem\s+sandbox"
        ),
        combined,
    )


def test_public_docs_explain_operator_choice_ux_and_honest_authority_boundaries() -> None:
    index = _visible_text(DOCS / "index.html")
    llms_full = (DOCS / "llms-full.txt").read_text(encoding="utf-8").lower()
    combined = index + "\n" + llms_full

    assert "meditate decisions" in combined
    assert "meditate decide" in combined
    assert re.search(r"--choice\s+(?:a\|b\|c|a,?\s*b,?\s*(?:or|and)\s*c)", combined)
    assert "--custom" in combined
    assert re.search(
        (
            r"i(?:’|')m trying to resolve .+ and .+\. would you prefer .+"
            r"\(recommended\), .+, .+, or something else\?"
        ),
        combined,
    )
    assert "recommend" in combined
    assert re.search(
        r"recommend(?:ation|ed)?.{0,120}(?:advisory|does not (?:answer|choose|select))",
        combined,
    )
    assert "successor plan" in combined
    assert re.search(r"operator[- ]asserted.{0,100}(?:user\s+)?authority", combined)
    assert re.search(
        r"(?:not|no).{0,80}(?:authenticated|attested).{0,40}identity|"
        r"identity.{0,80}(?:not\s+(?:authenticated|attested)|"
        r"un(?:authenticated|attested))",
        combined,
    )
    assert "relay" in combined
    assert "structural validation is not behavioral qualification" in combined
    assert re.search(
        (
            r"same[- ]user\s+filesystem\s+compromise"
            r".{0,100}outside.{0,60}threat\s+(?:model|boundary)"
        ),
        combined,
    )


def test_privacy_surfaces_disclose_decision_relay_storage_and_purge_boundaries() -> None:
    surfaces = {
        "PRIVACY.md": " ".join((ROOT / "PRIVACY.md").read_text(encoding="utf-8").lower().split()),
        "docs/privacy.html": _visible_text(DOCS / "privacy.html"),
    }

    for surface, text in surfaces.items():
        assert "anthropic" in text, f"{surface}: missing decision-response recipient"
        assert re.search(r"(?:send|sent|transmit|relay).{0,180}anthropic", text), (
            f"{surface}: missing response transmission disclosure"
        )
        assert re.search(
            (
                r"exact.{0,100}(?:chosen|choice|selected|custom).{0,100}response|"
                r"(?:chosen|choice|selected|custom).{0,100}response.{0,100}exact"
            ),
            text,
        ), f"{surface}: missing exact chosen/custom response disclosure"
        assert re.search(r"frozen.{0,100}parent.{0,100}context", text), (
            f"{surface}: missing frozen-parent-context disclosure"
        )

        assert re.search(
            r"private.{0,60}local.{0,100}(?:xdg|director|storage)|"
            r"local.{0,60}private.{0,100}(?:xdg|director|storage)",
            text,
        ), f"{surface}: missing private local storage-directory disclosure"
        artifact_markers = {
            "plan": ("decision plan", "plan.json"),
            "manifest": ("manifest", "manifest.json"),
            "evidence": ("evidence", "evidence.json"),
            "report": ("report", "report.json", "report markdown"),
        }
        for artifact, markers in artifact_markers.items():
            assert any(marker in text for marker in markers), (
                f"{surface}: missing listed {artifact} artifact"
            )
        assert re.search(r"(?:accepted|selected).{0,100}response", text), (
            f"{surface}: missing accepted-response storage disclosure"
        )
        assert re.search(r"(?:decision\s+)?request", text), (
            f"{surface}: missing request storage disclosure"
        )
        assert "jsonl" in text
        assert re.search(
            (
                r"jsonl.{0,180}(?:no|not|without|never).{0,80}"
                r"(?:raw\s+)?(?:question|option|custom\s+response)|"
                r"(?:no|not|without|never).{0,80}(?:raw\s+)?"
                r"(?:question|option|custom\s+response).{0,180}jsonl"
            ),
            text,
        ), f"{surface}: missing hash-only decision JSONL disclosure"

        assert re.search(
            r"(?:reject|block|refuse).{0,100}(?:recognized\s+)?high[- ]confidence.{0,60}secret",
            text,
        ), f"{surface}: missing recognized-secret rejection boundary"
        assert re.search(
            r"(?:does not|do not|no).{0,80}(?:promise|guarantee).{0,40}anonym|"
            r"not.{0,40}anonym(?:ous|ity)|not an anonymity",
            text,
        ), f"{surface}: missing no-anonymity-promise boundary"

        assert "successor" in text and "purg" in text
        assert re.search(
            r"purg.{0,160}(?:report|json|markdown).{0,100}(?:remove|delete)|"
            r"(?:report|json|markdown).{0,160}(?:remove|delete).{0,100}purg",
            text,
        ), f"{surface}: missing successor-report purge disclosure"
        assert "replay" in text and ("tombstone" in text or "marker" in text)
        assert re.search(
            r"(?:only|solely).{0,100}hash(?:es)?.{0,80}(?:id|identifier)|"
            r"(?:only|solely).{0,100}(?:id|identifier).{0,80}hash",
            text,
        ), f"{surface}: missing hash/ID-only purge metadata disclosure"
        assert re.search(
            r"(?:no|not|without|does not retain).{0,80}(?:raw\s+)?response(?:\s+text)?",
            text,
        ), f"{surface}: missing no-raw-response purge disclosure"


def test_public_docs_explain_fixed_point_typed_output_and_behavioral_oracle() -> None:
    index = _visible_text(DOCS / "index.html")
    llms_full = (DOCS / "llms-full.txt").read_text(encoding="utf-8").lower()
    combined = index + "\n" + llms_full

    assert re.search(r"prompt(?:\s+(?:contract|version))?\s*[:=]?\s*v?10\b", combined)
    assert re.search(r"parser(?:\s+(?:contract|version))?\s*[:=]?\s*v?25\b", combined)
    assert re.search(
        r"summar(?:y|ies).{0,180}(?:deterministic|locally computed|validated data)|"
        r"(?:deterministic|locally computed).{0,180}summar(?:y|ies)",
        combined,
    )
    assert re.search(
        r"(?:model|provider).{0,160}(?:cannot|does not|must not|never)"
        r".{0,100}(?:author|supply|write).{0,80}summar|"
        r"summar(?:y|ies).{0,160}(?:not|never).{0,80}(?:model|provider)[- ]authored|"
        r"(?:model|provider)[- ]authored.{0,80}summar(?:y|ies)"
        r".{0,100}(?:forbid|reject|not accepted|removed)",
        combined,
    )
    assert re.search(
        r"(?:8|eight)[- ]word.{0,120}(?:contiguous\s+)?phrase.{0,120}"
        r"(?:repeat|duplicat)|"
        r"(?:repeat|duplicat).{0,120}(?:8|eight)[- ]word.{0,120}phrase|"
        r"(?:8|eight)(?:\s+or\s+more)?\s+words?.{0,120}(?:contiguous|repeat|duplicat)|"
        r"(?:contiguous|repeat|duplicat).{0,120}(?:8|eight)(?:\s+or\s+more)?\s+words?",
        combined,
    )
    for catchall in (
        "other applicable actions",
        "additional applicable actions",
        "and similar",
        "etc",
        "and so on",
    ):
        assert catchall in combined
    assert re.search(
        r"(?:catch[- ]all|exact phrase).{0,180}(?:source|cited evidence)|"
        r"(?:source|cited evidence).{0,180}(?:catch[- ]all|exact phrase)",
        combined,
    )

    assert "fixed point is stability" in combined
    assert "defect resolution" in combined
    assert re.search(r"byte(?:s| counts?)?\s+(?:are|is).{0,40}telemetry", combined)
    assert re.search(r"(?:output|directive).{0,80}(?:may|can).{0,40}grow", combined)
    assert "stable_noop" in combined
    assert re.search(r"stable(?:_noop| no-op).{0,140}zero (?:provider|model) calls?", combined)
    assert "reviewed_noop" in combined
    assert "exact_duplicate" in combined and "confirmed" in combined
    assert "exception_lineage" in combined and "review" in combined
    assert "non_idempotent_proposal" in combined
    assert re.search(r"(?:ten|10) iterations?.{0,100}(?:without drift|do not drift)", combined)

    for keyword in ("must", "must not", "should", "should not", "may"):
        assert f"`{keyword}`" in llms_full
    for field in ("normative_keyword", "rule", "reason", "scope", "boundary_example"):
        assert field in llms_full
    assert "rfc 2119" in combined
    assert "boundary example remains untrusted prose" in combined

    assert "meditate verify" in combined
    assert "owner-authored" in combined and "planner never" in combined
    for condition in ("control", "predecessor", "candidate"):
        assert condition in combined
    assert re.search(
        r"pass(?:ed)? .{0,100}(?:recorded|owner-selected).{0,100}(?:cases|suite)",
        combined,
    )
    assert "not universal behavioral equivalence" in combined

    assert "kindex_required_failed" in combined
    assert re.search(r"kindex.{0,160}(?:every|all).{0,80}(?:read|search).{0,80}required", combined)


def test_public_surfaces_contain_no_raw_personal_artifacts_or_live_secrets() -> None:
    forbidden_personal_artifacts = (
        "/users/jmcentire/",
        "/home/jmcentire/",
        "cookie: session=",
        "authorization: bearer ",
        "-----begin private key-----",
    )
    for path in DOCS.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in forbidden_personal_artifacts:
            assert marker not in lowered, f"{path.name} contains raw personal or secret material"
        assert not surviving_high_confidence(text), (
            f"{path.name} contains text matching a high-confidence live-secret pattern"
        )
