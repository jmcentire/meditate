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
    for command in ("init", "inspect", "plan", "run", "apply", "restore", "purge", "cron"):
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
    assert re.search(
        (
            r"same[- ]user\s+filesystem\s+compromise"
            r".{0,100}outside.{0,60}threat\s+(?:model|boundary)"
        ),
        combined,
    )


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
