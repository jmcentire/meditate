from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from meditate.config import (
    ApplyConfig,
    Config,
    KindexConfig,
    LLMConfig,
    RetentionConfig,
    SafetyConfig,
    SourceConfig,
)

ConfigFactory = Callable[..., tuple[Config, tuple[Path, ...]]]


@pytest.fixture
def config_factory(tmp_path: Path) -> ConfigFactory:
    def factory(
        contents: tuple[str | None, ...] = ("# Rules\n\n- Keep changes focused.\n",),
        *,
        sources: SourceConfig | None = None,
        safety: SafetyConfig | None = None,
        apply: ApplyConfig | None = None,
        llm: LLMConfig | None = None,
        target_names: tuple[str, ...] | None = None,
    ) -> tuple[Config, tuple[Path, ...]]:
        target_root = tmp_path / "targets"
        target_root.mkdir(exist_ok=True)
        names = target_names or tuple(f"AGENT-{index}.md" for index in range(len(contents)))
        paths = tuple(target_root / name for name in names)
        for path, content in zip(paths, contents, strict=True):
            if content is not None:
                path.write_text(content, encoding="utf-8")
        source = sources or SourceConfig(
            agents=("claude",),
            claude_home=tmp_path / "claude",
            codex_home=tmp_path / "codex",
            include_auto_memory=False,
            include_transcripts=False,
            max_events=20,
            max_excerpt_chars=500,
        )
        chosen_safety = safety or SafetyConfig(
            size_floor_ratio=0.20,
            size_ceiling_ratio=2.0,
            max_churn_ratio=1.0,
            max_malformed_ratio=0.20,
            minimum_free_bytes=1,
        )
        config = Config(
            config_path=tmp_path / "config.toml",
            targets=paths,
            data_root=tmp_path / "data",
            state_root=tmp_path / "state",
            cache_root=tmp_path / "cache",
            env_file=None,
            sources=source,
            kindex=KindexConfig(enabled=False),
            llm=llm or LLMConfig(max_input_tokens=50_000, max_total_input_tokens=50_000),
            safety=chosen_safety,
            apply=apply or ApplyConfig(),
            retention=RetentionConfig(),
            raw_bytes=b"synthetic-config-v1\n",
        )
        return config, paths

    return factory


@pytest.fixture
def replace_config() -> Callable[..., Config]:
    return replace
