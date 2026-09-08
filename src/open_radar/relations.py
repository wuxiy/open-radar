"""Human-maintained, evidence-bound relationships between projects and contexts."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Iterable, Iterator, Mapping

import yaml

from .domain import ID_PATTERN


ENDPOINT_KINDS = {"project", "context"}
DIRECTIONS = {"directed", "symmetric"}
EVIDENCE_ID_PREFIX = "evidence-"


class DuplicateRelationError(ValueError):
    """Raised when relation identity or semantic edge identity collides."""


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


@dataclass(frozen=True, order=True)
class RelationEndpoint:
    """A typed endpoint that cannot confuse a project ID with a context ID."""

    kind: str
    id: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str) -> "RelationEndpoint":
        if not isinstance(data, Mapping):
            raise ValueError(f"{path} must be an object")
        expected = {"kind", "id"}
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"{path} contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"{path} is missing fields: {', '.join(missing)}")
        kind = _require_string(data.get("kind"), f"{path}.kind")
        if kind not in ENDPOINT_KINDS:
            raise ValueError(f"{path}.kind is not supported")
        identifier = _require_string(data.get("id"), f"{path}.id")
        if not ID_PATTERN.fullmatch(identifier):
            raise ValueError(f"{path}.id must be a lowercase slug")
        return cls(kind=kind, id=identifier)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}


@dataclass(frozen=True)
class Relation:
    """One canonical relation edge, retained independently of project YAML."""

    schema_version: int
    relation_id: str
    source: RelationEndpoint
    target: RelationEndpoint
    relation_type: str
    direction: str
    reason: str
    evidence_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Relation":
        if not isinstance(data, Mapping):
            raise ValueError("relation must be an object")
        expected = {
            "schema_version",
            "relation_id",
            "source",
            "target",
            "relation_type",
            "direction",
            "reason",
            "evidence_ids",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"relation contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"relation is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("relation schema_version must be 1")
        relation_id = _require_string(data.get("relation_id"), "relation_id")
        if not ID_PATTERN.fullmatch(relation_id):
            raise ValueError("relation_id must be a lowercase slug")
        source = RelationEndpoint.from_dict(data.get("source"), path="relation.source")
        target = RelationEndpoint.from_dict(data.get("target"), path="relation.target")
        if source == target:
            raise ValueError("relation source and target must differ")
        relation_type = _require_string(data.get("relation_type"), "relation_type")
        if not ID_PATTERN.fullmatch(relation_type):
            raise ValueError("relation_type must be a lowercase slug")
        direction = _require_string(data.get("direction"), "direction")
        if direction not in DIRECTIONS:
            raise ValueError("relation direction is not supported")
        if direction == "symmetric" and source >= target:
            raise ValueError("symmetric relation endpoints must use canonical source/target ordering")
        reason = _require_string(data.get("reason"), "reason")
        raw_evidence_ids = data.get("evidence_ids")
        if not isinstance(raw_evidence_ids, list) or not raw_evidence_ids:
            raise ValueError("evidence_ids must be a non-empty array")
        evidence_ids = tuple(
            _require_string(item, f"evidence_ids[{index}]")
            for index, item in enumerate(raw_evidence_ids)
        )
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_ids must not contain duplicates")
        if any(
            not item.startswith(EVIDENCE_ID_PREFIX)
            or not ID_PATTERN.fullmatch(item[len(EVIDENCE_ID_PREFIX):])
            for item in evidence_ids
        ):
            raise ValueError("evidence_ids must contain evidence IDs")
        return cls(
            schema_version=1,
            relation_id=relation_id,
            source=source,
            target=target,
            relation_type=relation_type,
            direction=direction,
            reason=reason,
            evidence_ids=evidence_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "relation_id": self.relation_id,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "relation_type": self.relation_type,
            "direction": self.direction,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
        }

    @property
    def semantic_key(self) -> tuple[object, ...]:
        return (
            self.source,
            self.target,
            self.relation_type,
            self.direction,
        )

    def view_for_endpoint(self, endpoint: RelationEndpoint) -> dict[str, object]:
        """Return a query-oriented view without changing canonical edge storage."""
        if endpoint == self.source:
            other = self.target
        elif endpoint == self.target:
            other = self.source
        else:
            raise ValueError("endpoint is not part of this relation")
        return {
            **self.to_dict(),
            "query_endpoint": endpoint.to_dict(),
            "other_endpoint": other.to_dict(),
        }


class RelationStore:
    """Atomic relation YAML storage with canonical file and edge identities."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "relations"
        self.lock_path = self.directory / ".write.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def _load_path(self, path: Path, *, expected_id: str) -> Relation:
        try:
            relation = Relation.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise ValueError(f"{path}: invalid relation YAML") from exc
        if relation.relation_id != expected_id:
            raise ValueError(
                f"{path}: relation id {relation.relation_id!r} does not match filename {expected_id!r}"
            )
        return relation

    def all(self) -> list[Relation]:
        if not self.directory.exists():
            return []
        relations: list[Relation] = []
        seen_semantic_keys: dict[tuple[object, ...], str] = {}
        for path in sorted(self.directory.glob("*.yaml")):
            relation = self._load_path(path, expected_id=path.stem)
            previous = seen_semantic_keys.get(relation.semantic_key)
            if previous is not None:
                raise DuplicateRelationError(
                    f"duplicate relation edge: {previous} and {relation.relation_id}"
                )
            seen_semantic_keys[relation.semantic_key] = relation.relation_id
            relations.append(relation)
        return relations

    def load(self, relation_id: str) -> Relation:
        if not isinstance(relation_id, str) or not ID_PATTERN.fullmatch(relation_id):
            raise ValueError("relation_id must be a lowercase slug")
        path = self.directory / f"{relation_id}.yaml"
        if not path.is_file():
            raise FileNotFoundError(path)
        return self._load_path(path, expected_id=relation_id)

    def save(self, relation: Relation) -> Path:
        if not isinstance(relation, Relation):
            raise ValueError("relation must be a Relation")
        with self.locked():
            from .taxonomy import RelationTypeCatalog

            RelationTypeCatalog.load(self.root).validate(
                relation.relation_type, relation.direction
            )
            destination = self.directory / f"{relation.relation_id}.yaml"
            if destination.exists():
                existing = self._load_path(destination, expected_id=relation.relation_id)
                if existing.to_dict() == relation.to_dict():
                    return destination
                raise DuplicateRelationError(f"relation_id already exists: {relation.relation_id}")
            for existing in self.all():
                if existing.semantic_key == relation.semantic_key:
                    raise DuplicateRelationError(
                        f"relation edge already exists: {existing.relation_id}"
                    )
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                prefix=f".{relation.relation_id}.",
                suffix=".tmp",
                dir=self.directory,
                encoding="utf-8",
                delete=False,
            )
            temporary = Path(handle.name)
            try:
                yaml.safe_dump(relation.to_dict(), handle, allow_unicode=True, sort_keys=False)
                handle.close()
                temporary.replace(destination)
            except Exception:
                handle.close()
                temporary.unlink(missing_ok=True)
                raise
            return destination

    def for_endpoint(self, endpoint: RelationEndpoint) -> list[Relation]:
        if not isinstance(endpoint, RelationEndpoint):
            raise ValueError("endpoint must be a RelationEndpoint")
        return [
            relation
            for relation in self.all()
            if relation.source == endpoint or relation.target == endpoint
        ]


