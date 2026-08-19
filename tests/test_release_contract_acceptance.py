from __future__ import annotations

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

from meditate import __version__

ROOT = Path(__file__).resolve().parents[1]


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _normalized_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        parser = _VisibleTextParser()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    return " ".join(raw.lower().split())


def test_package_and_pyproject_versions_are_v0_1_0() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == "0.1.0"
    assert pyproject["project"]["version"] == "0.1.0"


def test_changelog_and_public_docs_expose_v0_1_0_without_semantic_qualification_claims() -> None:
    surfaces = {
        "CHANGELOG.md": _normalized_text(ROOT / "CHANGELOG.md"),
        "docs/index.html": _normalized_text(ROOT / "docs" / "index.html"),
        "docs/llms-full.txt": _normalized_text(ROOT / "docs" / "llms-full.txt"),
    }
    boundary_phrases = (
        "structural validation is not behavioral qualification",
        "no semantic qualification",
        "does not claim semantic qualification",
        "not semantically qualified",
    )
    forbidden_positive_claims = (
        "semantic verification passed",
        "semantic verification succeeded",
        "semantic qualification complete",
        "semantic qualification passed",
        "behavioral qualification passed",
        "is behaviorally qualified",
        "is semantically qualified",
        "semantically qualified release",
    )

    for name, text in surfaces.items():
        assert "v0.1.0" in text, f"{name} does not expose v0.1.0"
        for claim in forbidden_positive_claims:
            assert claim not in text, f"{name} claims unproved semantic qualification"

    for name in ("docs/index.html", "docs/llms-full.txt"):
        text = surfaces[name]
        explicitly_not_run = "semantic_verification" in text and "not_run" in text
        assert explicitly_not_run or any(phrase in text for phrase in boundary_phrases), (
            f"{name} does not preserve the structural-not-semantic release boundary"
        )

    changelog = surfaces["CHANGELOG.md"]
    assert "decision request" in changelog or "decision_request" in changelog
    assert "successor plan" in changelog


def test_public_release_surfaces_expose_final_prompt_v6_live_receipts() -> None:
    claude_run_id = "20260819T015515Z-120c6869"
    codex_run_id = "20260819T015632Z-a4fde49b"
    surfaces = {
        "CHANGELOG.md": _normalized_text(ROOT / "CHANGELOG.md"),
        "docs/index.html": _normalized_text(ROOT / "docs" / "index.html"),
        "docs/llms-full.txt": _normalized_text(ROOT / "docs" / "llms-full.txt"),
    }

    for name, text in surfaces.items():
        claude_start = text.find(claude_run_id.lower())
        codex_start = text.find(codex_run_id.lower())
        assert claude_start >= 0, f"{name}: missing final Claude run ID"
        assert codex_start >= 0, f"{name}: missing final Codex run ID"

        claude_end = codex_start if codex_start > claude_start else len(text)
        codex_end = claude_start if claude_start > codex_start else len(text)
        claude_receipt = text[claude_start:claude_end]
        codex_receipt = text[codex_start:codex_end]

        assert re.search(r"\b65\s+directives?\b", claude_receipt), (
            f"{name}: Claude receipt must bind the 65-directive count"
        )
        assert "+720" in claude_receipt, (
            f"{name}: Claude receipt must bind the +720-byte aggregate delta"
        )
        assert "compression_regression" in claude_receipt
        assert re.search(r"(?:no|without)\s+(?:an?\s+)?apply\s+command", claude_receipt)
        assert re.search(
            r"(?:target|sha).{0,100}unchanged|unchanged.{0,100}(?:target|sha)",
            claude_receipt,
        ), f"{name}: Claude receipt must disclose the unchanged target"
        assert "441fe6e9" in claude_receipt, (
            f"{name}: Claude receipt must identify the unchanged target hash"
        )

        assert re.search(
            r"(?:33\s*/\s*33|33\s+of\s+33|(?:kept|keep)\s+all\s+33)",
            codex_receipt,
        ), f"{name}: Codex receipt must bind all 33 kept directives"
        assert re.search(r"(?:zero|0)\s+changes?\b", codex_receipt), (
            f"{name}: Codex receipt must disclose zero changes"
        )
        assert re.search(
            r"4,?276\s*(?:/|(?:bytes?.{0,80}(?:within|of)))\s*(?:the\s+)?32,?768",
            codex_receipt,
        ), f"{name}: Codex receipt must bind 4,276 of 32,768 configured-target bytes"
        assert re.search(
            r"(?:target|sha).{0,100}unchanged|unchanged.{0,100}(?:target|sha)",
            codex_receipt,
        ), f"{name}: Codex receipt must disclose the unchanged target"
        assert "0dd415bb" in codex_receipt, (
            f"{name}: Codex receipt must identify the unchanged target hash"
        )

        assert re.search(r"prompt(?:\s+(?:contract|version))?\s*[:=]?\s*v?6\b", text)
        assert "61f949" in text, f"{name}: missing prompt-v6 hash prefix"
        assert re.search(r"parser(?:\s+(?:contract|version))?\s*[:=]?\s*v?20\b", text)
        assert "semantic_verification" in text and "not_run" in text
        assert re.search(
            r"(?:no|not|neither|does not|do not).{0,100}behavioral[- ]equivalence",
            text,
        ), f"{name}: live receipts must not claim behavioral equivalence"


def test_docs_name_github_release_as_canonical_distribution_with_versioned_wheel() -> None:
    index_path = ROOT / "docs" / "index.html"
    llms_path = ROOT / "docs" / "llms-full.txt"
    visible = _normalized_text(index_path) + "\n" + _normalized_text(llms_path)
    raw = (
        index_path.read_text(encoding="utf-8").lower()
        + "\n"
        + llms_path.read_text(encoding="utf-8").lower()
    )

    assert re.search(
        r"(?:canonical.{0,120}github\s+releases?|github\s+releases?.{0,120}canonical)",
        visible,
    )
    wheel_url = re.search(
        (
            r"https://github\.com/[a-z0-9_.-]+/[a-z0-9_.-]+/releases/download/"
            r"v0\.1\.0/meditate_agent-0\.1\.0-py3-none-any\.whl"
        ),
        raw,
    )
    assert wheel_url, "public docs must expose the versioned v0.1.0 wheel install URL"

    assert re.search(
        r"(?:not|no).{0,60}pypi|pypi.{0,60}(?:not|no|unpublished)",
        visible,
    )
    assert not re.search(r"pip(?:3)?\s+install\s+meditate(?:\s|$)", visible)


def test_github_ci_runs_quality_tests_and_isolated_wheel_build() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    workflows = sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")))
    assert workflows, "a GitHub Actions workflow is required"
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in workflows)
    lines = tuple(line.strip() for line in text.splitlines())

    assert any("ruff check" in line for line in lines)
    assert any("mypy" in line and "--strict" in line for line in lines)
    assert any(re.search(r"(?:^|\s)pytest(?:\s|$)", line) for line in lines)
    wheel_builds = [
        line
        for line in lines
        if re.search(r"python(?:3)?\s+-m\s+build\b", line) and "--wheel" in line
    ]
    assert wheel_builds, "CI must build the wheel with python -m build --wheel"
    assert all("--no-isolation" not in line for line in wheel_builds)
