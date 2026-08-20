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


def test_package_and_pyproject_versions_are_v0_5_0() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == "0.5.0"
    assert pyproject["project"]["version"] == "0.5.0"


def test_changelog_and_public_docs_expose_v0_5_0_with_bounded_qualification_claims() -> None:
    surfaces = {
        "CHANGELOG.md": _normalized_text(ROOT / "CHANGELOG.md"),
        "docs/index.html": _normalized_text(ROOT / "docs" / "index.html"),
        "docs/llms-full.txt": _normalized_text(ROOT / "docs" / "llms-full.txt"),
    }
    for name, text in surfaces.items():
        assert "v0.5.0" in text, f"{name} does not expose v0.5.0"

    for name in ("docs/index.html", "docs/llms-full.txt"):
        text = surfaces[name]
        assert "structural validation is not behavioral qualification" in text
        assert "not universal behavioral equivalence" in text
        assert "owner-authored" in text and "planner" in text
        assert re.search(r"recorded.{0,100}(?:consumer|agent|cases|suite)", text)

    changelog = surfaces["CHANGELOG.md"]
    assert "decision request" in changelog or "decision_request" in changelog
    assert "successor plan" in changelog


def test_public_release_surfaces_expose_v0_5_reversible_fixed_point_contract() -> None:
    surfaces = {
        "CHANGELOG.md": _normalized_text(ROOT / "CHANGELOG.md"),
        "docs/index.html": _normalized_text(ROOT / "docs" / "index.html"),
        "docs/llms-full.txt": _normalized_text(ROOT / "docs" / "llms-full.txt"),
    }

    for name, text in surfaces.items():
        assert "fixed point" in text and "stability" in text
        assert "defect resolution" in text
        assert "stable_noop" in text and "cache" in text
        assert "exact_duplicate" in text and "exception_lineage" in text
        for candidate_class in (
            "contradiction",
            "temporal_supersession",
            "underspecified",
            "overspecified",
            "wrong_scope",
            "enforcement_candidate",
            "missing_rule",
        ):
            assert candidate_class in text
        assert "write_authority=reversible" in text or "write_authority = reversible" in text
        assert "semantic analyst" in text and "drafter" in text
        assert "rfc 2119" in text
        assert "meditate verify" in text
        assert "planner" in text and ("never sees" in text or "never receives" in text)
        assert "kindex_required_failed" in text
        assert re.search(r"analyst prompt(?:\s+(?:contract|version))?\s*[:=]?\s*v?5\b", text)
        assert "307102f5" in text, f"{name}: missing Analyst prompt hash prefix"
        assert re.search(r"drafter prompt(?:\s+(?:contract|version))?\s*[:=]?\s*v?18\b", text)
        assert "510c166f" in text, f"{name}: missing Drafter prompt hash prefix"
        assert "meditate-analyst-parser-v6" in text or "parser v6" in text
        assert "meditate-parser-v34" in text or "parser v34" in text
        assert "restore" in text and "reversible" in text
        assert "not universal behavioral equivalence" in text


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
            r"v0\.5\.0/meditate_agent-0\.5\.0-py3-none-any\.whl"
        ),
        raw,
    )
    assert wheel_url, "public docs must expose the versioned v0.5.0 wheel install URL"

    assert re.search(
        r"(?:not|no).{0,60}pypi|pypi.{0,60}(?:not|no|unpublished)",
        visible,
    )
    assert not re.search(r"pip(?:3)?\s+install\s+meditate(?:\s|$)", visible)


def test_v0_5_docs_expose_direct_target_output_and_recovery_contract() -> None:
    surfaces = {
        "README.md": _normalized_text(ROOT / "README.md"),
        "docs/index.html": _normalized_text(ROOT / "docs" / "index.html"),
        "docs/design-brief.md": _normalized_text(ROOT / "docs" / "design-brief.md"),
        "docs/llms-full.txt": _normalized_text(ROOT / "docs" / "llms-full.txt"),
        "PRIVACY.md": _normalized_text(ROOT / "PRIVACY.md"),
        "docs/privacy.html": _normalized_text(ROOT / "docs" / "privacy.html"),
    }
    for name, text in surfaces.items():
        assert "--target" in text, f"{name}: missing direct target contract"
        assert "--output" in text, f"{name}: missing compiled output contract"
        assert "read-only" in text, f"{name}: missing source mutability boundary"
        assert "restore" in text, f"{name}: missing recoverability boundary"

    full = surfaces["docs/llms-full.txt"]
    assert "output may also be one input" in full
    assert "frontmatter" in full and "secondary" in full and "not" in full
    assert "source path" in full
    assert "same-user" in full and "filesystem sandbox" in full


def test_v0_5_public_docs_bind_live_target_output_and_fixed_point_receipts() -> None:
    surfaces = {
        name: _normalized_text(ROOT / name)
        for name in (
            "README.md",
            "CHANGELOG.md",
            "docs/index.html",
            "docs/design-brief.md",
            "docs/llms-full.txt",
            "docs/llms.txt",
        )
    }
    run_ids = (
        "20260820t013809z-a65bd797",
        "20260820t013825z-3ccd9834",
        "20260820t013836z-60c301c4",
        "20260820t013850z-874628d9",
        "20260820t013856z-0c0593ca",
    )
    for name, text in surfaces.items():
        for run_id in run_ids:
            assert run_id in text, f"{name}: missing live receipt {run_id}"
        assert "zero provider" in text or "zero-provider" in text
        assert "behavioral equivalence" in text

    full = surfaces["docs/llms-full.txt"]
    assert "exact raw bytes plus heading path" in full
    assert "already represented" in full


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