def validate_relation_references(
    relations: Iterable[Relation],
    *,
    project_ids: set[str],
    context_ids: set[str],
    relation_type_directions: Mapping[str, frozenset[str]],
    evidence_bindings: Mapping[str, tuple[str, str | None]],
) -> list[str]:
    """Return stable cross-file integrity errors for relation records."""
    errors: list[str] = []
    for relation in relations:
        directions = relation_type_directions.get(relation.relation_type)
        if directions is None:
            errors.append(f"unknown relation type: {relation.relation_type}")
        elif relation.direction not in directions:
            errors.append(
                f"relation type {relation.relation_type} does not support direction: {relation.direction}"
            )
        for label, endpoint in (("source", relation.source), ("target", relation.target)):
            known_ids = project_ids if endpoint.kind == "project" else context_ids
            if endpoint.id not in known_ids:
                errors.append(
                    f"{label} references unknown {endpoint.kind}: {endpoint.id}"
                )
        evidence = []
        for evidence_id in relation.evidence_ids:
            binding = evidence_bindings.get(evidence_id)
            if binding is None:
                errors.append(f"references unknown evidence: {evidence_id}")
            else:
                evidence.append(binding)
        for endpoint in (relation.source, relation.target):
            if endpoint.kind == "project" and not any(
                project_id == endpoint.id for project_id, _ in evidence
            ):
                errors.append(
                    f"evidence does not support project endpoint: {endpoint.id}"
                )
            if endpoint.kind == "context" and not any(
                context_id == endpoint.id for _, context_id in evidence
            ):
                errors.append(
                    f"evidence does not support context endpoint: {endpoint.id}"
                )
    return errors
