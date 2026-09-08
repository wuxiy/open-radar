"""Deterministic score cards and private research contexts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

import yaml

from .domain import ID_PATTERN, ensure_utc, iso_utc
from .research import DIMENSIONS, ResearchEvidence


SCORE_VERSION = "radar-score/1"
SCORE_DIMENSIONS = ("innovation", "engineering", "relevance", "activity", "learning_value")
SCORE_WEIGHTS = {
    "innovation": 0.25,
    "engineering": 0.20,
    "relevance": 0.25,
    "activity": 0.15,
    "learning_value": 0.15,
}


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


def _strings(value: Any, path: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    result = tuple(_require_string(item, f"{path}[{index}]") for index, item in enumerate(value))
    if nonempty and not result:
        raise ValueError(f"{path} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{path} must not contain duplicates")
    return result


@dataclass(frozen=True)
class Context:
    """A private, human-maintained scoring context."""

    schema_version: int
    context_id: str
    name: str
    goal: str
    technical_questions: tuple[str, ...]
    priority: int
    active: bool = True
    project_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Context":
        if not isinstance(data, Mapping):
            raise ValueError("context must be an object")
        expected = {
            "schema_version", "context_id", "name", "goal", "technical_questions",
            "priority", "active", "project_ids",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"context contains unknown fields: {', '.join(unknown)}")
        required = {"schema_version", "context_id", "name", "goal", "technical_questions", "priority"}
        missing = sorted(required - set(data))
        if missing:
            raise ValueError(f"context is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("context schema_version must be 1")
        context_id = _require_string(data.get("context_id"), "context_id")
        if not ID_PATTERN.fullmatch(context_id):
            raise ValueError("context_id must be a lowercase slug")
        name = _require_string(data.get("name"), "name")
        goal = _require_string(data.get("goal"), "goal")
        technical_questions = _strings(data.get("technical_questions"), "technical_questions", nonempty=True)
        priority = data.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
            raise ValueError("priority must be an integer between 1 and 5")
        active = data.get("active", True)
        if not isinstance(active, bool):
            raise ValueError("active must be a boolean")
        project_ids = _strings(data.get("project_ids", []), "project_ids")
        if any(not ID_PATTERN.fullmatch(project_id) for project_id in project_ids):
            raise ValueError("project_ids must contain lowercase slugs")
        return cls(
            schema_version=1,
            context_id=context_id,
            name=name,
            goal=goal,
            technical_questions=technical_questions,
            priority=priority,
            active=active,
            project_ids=project_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "name": self.name,
            "goal": self.goal,
            "technical_questions": list(self.technical_questions),
            "priority": self.priority,
            "active": self.active,
            "project_ids": list(self.project_ids),
        }


class ContextStore:
    """Read and write private contexts without touching project facts."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "contexts"

    def all(self) -> list[Context]:
        if not self.directory.exists():
            return []
        contexts: list[Context] = []
        for path in sorted(self.directory.glob("*.yaml")):
            contexts.append(self._load_path(path, expected_id=path.stem))
        return contexts

    def load(self, context_id: str) -> Context:
        if not ID_PATTERN.fullmatch(context_id):
            raise ValueError("context_id must be a lowercase slug")
        path = self.directory / f"{context_id}.yaml"
        if not path.is_file():
            raise FileNotFoundError(path)
        return self._load_path(path, expected_id=context_id)

    def _load_path(self, path: Path, *, expected_id: str) -> Context:
        try:
            context = Context.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}: invalid context YAML") from exc
        if context.context_id != expected_id:
            raise ValueError(
                f"{path}: context id {context.context_id!r} does not match filename {expected_id!r}"
            )
        return context

    def save(self, context: Context) -> Path:
        if not isinstance(context, Context):
            raise ValueError("context must be a Context")
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{context.context_id}.yaml"
        handle = tempfile.NamedTemporaryFile(
            mode="w", prefix=f".{context.context_id}.", suffix=".tmp", dir=self.directory,
            encoding="utf-8", delete=False,
        )
        temporary = Path(handle.name)
        try:
            yaml.safe_dump(context.to_dict(), handle, allow_unicode=True, sort_keys=False)
            handle.close()
            temporary.replace(destination)
        except Exception:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
        return destination


@dataclass(frozen=True)
class ScoreDimension:
    dimension: str
    rating: float
    reason: str
    evidence_ids: tuple[str, ...]
    confidence: float
    input_version: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoreDimension":
        if not isinstance(data, Mapping):
            raise ValueError("score dimension must be an object")
        expected = {"dimension", "rating", "reason", "evidence_ids", "confidence", "input_version"}
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"score dimension contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"score dimension is missing fields: {', '.join(missing)}")
        dimension = _require_string(data.get("dimension"), "dimension")
        if dimension not in SCORE_DIMENSIONS:
            raise ValueError("score dimension is not supported")
        rating = data.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 0 <= rating <= 10:
            raise ValueError("rating must be a number between 0 and 10")
        reason = _require_string(data.get("reason"), "reason")
        evidence_ids = _strings(data.get("evidence_ids"), "evidence_ids", nonempty=True)
        confidence = data.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be a number between 0 and 1")
        input_version = _require_string(data.get("input_version"), "input_version")
        return cls(dimension, float(rating), reason, evidence_ids, float(confidence), input_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "rating": self.rating,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "input_version": self.input_version,
        }


