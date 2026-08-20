"""Deterministic Markdown segmentation and locally minted directive IDs."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path

from .config import Config
from .models import Directive, InputDocument, TargetDocument
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


def split_frontmatter(content: str) -> tuple[str, str]:
    """Split a character-faithful YAML envelope from a valid UTF-8 document body."""

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", content
    end = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        -1,
    )
    if end < 0:
        return "", content
    boundary = sum(len(line) for line in lines[: end + 1])
    return content[:boundary], content[boundary:]


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
                source_path=logical_path,
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


def _read_input(path: Path, *, require_existing: bool) -> InputDocument:
    try:
        initial = path.lstat()
    except FileNotFoundError:
        initial = None
    if initial is not None:
        if stat.S_ISLNK(initial.st_mode):
            fail("symlink_target", f"Refusing symlinked target: {path}")
        if not stat.S_ISREG(initial.st_mode):
            fail("non_regular_target", f"Target is not a regular file: {path}")
        descriptor = -1
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                fail("non_regular_target", f"Target changed type while opening: {path}")
            if (opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino):
                fail("source_drift", f"Target changed while opening: {path}")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            data = b"".join(chunks)
        except OSError as exc:
            fail("target_read_failed", f"Cannot safely read target {path}: {exc}")
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        existed = True
        mode = stat.S_IMODE(opened.st_mode)
        device = opened.st_dev
        inode = opened.st_ino
    else:
        if require_existing:
            fail("input_missing", f"Semantic input does not exist: {path}")
        if not path.parent.exists() or path.parent.is_symlink():
            fail(
                "missing_target_parent",
                f"Target parent must exist and not be a symlink: {path.parent}",
            )
        data = b""
        existed = False
        mode = 0o644
        device = 0
        inode = 0
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        fail("target_not_utf8", f"Instruction target is not UTF-8: {path}")
    frontmatter, body = split_frontmatter(content)
    return InputDocument(
        path=path,
        logical_path=display_path(path),
        content=content,
        content_bytes=data,
        sha256=sha256_bytes(data),
        mode=mode,
        existed=existed,
        device=device,
        inode=inode,
        frontmatter=frontmatter,
        body=body,
    )


def _combined_content(
    inputs: tuple[InputDocument, ...],
    primary: InputDocument,
    *,
    reuse_primary_directives: bool,
) -> tuple[
    str,
    tuple[str, ...],
    tuple[tuple[int, int, str], ...],
    tuple[str, ...],
]:
    if len(inputs) == 1:
        return inputs[0].content, (), ((0, len(inputs[0].content), inputs[0].logical_path),), ()
    newline = "\r\n" if "\r\n" in primary.content else "\n"
    bodies = [(item, item.body.strip("\r\n")) for item in inputs if item.body.strip()]
    envelope = primary.frontmatter.rstrip("\r\n")
    chunks: list[str] = []
    spans: list[tuple[int, int, str]] = []
    represented: list[str] = []
    cursor = 0
    primary_directives = Counter(
        (directive.heading_path, directive.raw)
        for directive in segment_markdown(primary.body, logical_path=primary.logical_path)
    )
    if envelope:
        chunks.append(envelope)
        cursor += len(envelope)
    for item, body in bodies:
        if reuse_primary_directives and item.path != primary.path:
            item_directives = Counter(
                (directive.heading_path, directive.raw)
                for directive in segment_markdown(item.body, logical_path=item.logical_path)
            )
            if item_directives and all(
                primary_directives[signature] >= count
                for signature, count in item_directives.items()
            ):
                represented.append(item.logical_path)
                continue
        if chunks:
            separator = newline * 2
            chunks.append(separator)
            cursor += len(separator)
        start = cursor
        chunks.append(body)
        cursor += len(body)
        spans.append((start, cursor, item.logical_path))
    content = "".join(chunks)
    if content:
        content += newline
    else:
        content = primary.content
        spans.append((0, len(content), primary.logical_path))
    secondary = tuple(
        item.logical_path for item in inputs if item.path != primary.path and bool(item.frontmatter)
    )
    return content, secondary, tuple(spans), tuple(represented)


def load_target_set(config: Config) -> tuple[tuple[TargetDocument, ...], tuple[InputDocument, ...]]:
    """Load ordered semantic inputs and construct the exact writable document set."""

    output_mode = config.runtime_output is not None
    inputs = tuple(
        _read_input(configured.expanduser().absolute(), require_existing=output_mode)
        for configured in config.input_targets
    )
    physical_inputs: dict[tuple[int, int], str] = {}
    for item in inputs:
        if not item.existed:
            continue
        identity = (item.device, item.inode)
        earlier = physical_inputs.get(identity)
        if earlier is not None:
            fail(
                "duplicate_target",
                f"The same physical input was supplied more than once: {earlier} and "
                f"{item.logical_path}",
            )
        physical_inputs[identity] = item.logical_path
    if not output_mode:
        documents = tuple(
            TargetDocument(
                path=item.path,
                logical_path=item.logical_path,
                content=item.content,
                content_bytes=item.content_bytes,
                sha256=item.sha256,
                mode=item.mode,
                existed=item.existed,
                directives=segment_markdown(
                    item.content,
                    logical_path=item.logical_path,
                    protected_headings=config.safety.protected_headings,
                ),
                scope_paths=(
                    parse_paths_frontmatter(item.content)
                    if is_claude_rules_target(item.path, config)
                    else ()
                ),
                preimage_bytes=item.content_bytes,
                preimage_sha256=item.sha256,
                frontmatter_source=item.logical_path if item.frontmatter else "",
            )
            for item in inputs
        )
        return documents, inputs

    output = config.runtime_output
    if output is None:  # pragma: no cover - narrowed by output_mode
        fail("invalid_target_override", "Output mode requires an output path")
    output_path = output.expanduser().absolute()
    by_path = {item.path: item for item in inputs}
    preimage = by_path.get(output_path) or _read_input(output_path, require_existing=False)
    primary = by_path.get(output_path) or inputs[0]
    content, secondary_frontmatter, source_spans, represented_sources = _combined_content(
        inputs,
        primary,
        reuse_primary_directives=output_path in by_path,
    )
    content_bytes = content.encode("utf-8")
    logical = display_path(output_path)
    directives = segment_markdown(
        content,
        logical_path=logical,
        protected_headings=config.safety.protected_headings,
    )
    attributed_directives = tuple(
        replace(
            directive,
            source_path=next(
                (
                    source_path
                    for start, end, source_path in source_spans
                    if start <= directive.start < end
                ),
                primary.logical_path,
            ),
        )
        for directive in directives
    )
    target = TargetDocument(
        path=output_path,
        logical_path=logical,
        content=content,
        content_bytes=content_bytes,
        sha256=sha256_bytes(content_bytes),
        mode=preimage.mode,
        existed=preimage.existed,
        directives=attributed_directives,
        scope_paths=(
            parse_paths_frontmatter(content) if is_claude_rules_target(output_path, config) else ()
        ),
        preimage_bytes=preimage.content_bytes,
        preimage_sha256=preimage.sha256,
        frontmatter_source=primary.logical_path if primary.frontmatter else "",
        secondary_frontmatter_sources=secondary_frontmatter,
        represented_input_sources=represented_sources,
    )
    return (target,), inputs


def load_targets(config: Config) -> tuple[TargetDocument, ...]:
    """Compatibility wrapper returning only writable semantic documents."""

    return load_target_set(config)[0]
