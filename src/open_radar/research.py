"""Structured research evidence and deterministic analysis proposals."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping

from .change_detection import ChangeEvent
from .domain import ID_PATTERN, ensure_utc, iso_utc


PROPOSAL_RULE_VERSION = "proposal-rules/1"
PROPOSAL_STATUSES = {"pending", "in_review", "accepted", "rejected"}
EVIDENCE_KINDS = {"fact", "inference", "opinion"}
SOURCE_TYPES = {"url", "commit", "observation", "snapshot"}
DIMENSIONS = {"innovation", "engineering", "relevance", "activity", "learning_value"}
PROPOSAL_ID_PATTERN = re.compile(r"^proposal-[0-9a-f]{24}$")
PROPOSAL_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHANGE_EVENT_ID_PATTERN = re.compile(r"^change-[0-9a-f]{24}$")
EVIDENCE_ID_PATTERN = re.compile(r"^evidence-[a-z0-9][a-z0-9-]*$")


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    text = _require_string(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO-8601 timestamp") from exc
    try:
        return ensure_utc(parsed)
    except ValueError as exc:
        raise ValueError(f"{path} must use UTC") from exc


def _json_value(value: Any, path: str) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be JSON serializable") from exc
    return value


@dataclass(frozen=True)
class AnalysisProposal:
    """A review-only proposal derived from one deterministic change event."""

    schema_version: int
    proposal_id: str
    fingerprint: str
    project_id: str
    provider: str
    repository_id: int
    trigger_event_id: str
    trigger_fingerprint: str
    requested_at: datetime
    question: str
    scope: tuple[str, ...]
    status: str
    rule_version: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalysisProposal":
        if not isinstance(data, Mapping):
            raise ValueError("analysis proposal must be an object")
        expected = {
            "schema_version",
            "proposal_id",
            "fingerprint",
            "project_id",
            "provider",
            "repository_id",
            "trigger_event_id",
            "trigger_fingerprint",
            "requested_at",
            "question",
            "scope",
            "status",
            "rule_version",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"analysis proposal contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"analysis proposal is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("analysis proposal schema_version must be 1")
        proposal_id = _require_string(data.get("proposal_id"), "proposal_id")
        if not PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
            raise ValueError("proposal_id must be proposal- followed by 24 lowercase hex characters")
        fingerprint = _require_string(data.get("fingerprint"), "fingerprint")
        if not PROPOSAL_FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("proposal fingerprint must be a lowercase SHA-256 hex digest")
        project_id = _require_string(data.get("project_id"), "project_id")
        if not ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id must be a lowercase slug")
        provider = _require_string(data.get("provider"), "provider")
        repository_id = data.get("repository_id")
        if isinstance(repository_id, bool) or not isinstance(repository_id, int) or repository_id <= 0:
            raise ValueError("repository_id must be a positive integer")
        trigger_event_id = _require_string(data.get("trigger_event_id"), "trigger_event_id")
        if not CHANGE_EVENT_ID_PATTERN.fullmatch(trigger_event_id):
            raise ValueError("trigger_event_id must be a change event ID")
        trigger_fingerprint = _require_string(data.get("trigger_fingerprint"), "trigger_fingerprint")
        if not PROPOSAL_FINGERPRINT_PATTERN.fullmatch(trigger_fingerprint):
            raise ValueError("trigger_fingerprint must be a lowercase SHA-256 hex digest")
        requested_at = _timestamp(data.get("requested_at"), "requested_at")
        question = _require_string(data.get("question"), "question")
        scope = data.get("scope")
        if not isinstance(scope, list) or not scope or any(
            not isinstance(item, str) or not item.strip() for item in scope
        ):
            raise ValueError("scope must be a non-empty array of strings")
        if len(scope) != len(set(scope)):
            raise ValueError("scope must not contain duplicates")
        status = _require_string(data.get("status"), "status")
        if status not in PROPOSAL_STATUSES:
            raise ValueError("analysis proposal status is not supported")
        rule_version = _require_string(data.get("rule_version"), "rule_version")
        if rule_version != PROPOSAL_RULE_VERSION:
            raise ValueError(f"unsupported proposal rule version: {rule_version}")
        proposal = cls(
            schema_version=1,
            proposal_id=proposal_id,
            fingerprint=fingerprint,
            project_id=project_id,
            provider=provider,
            repository_id=repository_id,
            trigger_event_id=trigger_event_id,
            trigger_fingerprint=trigger_fingerprint,
            requested_at=requested_at,
            question=question,
            scope=tuple(scope),
            status=status,
            rule_version=rule_version,
        )
        expected_fingerprint = _proposal_fingerprint(proposal)
        if proposal.fingerprint != expected_fingerprint:
            raise ValueError("analysis proposal fingerprint does not match its trigger")
        if proposal.proposal_id != f"proposal-{proposal.fingerprint[:24]}":
            raise ValueError("proposal_id does not match fingerprint")
        return proposal

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "fingerprint": self.fingerprint,
            "project_id": self.project_id,
            "provider": self.provider,
            "repository_id": self.repository_id,
            "trigger_event_id": self.trigger_event_id,
            "trigger_fingerprint": self.trigger_fingerprint,
            "requested_at": iso_utc(self.requested_at),
            "question": self.question,
            "scope": list(self.scope),
            "status": self.status,
            "rule_version": self.rule_version,
        }


def _proposal_fingerprint(proposal: AnalysisProposal) -> str:
    payload = {
        "project_id": proposal.project_id,
        "provider": proposal.provider,
        "repository_id": proposal.repository_id,
        "trigger_event_id": proposal.trigger_event_id,
        "trigger_fingerprint": proposal.trigger_fingerprint,
        "question": proposal.question,
        "scope": list(proposal.scope),
        "rule_version": proposal.rule_version,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


_QUESTIONS = {
    "facts.archived": "Assess the repository archive-state change and its implications for maintenance.",
    "facts.license_spdx": "Verify the license change and assess its compatibility and risk.",
    "facts.language": "Review the language change and determine whether the repository architecture shifted.",
    "facts.topics": "Review the topic change against the repository's actual technical scope.",
    "metrics.stars": "Assess the significant star-count change and whether it signals adoption or attention.",
    "metrics.forks": "Assess the significant fork-count change and whether it signals engineering reuse.",
}


def build_analysis_proposals(events: Iterable[ChangeEvent]) -> list[AnalysisProposal]:
    """Build stable review proposals for actionable deterministic changes."""
    proposals: list[AnalysisProposal] = []
    seen: set[str] = set()
    for candidate in events:
        if not isinstance(candidate, ChangeEvent):
            raise ValueError("analysis proposal trigger must be a ChangeEvent")
        event = ChangeEvent.from_dict(candidate.to_dict())
        if event.severity not in {"high", "medium"}:
            continue
        question = _QUESTIONS.get(event.field)
        if question is None:
            continue
        scope = ("repository-metadata", event.field.split(".", 1)[0])
        proposal = AnalysisProposal(
            schema_version=1,
            proposal_id="proposal-" + ("0" * 24),
            fingerprint="0" * 64,
            project_id=event.project_id,
            provider=event.provider,
            repository_id=event.repository_id,
            trigger_event_id=event.change_id,
            trigger_fingerprint=event.fingerprint,
            requested_at=event.detected_at,
            question=question,
            scope=scope,
            status="pending",
            rule_version=PROPOSAL_RULE_VERSION,
        )
        fingerprint = _proposal_fingerprint(proposal)
        finalized = replace(
            proposal,
            proposal_id=f"proposal-{fingerprint[:24]}",
            fingerprint=fingerprint,
        )
        if finalized.proposal_id in seen:
            continue
        seen.add(finalized.proposal_id)
        proposals.append(finalized)
    return sorted(proposals, key=lambda item: item.proposal_id)


@dataclass(frozen=True)
class ResearchEvidence:
    """A source-bound human or model research statement."""

    schema_version: int
    evidence_id: str
    project_id: str
    kind: str
    claim: str
    reason: str
    source_type: str
    source_ref: str
    input_version: str
    generated_at: datetime
    confidence: float
    dimension: str | None = None
    rating: float | None = None
    context_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResearchEvidence":
        if not isinstance(data, Mapping):
            raise ValueError("research evidence must be an object")
        expected = {
            "schema_version", "evidence_id", "project_id", "kind", "claim",
            "reason", "source_type", "source_ref", "input_version", "generated_at", "confidence",
            "dimension", "rating", "context_id", "model", "prompt_version",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"research evidence contains unknown fields: {', '.join(unknown)}")
        required = {
            "schema_version", "evidence_id", "project_id", "kind", "claim",
            "reason", "source_type", "source_ref", "input_version", "generated_at", "confidence",
        }
        missing = sorted(required - set(data))
        if missing:
            raise ValueError(f"research evidence is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("research evidence schema_version must be 1")
        evidence_id = _require_string(data.get("evidence_id"), "evidence_id")
        if not EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
            raise ValueError("evidence_id must start with evidence- and use lowercase identifiers")
        project_id = _require_string(data.get("project_id"), "project_id")
        if not ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id must be a lowercase slug")
        kind = _require_string(data.get("kind"), "kind")
        if kind not in EVIDENCE_KINDS:
            raise ValueError("research evidence kind is not supported")
        claim = _require_string(data.get("claim"), "claim")
        reason = _require_string(data.get("reason"), "reason")
        source_type = _require_string(data.get("source_type"), "source_type")
        if source_type not in SOURCE_TYPES:
            raise ValueError("research evidence source_type is not supported")
        source_ref = _require_string(data.get("source_ref"), "source_ref")
        if source_type == "url" and not source_ref.startswith("https://"):
            raise ValueError("url evidence source_ref must use https")
        if source_type == "commit" and re.fullmatch(r"[0-9a-f]{7,64}", source_ref) is None:
            raise ValueError("commit evidence source_ref must be a hexadecimal commit SHA")
        input_version = _require_string(data.get("input_version"), "input_version")
        generated_at = _timestamp(data.get("generated_at"), "generated_at")
        confidence = data.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be a number between 0 and 1")
        dimension = data.get("dimension")
        if dimension is not None:
            dimension = _require_string(dimension, "dimension")
            if dimension not in DIMENSIONS:
                raise ValueError("research evidence dimension is not supported")
        rating = data.get("rating")
        if rating is not None:
            if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 0 <= rating <= 10:
                raise ValueError("rating must be a number between 0 and 10")
            if dimension is None:
                raise ValueError("rating requires a dimension")
        context_id = data.get("context_id")
        if context_id is not None:
            context_id = _require_string(context_id, "context_id")
        if dimension == "relevance" and context_id is None:
            raise ValueError("relevance evidence requires a context_id")
        optional: dict[str, str | None] = {}
        for name in ("model", "prompt_version"):
            value = data.get(name)
            if value is not None:
                optional[name] = _require_string(value, name)
            else:
                optional[name] = None
        return cls(
            schema_version=1,
            evidence_id=evidence_id,
            project_id=project_id,
            kind=kind,
            claim=claim,
            reason=reason,
            source_type=source_type,
            source_ref=source_ref,
            input_version=input_version,
            generated_at=generated_at,
            confidence=float(confidence),
            dimension=dimension,
            rating=float(rating) if rating is not None else None,
            context_id=context_id,
            model=optional["model"],
            prompt_version=optional["prompt_version"],
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "project_id": self.project_id,
            "kind": self.kind,
            "claim": self.claim,
            "reason": self.reason,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "input_version": self.input_version,
            "generated_at": iso_utc(self.generated_at),
            "confidence": self.confidence,
        }
        for name in ("dimension", "rating", "context_id", "model", "prompt_version"):
            value_to_add = getattr(self, name)
            if value_to_add is not None:
                value[name] = value_to_add
        return value


class DuplicateEvidenceError(ValueError):
    """Raised when a research evidence ID is reused with different content."""


class ResearchEvidenceStore:
    """Append-only human research evidence under research/evidence.jsonl."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "research"
        self.path = self.directory / "evidence.jsonl"
        self.lock_path = self.directory / ".evidence.lock"

    @contextmanager
    def _locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def all(self) -> list[ResearchEvidence]:
        if not self.path.exists():
            return []
        evidence: list[ResearchEvidence] = []
        seen: set[str] = set()
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = ResearchEvidence.from_dict(json.loads(line))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{self.path}:{line_number}: invalid research evidence") from exc
            if item.evidence_id in seen:
                raise DuplicateEvidenceError(f"evidence_id already exists: {item.evidence_id}")
            seen.add(item.evidence_id)
            evidence.append(item)
        return evidence

    def append(self, evidence: ResearchEvidence) -> bool:
        if not isinstance(evidence, ResearchEvidence):
            raise ValueError("research evidence must be a ResearchEvidence")
        if evidence.source_type == "observation":
            # Observation references are internal evidence edges and can be
            # checked without trusting the caller. Other source types may
            # point at an external URL, SHA, or opaque snapshot identifier.
            from .storage import ObservationStore

            observation_ids = {record.event_id for record in ObservationStore(self.root).all()}
            if evidence.source_ref not in observation_ids:
                raise ValueError(f"research evidence references unknown observation: {evidence.source_ref}")
        with self._locked():
            existing = {item.evidence_id: item for item in self.all()}
            previous = existing.get(evidence.evidence_id)
            if previous is not None:
                if previous.to_dict() == evidence.to_dict():
                    return False
                raise DuplicateEvidenceError(f"evidence_id already exists: {evidence.evidence_id}")
            self.directory.mkdir(parents=True, exist_ok=True)
            original = self.path.read_bytes() if self.path.exists() else b""
            handle = tempfile.NamedTemporaryFile(
                mode="wb", prefix=".evidence.", suffix=".tmp", dir=self.directory, delete=False
            )
            temporary = Path(handle.name)
            try:
                handle.write(original)
                handle.write(
                    (json.dumps(evidence.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                )
                handle.close()
                temporary.replace(self.path)
            except Exception:
                handle.close()
                temporary.unlink(missing_ok=True)
                raise
            return True
