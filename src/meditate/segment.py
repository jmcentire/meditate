"""Deterministic Markdown segmentation and locally minted directive IDs."""

from __future__ import annotations

import re
import stat
import unicodedata
from pathlib import Path

from .config import Config
from .models import Directive, TargetDocument
from .util import SCHEMA_VERSION, display_path, fail, sha256_bytes, sha256_text

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n)?$")
_TOP_LIST = re.compile(r"^(?:[-+*]|\d+[.)])[ \t]+")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_PROTECT_START = "<!-- meditate:protect:start"
_PROTECT_END = "<!-- meditate:protect:end -->"


def parse_paths_frontmatter(content: str) -> tuple[str, ...]:
    """Parse the simple root-level ``paths:`` list supported by Claude rules."""

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return ()
    end = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        -1,
    )
    if end < 0:
        return ()
    frontmatter = lines[1:end]
    paths: list[str] = []
    paths_indent: int | None = None

    def clean(value: str) -> str:
        chosen = value.strip()
        if len(chosen) >= 2 and chosen[0] == chosen[-1] and chosen[0] in {"'", '"'}:
            chosen = chosen[1:-1]
        elif " #" in chosen:
            chosen = chosen.split(" #", 1)[0].rstrip()
        return chosen if "\x00" not in chosen else ""

    for line in frontmatter:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if paths_indent is None:
            if stripped.startswith("paths:"):
                paths_indent = indent
                inline = stripped.removeprefix("paths:").strip()
                if inline.startswith("[") and inline.endswith("]"):
                    paths.extend(
                        value for item in inline[1:-1].split(",") if (value := clean(item))
                    )
            continue
        if indent <= paths_indent:
            break
        item = stripped
        if not item.startswith("-"):
            continue
        value = clean(item[1:])
        if value:
            paths.append(value)
    return tuple(dict.fromkeys(paths))


def is_claude_rules_target(path: Path, config: Config) -> bool:
    candidate = path.expanduser().absolute()
    if candidate.suffix.casefold() != ".md" or candidate not in config.allowed_targets:
        return False

    rules_root = (config.sources.claude_home / "rules").expanduser().absolute()
    try:
        relative = candidate.relative_to(rules_root)
    except ValueError:
        pass
    else:
        if relative.parts:
            return True

    parts = candidate.parts
    return any(parts[index : index + 2] == (".claude", "rules") for index in range(len(parts) - 2))


def normalize_directive(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in normalized.split("\n")]
    if lines:
        lines[0] = re.sub(r"^(?:[-+*]|\d+[.)])[ \t]+", "", lines[0])
    return re.sub(r"\s+", " ", "\n".join(lines).strip()).casefold()


def _directive_id(
    logical_path: str,
    headings: tuple[str, ...],
    normalized: str,
    occurrence: int,
) -> str:
    material = "\x00".join(
        (str(SCHEMA_VERSION), logical_path, "/".join(headings), normalized, str(occurrence))
    )
    return f"dir_{sha256_text(material)[:16]}"


def segment_markdown(
    content: str,
    *,
    logical_path: str,
    protected_headings: tuple[str, ...] = (),
) -> tuple[Directive, ...]:
    lines = content.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)

    heading_stack: list[tuple[int, str]] = []
    protected_names = {item.casefold() for item in protected_headings}
    blocks: list[Directive] = []
    occurrences: dict[tuple[tuple[str, ...], str], int] = {}
    index = 0
    if lines and lines[0].strip() == "---":
        frontmatter_end = next(
            (
                line_index
                for line_index, line in enumerate(lines[1:], start=1)
                if line.strip() == "---"
            ),
            -1,
        )
        if frontmatter_end >= 0:
            index = frontmatter_end + 1

    def add_block(start_line: int, end_line: int, kind: str, force_protected: bool = False) -> None:
        start = offsets[start_line]
        end = offsets[end_line] if end_line < len(lines) else len(content)
        raw = content[start:end]
        normalized = normalize_directive(raw)
        if not normalized:
            return
        path = tuple(title for _level, title in heading_stack)
        occurrence_key = (path, normalized)
        occurrence = occurrences.get(occurrence_key, 0)
        occurrences[occurrence_key] = occurrence + 1
        protected = force_protected or any(item.casefold() in protected_names for item in path)
        blocks.append(
            Directive(
                id=_directive_id(logical_path, path, normalized, occurrence),
                target=logical_path,
                heading_path=path,
                kind=kind,
                start=start,
                end=end,
                raw=raw,
                normalized=normalized,
                protected=protected,
            )
        )

    while index < len(lines):
        line = lines[index]
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            index += 1
            continue
        if not line.strip():
            index += 1
            continue
        if _PROTECT_START in line:
            end = index + 1
            while end < len(lines) and _PROTECT_END not in lines[end]:
                end += 1
            if end >= len(lines):
                fail("unclosed_protected_block", f"Unclosed protected block in {logical_path}")
            add_block(index, end + 1, "protected", force_protected=True)
            index = end + 1
            continue
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            width = len(fence.group(1))
            end = index + 1
            closing = re.compile(rf"^[ \t]{{0,3}}{re.escape(marker)}{{{width},}}[ \t]*(?:\r?\n)?$")
            while end < len(lines) and not closing.match(lines[end]):
                end += 1
            if end < len(lines):
                end += 1
            add_block(index, end, "code_fence")
            index = end
            continue
        if _TOP_LIST.match(line):
            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if _HEADING.match(candidate) or _TOP_LIST.match(candidate):
                    break
                if not candidate.strip():
                    lookahead = end + 1
                    while lookahead < len(lines) and not lines[lookahead].strip():
                        lookahead += 1
                    if lookahead >= len(lines):
                        break
                    next_line = lines[lookahead]
                    if (
                        _HEADING.match(next_line)
                        or _TOP_LIST.match(next_line)
                        or not next_line[:1].isspace()
                    ):
                        break
                end += 1
            add_block(index, end, "list_item")
            index = end
            continue

        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if not candidate.strip() or _HEADING.match(candidate) or _TOP_LIST.match(candidate):
                break
            end += 1
        add_block(index, end, "paragraph")
        index = end

    return tuple(blocks)


def load_targets(config: Config) -> tuple[TargetDocument, ...]:
    documents: list[TargetDocument] = []
    for configured in config.targets:
        path = configured.expanduser().absolute()
        if path.is_symlink():
            fail("symlink_target", f"Refusing symlinked target: {path}")
        existed = path.exists()
        if existed:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                fail("non_regular_target", f"Target is not a regular file: {path}")
            data = path.read_bytes()
            mode = stat.S_IMODE(info.st_mode)
        else:
            if not path.parent.exists() or path.parent.is_symlink():
                fail(
                    "missing_target_parent",
                    f"Target parent must exist and not be a symlink: {path.parent}",
                )
            data = b""
            mode = 0o644
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            fail("target_not_utf8", f"Instruction target is not UTF-8: {path}")
        logical = display_path(path)
        directives = segment_markdown(
            content,
            logical_path=logical,
            protected_headings=config.safety.protected_headings,
        )
        documents.append(
            TargetDocument(
                path=path,
                logical_path=logical,
                content=content,
                content_bytes=data,
                sha256=sha256_bytes(data),
                mode=mode,
                existed=existed,
                directives=directives,
                scope_paths=(
                    parse_paths_frontmatter(content) if is_claude_rules_target(path, config) else ()
                ),
            )
        )
    return tuple(documents)
