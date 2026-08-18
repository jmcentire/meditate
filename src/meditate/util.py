"""Filesystem, hashing, locking, and safe serialization helpers."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

SCHEMA_VERSION = 1
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")


class MeditateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> NoReturn:
    raise MeditateError(code, message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail("invalid_json", f"Cannot read valid JSON from {path}: {type(exc).__name__}")


def new_run_id(now: datetime | None = None) -> str:
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    return f"{instant:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        fail("invalid_run_id", f"Invalid run ID: {run_id!r}")
    return run_id


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        fail("state_root_unreadable", f"Cannot stat state directory {path}: {exc}")
    if mode & stat.S_IWOTH:
        fail("world_writable_state_root", f"Refusing world-writable state directory: {path}")
    if mode & 0o077:
        path.chmod(mode & ~0o077)
    return path


def ensure_not_foreign_root(home: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        owner = home.stat().st_uid if home.exists() else -1
        if owner not in {-1, 0}:
            fail("foreign_home_as_root", f"Refusing to operate as root against {home}")


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    ensure_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".meditate-", dir=path.parent)
    temp_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        info = temp_path.lstat()
        if not stat.S_ISREG(info.st_mode):
            fail("unsafe_tempfile", f"Temporary path is not a regular file: {temp_path}")
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def atomic_write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    atomic_write(path, canonical_json_bytes(value), mode=mode)


def resolve_allowlisted(path: Path, allowed: set[Path], *, allow_missing: bool = False) -> Path:
    expanded = path.expanduser().absolute()
    if "\x00" in str(expanded):
        fail("invalid_target", "Target contains a NUL byte")
    if expanded.is_symlink():
        fail("symlink_target", f"Refusing symlinked target: {expanded}")
    if expanded.exists():
        resolved = expanded.resolve(strict=True)
        if not resolved.is_file():
            fail("non_regular_target", f"Target is not a regular file: {resolved}")
    else:
        if not allow_missing:
            fail("missing_target", f"Target does not exist: {expanded}")
        parent = expanded.parent.resolve(strict=True)
        resolved = parent / expanded.name
    allowed_resolved = {item.expanduser().absolute() for item in allowed}
    if resolved not in allowed_resolved:
        fail(
            "target_not_allowlisted",
            f"Target is outside the exact configured allowlist: {resolved}",
        )
    return resolved


@contextlib.contextmanager
def exclusive_lock(path: Path, *, blocking: bool = False) -> Iterator[None]:
    ensure_private_dir(path.parent)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError:
            fail("lock_held", f"Another Meditate operation holds {path}")
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def display_path(path: Path, home: Path | None = None) -> str:
    chosen_home = home or Path.home()
    try:
        return f"~/{path.resolve().relative_to(chosen_home.resolve())}"
    except (OSError, ValueError):
        return str(path)
