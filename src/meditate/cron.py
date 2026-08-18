"""Cron entry rendering and non-mutating environment checks."""

from __future__ import annotations

import re
import shlex
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from .config import Config
from .provider import resolve_anthropic_key
from .segment import load_targets
from .util import ensure_private_dir, fail

_SCHEDULE = re.compile(r"^[0-9*/?,\-]+(?:[ \t]+[0-9*/?,\-]+){4}$")


def render_cron_entry(
    config: Config,
    *,
    schedule: str,
    working_directory: Path,
    profile: Path | None,
    apply: bool,
) -> str:
    normalized_schedule = " ".join(schedule.split())
    if not _SCHEDULE.fullmatch(normalized_schedule):
        fail("invalid_cron_schedule", "Cron schedule must contain five conventional fields")
    working = working_directory.expanduser().absolute()
    if not working.is_dir():
        fail("invalid_working_directory", f"Cron working directory does not exist: {working}")
    pieces: list[str] = []
    if profile is not None:
        selected_profile = profile.expanduser().absolute()
        if selected_profile.is_symlink() or not selected_profile.is_file():
            fail(
                "invalid_profile",
                f"Cron profile is not a regular non-symlink file: {selected_profile}",
            )
        pieces.append(f"source {shlex.quote(str(selected_profile))}")
    pieces.append(f"cd {shlex.quote(str(working))}")
    command = [
        sys.executable,
        "-m",
        "meditate",
        "run",
        "--config",
        str(config.config_path),
        "--json",
    ]
    if apply:
        command.append("--apply")
    pieces.append(f"exec {shlex.join(command)}")
    inner = " && ".join(pieces)
    log_path = ensure_private_dir(config.state_root / "logs") / "cron.log"
    return (
        f"{normalized_schedule} /bin/bash -lc {shlex.quote(inner)} "
        f">> {shlex.quote(str(log_path))} 2>&1"
    )


def check_cron_environment(config: Config, *, profile: Path | None) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    executable = Path(sys.executable)
    checks["python"] = str(executable)
    if not executable.is_file():
        fail("cron_python_missing", f"Python executable is unavailable: {executable}")

    if profile is not None:
        selected_profile = profile.expanduser().absolute()
        if selected_profile.is_symlink() or not selected_profile.is_file():
            fail(
                "invalid_profile",
                f"Cron profile is not a regular non-symlink file: {selected_profile}",
            )
        checks["profile"] = str(selected_profile)
    else:
        checks["profile"] = None

    secret, warnings = resolve_anthropic_key(config)
    checks["anthropic_key_source"] = secret.source
    checks["warnings"] = list(warnings)
    checks["targets"] = [target.logical_path for target in load_targets(config)]
    checks["data_root"] = str(ensure_private_dir(config.data_root))
    checks["state_root"] = str(ensure_private_dir(config.state_root))

    if config.kindex.enabled:
        command = config.kindex.command
        resolved = shutil.which(command)
        if not resolved:
            checks["warnings"].append("kindex_unavailable_in_current_path")
        else:
            info = Path(resolved).stat()
            if not stat.S_ISREG(info.st_mode):
                fail("unsafe_kindex_command", f"Kindex command is not a regular file: {resolved}")
            checks["kindex"] = resolved
    checks["ok"] = True
    return checks
