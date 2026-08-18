"""Deterministic validation of Claude ``@path`` import graphs."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from .config import Config
from .models import ImportDocument, ImportGraph
from .util import canonical_json_bytes, display_path, fail, sha256_bytes

MAX_IMPORT_DEPTH = 4
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_IMPORT = re.compile(r"(?<![A-Za-z0-9_])@([^\s`<>]+)")
_INLINE_CODE = re.compile(r"(?P<ticks>`+).*?(?P=ticks)")
_TRAILING_PUNCTUATION = ".,;:!?)]}"
_CLAUDE_ROOT_NAMES = frozenset({"CLAUDE.md", "CLAUDE.local.md"})


def _imports_from_text(content: str) -> tuple[str, ...]:
    imports: list[str] = []
    fence_marker = ""
    fence_width = 0
    for line in content.splitlines():
        fence = _FENCE.match(line)
        if fence_marker:
            closing = re.fullmatch(
                rf"[ \t]{{0,3}}{re.escape(fence_marker)}{{{fence_width},}}[ \t]*",
                line,
            )
            if closing:
                fence_marker = ""
                fence_width = 0
            continue
        if fence:
            fence_marker = fence.group(1)[0]
            fence_width = len(fence.group(1))
            continue
        visible = _INLINE_CODE.sub("", line)
        for match in _IMPORT.finditer(visible):
            value = match.group(1).rstrip(_TRAILING_PUNCTUATION)
            if value:
                imports.append(value)
    return tuple(imports)


def _resolve_import(containing: Path, value: str) -> Path:
    if "\x00" in value:
        fail("dangling_import", f"Claude import contains a NUL byte in {containing}")
    try:
        candidate = Path(value).expanduser()
    except RuntimeError:
        fail("dangling_import", f"Claude import has an unknown home path: {value}")
    if not candidate.is_absolute():
        candidate = containing.parent / candidate
    return Path(os.path.abspath(candidate))


def build_import_graph(
    config: Config,
    *,
    overrides: dict[Path, tuple[bytes, bool]] | None = None,
) -> ImportGraph:
    """Build a validated graph, optionally substituting proposed target bytes."""

    configured = {path.expanduser().absolute() for path in config.targets}
    roots = tuple(sorted(path for path in configured if path.name in _CLAUDE_ROOT_NAMES))
    override_map = {
        path.expanduser().absolute(): value for path, value in (overrides or {}).items()
    }
    documents: dict[Path, ImportDocument] = {}
    edges: set[tuple[Path, Path]] = set()
    root_set = set(roots)

    def read_document(path: Path, *, imported: bool) -> ImportDocument:
        previous = documents.get(path)
        if previous is not None:
            if imported and not previous.existed:
                fail("dangling_import", f"Claude import does not exist: {path}")
            return previous
        overridden = override_map.get(path)
        if overridden is not None:
            data, existed = overridden
            if imported and not existed:
                fail("dangling_import", f"Claude import does not exist: {path}")
        else:
            try:
                info = path.lstat()
            except FileNotFoundError:
                if imported:
                    fail("dangling_import", f"Claude import does not exist: {path}")
                data = b""
                existed = False
            except OSError as exc:
                fail("dangling_import", f"Cannot inspect Claude import {path}: {exc}")
            else:
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    fail("non_regular_import", f"Claude import is not a regular file: {path}")
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    fail("dangling_import", f"Cannot read Claude import {path}: {exc}")
                existed = True
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            fail("import_not_utf8", f"Claude import is not UTF-8: {path}")
        document = ImportDocument(
            path=path,
            logical_path=display_path(path),
            content=content,
            content_bytes=data,
            sha256=sha256_bytes(data),
            existed=existed,
            is_root=path in root_set,
            configured_target=path in configured,
        )
        documents[path] = document
        return document

    def visit(path: Path, depth: int, stack: tuple[Path, ...]) -> None:
        document = read_document(path, imported=bool(stack))
        references = _imports_from_text(document.content)
        if references and depth >= MAX_IMPORT_DEPTH:
            fail(
                "import_depth_exceeded",
                f"Claude import graph exceeds {MAX_IMPORT_DEPTH} hops at {path}",
            )
        for reference in references:
            destination = _resolve_import(path, reference)
            edges.add((path, destination))
            if destination in stack or destination == path:
                chain = " -> ".join(str(item) for item in (*stack, path, destination))
                fail("circular_import", f"Circular Claude import: {chain}")
            read_document(destination, imported=True)
            if destination not in stack:
                visit(destination, depth + 1, (*stack, path))

    for root in roots:
        visit(root, 0, ())

    ordered_documents = tuple(sorted(documents.values(), key=lambda item: item.logical_path))
    ordered_edges = tuple(
        sorted(
            (
                (documents[source].logical_path, documents[destination].logical_path)
                for source, destination in edges
            ),
            key=lambda item: (item[0], item[1]),
        )
    )
    logical_roots = tuple(sorted(documents[path].logical_path for path in roots))
    core = {
        "max_depth": MAX_IMPORT_DEPTH,
        "roots": list(logical_roots),
        "nodes": [
            {
                "path": item.logical_path,
                "sha256": item.sha256,
                "bytes": len(item.content_bytes),
                "existed": item.existed,
                "root": item.is_root,
                "configured_target": item.configured_target,
            }
            for item in ordered_documents
        ],
        "edges": [{"from": source, "to": destination} for source, destination in ordered_edges],
    }
    return ImportGraph(
        roots=logical_roots,
        documents=ordered_documents,
        edges=ordered_edges,
        digest=sha256_bytes(canonical_json_bytes(core)),
    )
