"""Deterministic vitality scoring, corroboration, and overlap candidates."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from itertools import combinations

from .config import Config
from .models import EvidenceEvent, InspectionResult, SourceStats, TargetDocument

_CORRECTION = re.compile(
    r"(?i)\b(?:new rule|i (?:said|asked)|you (?:did not|didn't)|stop (?:doing|saying|thrashing)|"
    r"do not|don't|never again|why (?:would|did)|that's (?:wrong|not)|this is wrong|must not)\b"
)
_DIRECTIVE = re.compile(
    r"(?i)\b(?:must|should|always|never|do not|don't|default|prefer|only|ensure|require|"
    r"commit|merge|push|deploy|verify|test|archive|restore|remember)\b"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)
_STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "this",
    "to",
    "we",
    "what",
    "when",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
    "do",
    "not",
    "only",
    "should",
    "must",
    "always",
    "never",
    "default",
}
_NEGATIVE = re.compile(r"(?i)\b(?:do not|don't|never|only when asked|must not|no longer)\b")
_POSITIVE = re.compile(
    r"(?i)\b(?:by default|always|go ahead|make it so|commit|merge|push|deploy)\b"
)
_EXPLICIT_DURABLE = re.compile(
    r"(?i)\b(?:new rule|general directives?|add (?:that|this) to (?:your )?memory|"
    r"every future interaction|always, forever)\b"
)
_BEHAVIOR_ANCHORS = {
    "archive",
    "ask",
    "build",
    "clear",
    "commit",
    "delete",
    "deploy",
    "edit",
    "fix",
    "kindex",
    "merge",
    "plan",
    "push",
    "release",
    "restore",
    "review",
    "test",
    "verify",
    "write",
}
_NON_BEHAVIORAL_HEADINGS = {"api keys & secrets", "identity"}


def _fingerprint(text: str) -> str:
    tokens = [token.casefold() for token in _TOKEN.findall(text)]
    meaningful = [token for token in tokens if token not in _STOP and len(token) > 2]
    return " ".join(meaningful[:28])


def _scores(text: str) -> tuple[int, int]:
    correction = len(_CORRECTION.findall(text))
    directive = len(_DIRECTIVE.findall(text))
    uppercase = sum(1 for token in text.split() if len(token) > 3 and token.isupper())
    explicit = len(_EXPLICIT_DURABLE.findall(text))
    return min(30, correction * 4 + explicit * 10 + min(3, uppercase)), min(30, directive)


def _behavior_keys(text: str) -> tuple[str, ...]:
    anchors = sorted(set(_fingerprint(text).split()) & _BEHAVIOR_ANCHORS)
    if len(anchors) < 3:
        return ()
    # Three-anchor combinations recognize a stable behavioral core even when
    # one occurrence adds release/test/restore qualifiers. A two-token match is
    # too broad for durable-preference corroboration.
    return tuple(" ".join(group) for group in combinations(anchors, 3))


def enrich_events(events: tuple[EvidenceEvent, ...]) -> tuple[EvidenceEvent, ...]:
    sessions_by_fingerprint: dict[str, set[str]] = defaultdict(set)
    no_session_fingerprints: set[str] = set()
    sessions_by_behavior: dict[str, set[str]] = defaultdict(set)
    no_session_behaviors: set[str] = set()
    for event in events:
        fingerprint = _fingerprint(event.text)
        if not fingerprint:
            continue
        if event.session_id:
            sessions_by_fingerprint[fingerprint].add(event.session_id)
        else:
            no_session_fingerprints.add(fingerprint)
        for behavior in _behavior_keys(event.text):
            if event.session_id:
                sessions_by_behavior[behavior].add(event.session_id)
            else:
                no_session_behaviors.add(behavior)

    enriched: list[EvidenceEvent] = []
    for event in events:
        correction, directive = _scores(event.text)
        fingerprint = _fingerprint(event.text)
        corroboration = len(sessions_by_fingerprint.get(fingerprint, set()))
        if fingerprint in no_session_fingerprints:
            corroboration += 1
        behavior_corroboration = 0
        for behavior in _behavior_keys(event.text):
            count = len(sessions_by_behavior.get(behavior, set()))
            if behavior in no_session_behaviors:
                count += 1
            behavior_corroboration = max(behavior_corroboration, count)
        enriched.append(
            replace(
                event,
                correction_score=correction,
                directive_score=directive,
                corroboration=max(1, corroboration, behavior_corroboration),
            )
        )
    return tuple(enriched)


def _with_target_relevance(
    events: tuple[EvidenceEvent, ...], targets: tuple[TargetDocument, ...]
) -> tuple[EvidenceEvent, ...]:
    subjects = [
        _subject(directive.raw)
        for target in targets
        for directive in target.directives
        if _is_behavioral_directive(directive.heading_path, directive.raw)
        and _subject(directive.raw)
    ]
    output: list[EvidenceEvent] = []
    for event in events:
        event_subject = _subject(event.text)
        relevance = 0
        for directive_subject in subjects:
            shared = event_subject & directive_subject
            if not shared:
                continue
            anchors = shared & _BEHAVIOR_ANCHORS
            relevance = max(relevance, min(24, len(shared) * 2 + len(anchors) * 6))
        output.append(replace(event, target_relevance=relevance))
    return tuple(output)


def _is_behavioral_directive(heading_path: tuple[str, ...], text: str) -> bool:
    headings = {heading.casefold() for heading in heading_path}
    if headings & _NON_BEHAVIORAL_HEADINGS:
        return False
    normalized = text.lstrip().casefold()
    return not normalized.startswith(("- push to:", "- git commits as:"))


def _recency(timestamp: str) -> float:
    try:
        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        days = max(0.0, (datetime.now(UTC) - instant).total_seconds() / 86400)
    except ValueError:
        return 0.0
    # A one-year half-life prefers new evidence without erasing older context.
    return math.exp(-math.log(2) * days / 365.0)


def _rank(event: EvidenceEvent) -> tuple[float, str, str]:
    authority = 9 - int(event.authority)
    score = (
        authority * 4
        + event.correction_score * 3
        + event.directive_score
        + min(5, event.corroboration) * 2
        + event.target_relevance * 2
        + _recency(event.timestamp) * 8
    )
    return score, event.timestamp, event.id


def select_events(events: tuple[EvidenceEvent, ...], config: Config) -> tuple[EvidenceEvent, ...]:
    if len(events) <= config.sources.max_events:
        return tuple(sorted(events, key=lambda item: (item.timestamp, item.id)))
    ranked = sorted(events, key=_rank, reverse=True)
    primary_count = max(1, int(config.sources.max_events * 0.80))
    selected: dict[str, EvidenceEvent] = {event.id: event for event in ranked[:primary_count]}

    # Reserve the tail for temporal breadth: oldest event per year/source pair.
    breadth: dict[tuple[str, str], EvidenceEvent] = {}
    for event in events:
        year = event.timestamp[:4]
        key = (year, event.source_kind)
        previous = breadth.get(key)
        if previous is None or event.timestamp < previous.timestamp:
            breadth[key] = event
    for event in sorted(breadth.values(), key=lambda item: (item.timestamp, item.id)):
        if len(selected) >= config.sources.max_events:
            break
        selected[event.id] = event
    if len(selected) < config.sources.max_events:
        for event in ranked:
            selected.setdefault(event.id, event)
            if len(selected) >= config.sources.max_events:
                break
    return tuple(sorted(selected.values(), key=lambda item: (item.timestamp, item.id)))


def _subject(text: str) -> set[str]:
    return {token for token in _fingerprint(text).split() if len(token) > 2}


def detect_overlaps(
    targets: tuple[TargetDocument, ...], events: tuple[EvidenceEvent, ...]
) -> tuple[dict[str, object], ...]:
    candidates_by_directive: dict[
        str, list[tuple[tuple[int, int, int, str], dict[str, object]]]
    ] = defaultdict(list)
    directives = [
        item
        for target in targets
        for item in target.directives
        if _is_behavioral_directive(item.heading_path, item.raw)
    ]
    for directive in directives:
        left = _subject(directive.raw)
        if not left:
            continue
        for event in events:
            right = _subject(event.text)
            shared = left & right
            if not shared:
                continue
            opposite = (_NEGATIVE.search(directive.raw) and _POSITIVE.search(event.text)) or (
                _POSITIVE.search(directive.raw) and _NEGATIVE.search(event.text)
            )
            if opposite and (len(shared) >= 2 or shared & {"commit", "deploy", "push", "merge"}):
                candidate: dict[str, object] = {
                    "detector": "negation_pair",
                    "directive_id": directive.id,
                    "evidence_id": event.id,
                    "shared_subject_terms": sorted(shared)[:8],
                }
                score = (
                    event.target_relevance,
                    event.correction_score,
                    len(shared),
                    event.timestamp,
                )
                candidates_by_directive[directive.id].append((score, candidate))
    balanced: list[tuple[tuple[int, int, int, str], dict[str, object]]] = []
    for candidates in candidates_by_directive.values():
        balanced.extend(sorted(candidates, key=lambda item: item[0], reverse=True)[:3])
    balanced.sort(key=lambda item: item[0], reverse=True)
    return tuple(candidate for _score, candidate in balanced[:30])


def build_inspection(
    targets: tuple[TargetDocument, ...],
    events: tuple[EvidenceEvent, ...],
    stats: SourceStats,
    warnings: tuple[str, ...],
    config: Config,
) -> InspectionResult:
    enriched = _with_target_relevance(enrich_events(events), targets)
    selected = select_events(enriched, config)
    malformed_ratio = stats.malformed_records / max(1, stats.records_seen)
    degraded: list[str] = []
    if malformed_ratio > config.safety.max_malformed_ratio:
        degraded.append("malformed_ratio_exceeded")
    return InspectionResult(
        targets=targets,
        events=enriched,
        selected_events=selected,
        stats=stats,
        overlaps=detect_overlaps(targets, selected),
        warnings=warnings,
        degraded=tuple(degraded),
    )
