"""Deterministic, local qualification of planner work candidates.

This module does not decide that two directives are semantically equivalent.  It
only identifies structural shapes that make an LLM consolidation call worth
attempting.  Behavioral equivalence remains the job of an independent sentinel
suite.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .models import Directive, InspectionResult
from .util import canonical_json_bytes, sha256_bytes

_MIN_OVERLAP_TERMS = 2
_REQUIRED_HEADING = re.compile(r"(?i)\b(?:required|must|critical|mandatory)\b")
_EXCEPTION_BRANCH = re.compile(r"(?i)\b(?:but|except|unless|however|only if|provided that)\b")
_SUBJECT_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_SUBJECT_STOP_WORDS = frozenset(
    {
        "and",
        "because",
        "but",
        "directive",
        "do",
        "does",
        "except",
        "for",
        "from",
        "however",
        "if",
        "in",
        "it",
        "may",
        "must",
        "not",
        "only",
        "or",
        "provided",
        "rule",
        "should",
        "that",
        "the",
        "this",
        "to",
        "unless",
        "when",
        "with",
    }
)


@dataclass(frozen=True)
class CandidateCluster:
    """One non-overlapping set of directives that a planner may disposition."""

    id: str
    target: str
    heading_path: tuple[str, ...]
    source_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    pre_bytes: int
    importance: int
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "heading_path": list(self.heading_path),
            "source_ids": list(self.source_ids),
            "reason_codes": list(self.reason_codes),
            "pre_bytes": self.pre_bytes,
            "importance": self.importance,
            "evidence_ids": list(self.evidence_ids),
        }


def _cluster_id(target: str, heading_path: tuple[str, ...], source_ids: tuple[str, ...]) -> str:
    core = {
        "target": target,
        "heading_path": list(heading_path),
        "source_ids": list(source_ids),
    }
    return f"cand_{sha256_bytes(canonical_json_bytes(core))[:16]}"


def _importance(directives: list[Directive], *, evidence_count: int, reason_codes: set[str]) -> int:
    heading = " ".join(directives[0].heading_path) if directives else ""
    score = min(40, evidence_count * 8)
    if _REQUIRED_HEADING.search(heading):
        score += 10
    if "exact_duplicate" in reason_codes:
        score += 80
    if "exception_lineage" in reason_codes:
        score += 60
    return min(100, score)


def _subject_terms(directive: Directive) -> frozenset[str]:
    """Return conservative lexical subject terms for exception-lineage grouping."""

    return frozenset(
        token
        for token in _SUBJECT_TOKEN.findall(directive.normalized)
        if len(token) >= 3 and token not in _SUBJECT_STOP_WORDS
    )


def _exception_components(directives: list[Directive]) -> list[list[Directive]]:
    """Group only exception-bearing directives with a concrete shared subject."""

    terms = {item.id: _subject_terms(item) for item in directives}
    neighbors: dict[str, set[str]] = defaultdict(set)
    by_id = {item.id: item for item in directives}
    for index, left in enumerate(directives):
        for right in directives[index + 1 :]:
            if len(terms[left.id] & terms[right.id]) < _MIN_OVERLAP_TERMS:
                continue
            neighbors[left.id].add(right.id)
            neighbors[right.id].add(left.id)

    components: list[list[Directive]] = []
    visited: set[str] = set()
    for directive in directives:
        if directive.id in visited or not neighbors[directive.id]:
            continue
        stack = [directive.id]
        component_ids: set[str] = set()
        while stack:
            identifier = stack.pop()
            if identifier in component_ids:
                continue
            component_ids.add(identifier)
            stack.extend(neighbors[identifier] - component_ids)
        visited.update(component_ids)
        components.append(
            sorted((by_id[identifier] for identifier in component_ids), key=lambda item: item.start)
        )
    return components


def derive_candidate_clusters(inspection: InspectionResult) -> tuple[CandidateCluster, ...]:
    """Return structural candidates without making a semantic-equivalence claim.

    Only locally identifiable defect shapes qualify a provider call. Density and
    byte count are metrics, never defects: a long well-formed list is allowed to
    be a stable fixed point. Exact duplicates are confirmed defects; repeated
    exception branches are bounded review candidates. History overlap supplies
    evidence for those defects but cannot create a defect by itself.
    """

    directives = {
        directive.id: directive
        for target in inspection.targets
        for directive in target.directives
        if not directive.protected
    }
    events = {event.id: event for event in inspection.selected_events}
    overlap_evidence: dict[str, set[str]] = defaultdict(set)
    for overlap in inspection.overlaps:
        directive_id = overlap.get("directive_id")
        evidence_id = overlap.get("evidence_id")
        shared = overlap.get("shared_subject_terms")
        if (
            isinstance(directive_id, str)
            and directive_id in directives
            and isinstance(evidence_id, str)
            and evidence_id in events
            and isinstance(shared, list)
            and len({str(term).casefold() for term in shared if str(term).strip()})
            >= _MIN_OVERLAP_TERMS
        ):
            overlap_evidence[directive_id].add(evidence_id)

    by_heading: dict[tuple[str, tuple[str, ...]], list[Directive]] = defaultdict(list)
    for directive in directives.values():
        by_heading[(directive.target, directive.heading_path)].append(directive)

    clusters: list[CandidateCluster] = []
    for (target, heading_path), grouped in sorted(by_heading.items()):
        ordered = sorted(grouped, key=lambda item: (item.start, item.id))
        by_normalized: dict[str, list[Directive]] = defaultdict(list)
        for candidate_directive in ordered:
            if candidate_directive.normalized:
                by_normalized[candidate_directive.normalized].append(candidate_directive)

        claimed: set[str] = set()
        for duplicates in by_normalized.values():
            if len(duplicates) < 2:
                continue
            source_ids = tuple(item.id for item in duplicates)
            claimed.update(source_ids)
            evidence_ids = tuple(
                sorted(
                    {
                        event_id
                        for item in duplicates
                        for event_id in overlap_evidence.get(item.id, ())
                    }
                )
            )
            reasons = {"exact_duplicate"}
            clusters.append(
                CandidateCluster(
                    id=_cluster_id(target, heading_path, source_ids),
                    target=target,
                    heading_path=heading_path,
                    source_ids=source_ids,
                    reason_codes=("exact_duplicate",),
                    pre_bytes=sum(len(item.raw.encode("utf-8")) for item in duplicates),
                    importance=_importance(
                        duplicates, evidence_count=len(evidence_ids), reason_codes=reasons
                    ),
                    evidence_ids=evidence_ids,
                )
            )

        exception_directives = [
            item
            for item in ordered
            if item.id not in claimed and _EXCEPTION_BRANCH.search(item.raw)
        ]
        for exception_component in _exception_components(exception_directives):
            source_ids = tuple(item.id for item in exception_component)
            evidence_ids = tuple(
                sorted(
                    {
                        event_id
                        for item in exception_component
                        for event_id in overlap_evidence.get(item.id, ())
                    }
                )
            )
            reasons = {"exception_lineage"}
            clusters.append(
                CandidateCluster(
                    id=_cluster_id(target, heading_path, source_ids),
                    target=target,
                    heading_path=heading_path,
                    source_ids=source_ids,
                    reason_codes=("exception_lineage",),
                    pre_bytes=sum(len(item.raw.encode("utf-8")) for item in exception_component),
                    importance=_importance(
                        exception_component,
                        evidence_count=len(evidence_ids),
                        reason_codes=reasons,
                    ),
                    evidence_ids=evidence_ids,
                )
            )

    # One immutable run owns the complete non-overlapping defect set. This is
    # required for the fixed-point contract: a successful rewrite cannot leave
    # a second known defect for the next invocation to discover. Correctness
    # class is ranked before size; count and bytes only make ordering stable.
    ranked = sorted(
        clusters,
        key=lambda item: (
            -item.importance,
            -len(item.source_ids),
            -item.pre_bytes,
            item.target,
            item.heading_path,
            item.id,
        ),
    )
    return tuple(ranked)


def candidate_summary(clusters: tuple[CandidateCluster, ...]) -> dict[str, Any]:
    """Public, locally computed preflight metrics."""

    defect_classes = sorted({reason for item in clusters for reason in item.reason_codes})
    confirmed = [item for item in defect_classes if item == "exact_duplicate"]
    review = [item for item in defect_classes if item != "exact_duplicate"]
    return {
        "status": (
            "defects_detected"
            if confirmed
            else "review_candidates_detected"
            if review
            else "no_detectable_defects"
        ),
        "method": "deterministic_defects_v4",
        "clusters": len(clusters),
        "directives": sum(len(item.source_ids) for item in clusters),
        "pre_bytes": sum(item.pre_bytes for item in clusters),
        "candidate_ids": [item.id for item in clusters],
        "defect_classes": defect_classes,
        "confirmed_defect_classes": confirmed,
        "review_candidate_classes": review,
    }
