"""Shared immutable models used across the Meditate pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal


class Authority(IntEnum):
    """Lower numeric value means stronger durable authority."""

    USER_CORRECTION = 1
    CURRENT_INSTRUCTION = 2
    REPEATED_USER_PREFERENCE = 3
    DETERMINISTIC_OUTCOME = 4
    KINDEX_ACTIVE = 5
    AUTO_MEMORY = 6
    ASSISTANT_INFERENCE = 7
    UNKNOWN = 8


@dataclass(frozen=True)
class RedactionFinding:
    kind: str
    confidence: Literal["high", "low"]
    digest: str


@dataclass(frozen=True)
class EvidenceEvent:
    id: str
    source_kind: str
    authority: Authority
    timestamp: str
    session_id: str | None
    scope: str
    text: str
    source_locator: str
    content_sha256: str
    unattended_eligible: bool = False
    correction_score: int = 0
    directive_score: int = 0
    corroboration: int = 1
    target_relevance: int = 0
    redactions: tuple[RedactionFinding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_kind": self.source_kind,
            "authority": int(self.authority),
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "scope": self.scope,
            "text": self.text,
            "source_locator": self.source_locator,
            "content_sha256": self.content_sha256,
            "unattended_eligible": self.unattended_eligible,
            "correction_score": self.correction_score,
            "directive_score": self.directive_score,
            "corroboration": self.corroboration,
            "target_relevance": self.target_relevance,
            "redactions": [
                {"kind": f.kind, "confidence": f.confidence, "digest": f.digest}
                for f in self.redactions
            ],
        }


@dataclass(frozen=True)
class Directive:
    id: str
    target: str
    heading_path: tuple[str, ...]
    kind: str
    start: int
    end: int
    raw: str
    normalized: str
    protected: bool = False

    def packet_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "heading_path": list(self.heading_path),
            "kind": self.kind,
            "text": self.raw,
            "protected": self.protected,
        }


@dataclass(frozen=True)
class TargetDocument:
    path: Path
    logical_path: str
    content: str
    content_bytes: bytes
    sha256: str
    mode: int
    existed: bool
    directives: tuple[Directive, ...]
    scope_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportDocument:
    """One document participating in a Claude @import graph."""

    path: Path
    logical_path: str
    content: str
    content_bytes: bytes
    sha256: str
    existed: bool
    is_root: bool
    configured_target: bool


@dataclass(frozen=True)
class ImportGraph:
    """Validated Claude @import graph plus content kept out of public reports."""

    roots: tuple[str, ...]
    documents: tuple[ImportDocument, ...]
    edges: tuple[tuple[str, str], ...]
    digest: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "max_depth": 4,
            "roots": list(self.roots),
            "nodes": [
                {
                    "path": item.logical_path,
                    "sha256": item.sha256,
                    "bytes": len(item.content_bytes),
                    "existed": item.existed,
                    "root": item.is_root,
                    "configured_target": item.configured_target,
                }
                for item in self.documents
            ],
            "edges": [{"from": source, "to": destination} for source, destination in self.edges],
            "digest": self.digest,
        }


@dataclass(frozen=True)
class SourceStats:
    files_seen: int = 0
    bytes_seen: int = 0
    records_seen: int = 0
    records_emitted: int = 0
    malformed_records: int = 0
    unknown_records: int = 0
    sensitive_records_excluded: int = 0
    duplicate_records: int = 0

    def merge(self, other: SourceStats) -> SourceStats:
        return SourceStats(
            files_seen=self.files_seen + other.files_seen,
            bytes_seen=self.bytes_seen + other.bytes_seen,
            records_seen=self.records_seen + other.records_seen,
            records_emitted=self.records_emitted + other.records_emitted,
            malformed_records=self.malformed_records + other.malformed_records,
            unknown_records=self.unknown_records + other.unknown_records,
            sensitive_records_excluded=(
                self.sensitive_records_excluded + other.sensitive_records_excluded
            ),
            duplicate_records=self.duplicate_records + other.duplicate_records,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "files_seen": self.files_seen,
            "bytes_seen": self.bytes_seen,
            "records_seen": self.records_seen,
            "records_emitted": self.records_emitted,
            "malformed_records": self.malformed_records,
            "unknown_records": self.unknown_records,
            "sensitive_records_excluded": self.sensitive_records_excluded,
            "duplicate_records": self.duplicate_records,
        }


ApplyMode = Literal["attended", "unattended"]


@dataclass(frozen=True)
class InspectionResult:
    targets: tuple[TargetDocument, ...]
    events: tuple[EvidenceEvent, ...]
    selected_events: tuple[EvidenceEvent, ...]
    stats: SourceStats
    import_graph: ImportGraph
    overlaps: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()


@dataclass
class RunUsage:
    calls: int = 0
    estimated_input_tokens: int = 0
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0
    stop_reason: str = ""
    model_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "estimated_input_tokens": self.estimated_input_tokens,
            "actual_input_tokens": self.actual_input_tokens,
            "actual_output_tokens": self.actual_output_tokens,
            "stop_reason": self.stop_reason,
            "model_id": self.model_id,
        }


@dataclass
class ValidatedPlan:
    run_id: str
    plan_sha256: str
    model: str
    provider: str
    raw_plan: dict[str, Any]
    proposed_contents: dict[str, str]
    proposed_hashes: dict[str, str]
    minimum_apply_mode: ApplyMode
    changed_directive_count: int
    directive_count: int
    blocked_reasons: tuple[str, ...] = ()
    usage: RunUsage = field(default_factory=RunUsage)
    model_id: str = ""
    prompt_version: str = ""
    prompt_sha256: str = ""
    semantic_verification: dict[str, str] = field(default_factory=dict)
    consolidation_preflight: dict[str, Any] = field(default_factory=dict)
    post_directive_count: int = 0
    escalated_directive_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    import_graph_before: dict[str, Any] = field(default_factory=dict)
    import_graph_after: dict[str, Any] = field(default_factory=dict)
    decision_request: dict[str, Any] | None = None
    operator_decision: dict[str, Any] | None = None
    parent_plan_sha256: str = ""
    parent_packet_sha256: str = ""
    decision_lineage: dict[str, Any] = field(default_factory=dict)
