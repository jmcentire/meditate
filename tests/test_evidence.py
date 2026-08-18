from __future__ import annotations

from dataclasses import replace

from conftest import ConfigFactory

from meditate.evidence import build_inspection, detect_overlaps, enrich_events, select_events
from meditate.imports import build_import_graph
from meditate.models import Authority, EvidenceEvent, SourceStats
from meditate.segment import load_targets


def event(
    event_id: str,
    text: str,
    timestamp: str,
    *,
    session: str | None,
    source: str = "claude_history_user",
    authority: Authority = Authority.REPEATED_USER_PREFERENCE,
) -> EvidenceEvent:
    return EvidenceEvent(
        id=event_id,
        source_kind=source,
        authority=authority,
        timestamp=timestamp,
        session_id=session,
        scope="global",
        text=text,
        source_locator=f"fixture:{event_id}",
        content_sha256=event_id.removeprefix("evt_").ljust(64, "0")[:64],
    )


def test_corroboration_counts_independent_sessions_not_copied_memory() -> None:
    text = "Always verify the live surface before claiming deployment."
    events = (
        event("evt_one", text, "2024-01-01T00:00:00Z", session="a"),
        event("evt_two", text, "2025-01-01T00:00:00Z", session="b"),
        event(
            "evt_memory_one",
            text,
            "2026-01-01T00:00:00Z",
            session=None,
            source="claude_auto_memory",
            authority=Authority.AUTO_MEMORY,
        ),
        event(
            "evt_memory_two",
            text,
            "2026-02-01T00:00:00Z",
            session=None,
            source="claude_auto_memory",
            authority=Authority.AUTO_MEMORY,
        ),
    )
    enriched = enrich_events(events)
    assert {item.corroboration for item in enriched} == {3}


def test_behavioral_corroboration_recognizes_independent_commit_variants() -> None:
    events = (
        event(
            "evt_commit_one",
            "Once done, commit, merge, push, deploy, rev, and release.",
            "2026-04-01T00:00:00Z",
            session="one",
        ),
        event(
            "evt_commit_two",
            "New Rule: commit, merge, push, deploy. Why leave staged changes around?",
            "2026-05-01T00:00:00Z",
            session="two",
        ),
        event(
            "evt_commit_three",
            "All should be commit, merge, push, deploy, tested in prod.",
            "2026-06-01T00:00:00Z",
            session="three",
        ),
    )
    enriched = enrich_events(events)
    assert {item.corroboration for item in enriched} == {3}
    assert next(item for item in enriched if item.id == "evt_commit_two").correction_score >= 10


def test_selection_prefers_signal_but_reserves_old_temporal_breadth(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory()
    config = replace(config, sources=replace(config.sources, max_events=5))
    events = tuple(
        event(
            f"evt_recent_{index}",
            f"New rule: always verify deterministic result {index}.",
            f"2026-08-{10 + index:02d}T00:00:00Z",
            session=f"recent-{index}",
        )
        for index in range(6)
    ) + (
        event(
            "evt_old_context",
            "Older context says preserve hand edits before restore.",
            "2021-01-01T00:00:00Z",
            session="old",
        ),
    )
    selected = select_events(enrich_events(events), config)
    assert len(selected) == 5
    assert any(item.id == "evt_old_context" for item in selected)
    assert list(selected) == sorted(selected, key=lambda item: (item.timestamp, item.id))


def test_named_negation_overlap_detects_commit_reversal(config_factory: ConfigFactory) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    targets = load_targets(config)
    events = enrich_events(
        (
            event(
                "evt_new",
                "New rule: commit, merge, push, and deploy completed work by default.",
                "2026-08-18T00:00:00Z",
                session="new",
            ),
        )
    )
    overlaps = detect_overlaps(targets, events)
    assert overlaps
    assert overlaps[0]["detector"] == "negation_pair"
    assert "commit" in overlaps[0]["shared_subject_terms"]


def test_target_relevance_keeps_explicit_commit_reversal_amid_unrelated_corrections(
    config_factory: ConfigFactory,
) -> None:
    config, _paths = config_factory(("# Git\n\n- Commit only when asked.\n",))
    config = replace(config, sources=replace(config.sources, max_events=12))
    relevant = event(
        "evt_relevant_commit",
        "New Rule: commit, merge, push, deploy. Why leave staged changes around?",
        "2026-05-01T00:00:00Z",
        session="commit-session",
    )
    unrelated = tuple(
        event(
            f"evt_unrelated_{index}",
            (
                "Do not explain this story beat; never repeat it; stop adding exposition; "
                f"this is wrong in chapter {index}."
            ),
            f"2026-07-{(index % 28) + 1:02d}T00:00:00Z",
            session=f"story-{index}",
        )
        for index in range(40)
    )
    result = build_inspection(
        load_targets(config),
        build_import_graph(config),
        unrelated + (relevant,),
        SourceStats(),
        (),
        config,
    )
    selected = {item.id: item for item in result.selected_events}
    assert "evt_relevant_commit" in selected
    assert selected["evt_relevant_commit"].target_relevance > 0


def test_identity_push_metadata_is_not_a_behavioral_overlap(
    config_factory: ConfigFactory,
) -> None:
    content = (
        "# Identity\n\n- Push to: jmcentire (GitHub)\n\n"
        "# Preferences\n\n- Commit only when asked.\n"
    )
    config, _paths = config_factory((content,))
    targets = load_targets(config)
    events = enrich_events(
        (
            event(
                "evt_push_behavior",
                "New Rule: commit, merge, push, deploy completed work.",
                "2026-08-18T00:00:00Z",
                session="new",
            ),
        )
    )
    overlaps = detect_overlaps(targets, events)
    identity_id = targets[0].directives[0].id
    assert all(candidate["directive_id"] != identity_id for candidate in overlaps)
