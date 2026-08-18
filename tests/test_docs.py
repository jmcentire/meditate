from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

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