@dataclass(frozen=True)
class ScoreCard:
    """A derived score; it never mutates the corresponding Project."""

    schema_version: int
    project_id: str
    context_id: str | None
    score_version: str
    input_version: str
    evaluated_at: datetime
    dimensions: Mapping[str, ScoreDimension]
    total_score: float | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoreCard":
        if not isinstance(data, Mapping):
            raise ValueError("score card must be an object")
        expected = {
            "schema_version", "project_id", "context_id", "score_version", "input_version",
            "evaluated_at", "dimensions", "total_score",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"score card contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"score card is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("score card schema_version must be 1")
        project_id = _require_string(data.get("project_id"), "project_id")
        if not ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id must be a lowercase slug")
        context_id = data.get("context_id")
        if context_id is not None:
            context_id = _require_string(context_id, "context_id")
            if not ID_PATTERN.fullmatch(context_id):
                raise ValueError("context_id must be a lowercase slug")
        score_version = _require_string(data.get("score_version"), "score_version")
        if score_version != SCORE_VERSION:
            raise ValueError(f"unsupported score version: {score_version}")
        input_version = _require_string(data.get("input_version"), "input_version")
        evaluated_at = _timestamp(data.get("evaluated_at"), "evaluated_at")
        raw_dimensions = data.get("dimensions")
        if not isinstance(raw_dimensions, Mapping):
            raise ValueError("dimensions must be an object")
        dimensions: dict[str, ScoreDimension] = {}
        for name, raw in raw_dimensions.items():
            if not isinstance(name, str) or name not in SCORE_DIMENSIONS:
                raise ValueError("dimensions contains an unsupported key")
            dimension = ScoreDimension.from_dict(raw)
            if dimension.dimension != name:
                raise ValueError("score dimension key does not match its value")
            dimensions[name] = dimension
        total_score = data.get("total_score")
        if total_score is not None:
            if isinstance(total_score, bool) or not isinstance(total_score, (int, float)) or not 0 <= total_score <= 100:
                raise ValueError("total_score must be a number between 0 and 100")
            if set(dimensions) != set(SCORE_DIMENSIONS):
                raise ValueError("total_score requires every score dimension")
            expected_total = _total(dimensions)
            if float(total_score) != expected_total:
                raise ValueError("total_score does not match score dimensions")
            total_score = float(total_score)
        elif set(dimensions) == set(SCORE_DIMENSIONS):
            raise ValueError("complete score dimensions require total_score")
        return cls(1, project_id, context_id, score_version, input_version, evaluated_at, dimensions, total_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "context_id": self.context_id,
            "score_version": self.score_version,
            "input_version": self.input_version,
            "evaluated_at": iso_utc(self.evaluated_at),
            "dimensions": {name: self.dimensions[name].to_dict() for name in sorted(self.dimensions)},
            "total_score": self.total_score,
        }


def _total(dimensions: Mapping[str, ScoreDimension]) -> float:
    return round(10 * sum(dimensions[name].rating * SCORE_WEIGHTS[name] for name in SCORE_DIMENSIONS), 2)


class ScoreEngine:
    """Select the latest source-bound rating for each dimension deterministically."""

    def __init__(self, *, score_version: str = SCORE_VERSION) -> None:
        if score_version != SCORE_VERSION:
            raise ValueError(f"unsupported score version: {score_version}")
        self.score_version = score_version

    def score(
        self,
        project_id: str,
        evidence: Iterable[ResearchEvidence],
        *,
        context: Context | None = None,
        evaluated_at: datetime | None = None,
        input_version: str | None = None,
    ) -> ScoreCard:
        if not isinstance(project_id, str) or not ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id must be a lowercase slug")
        if context is not None and not isinstance(context, Context):
            raise ValueError("context must be a Context")
        records = []
        for item in evidence:
            if not isinstance(item, ResearchEvidence):
                raise ValueError("score evidence must be ResearchEvidence records")
            if item.project_id == project_id and item.rating is not None and item.dimension is not None:
                records.append(item)
        if evaluated_at is None:
            evaluated_at = max((item.generated_at for item in records), default=datetime(1970, 1, 1, tzinfo=timezone.utc))
        evaluated_at = ensure_utc(evaluated_at)
        selected: dict[str, ResearchEvidence] = {}
        for item in records:
            if item.generated_at > evaluated_at:
                continue
            assert item.dimension is not None
            if item.dimension == "relevance":
                if context is None or not context.active or item.context_id != context.context_id:
                    continue
                if context.project_ids and project_id not in context.project_ids:
                    continue
            previous = selected.get(item.dimension)
            if previous is None or (item.generated_at, item.evidence_id) > (previous.generated_at, previous.evidence_id):
                selected[item.dimension] = item
        dimensions = {
            name: ScoreDimension(
                dimension=name,
                rating=float(selected[name].rating),
                reason=selected[name].reason,
                evidence_ids=(selected[name].evidence_id,),
                confidence=selected[name].confidence,
                input_version=selected[name].input_version,
            )
            for name in SCORE_DIMENSIONS
            if name in selected
        }
        resolved_input_version = input_version or _input_version(
            item for item in records if item.generated_at <= evaluated_at
        )
        if not isinstance(resolved_input_version, str) or not resolved_input_version.strip():
            raise ValueError("input_version must be a non-empty string")
        total_score = _total(dimensions) if set(dimensions) == set(SCORE_DIMENSIONS) else None
        return ScoreCard(
            schema_version=1,
            project_id=project_id,
            context_id=context.context_id if context else None,
            score_version=self.score_version,
            input_version=resolved_input_version,
            evaluated_at=evaluated_at,
            dimensions=dimensions,
            total_score=total_score,
        )


def _input_version(records: Iterable[ResearchEvidence]) -> str:
    versions = sorted({item.input_version for item in records})
    if not versions:
        return "inputs:none"
    if len(versions) == 1:
        return versions[0]
    encoded = json.dumps(versions, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "inputs:" + hashlib.sha256(encoded).hexdigest()[:16]
