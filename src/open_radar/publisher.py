"""Observation-only publisher boundary with strict path and content checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Literal, Protocol

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from .contracts.schema import SchemaValidator
from .domain import ObservationRecord, ValidationError
from .generation import render_readme
from .storage import ObservationStore, ProjectStore


ArtifactKind = Literal["observation", "run", "readme"]
_MONTH_FILE = re.compile(r"^(?:19|20)[0-9]{2}-(0[1-9]|1[0-2])\.jsonl$")


class PublisherIsolationError(PermissionError):
    """Raised when a machine-data artifact crosses its allowed boundary."""


@dataclass(frozen=True)
class PublisherArtifact:
    path: str
    content: str
    kind: ArtifactKind
    sha256: str | None = None


@dataclass(frozen=True)
class PublisherPlan:
    files: tuple[PublisherArtifact, ...]
    commit_message: str = "update observation data"

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)


class PublisherSink(Protocol):
    def open_or_update(self, plan: PublisherPlan) -> object: ...


class ObservationOnlyPublisher:
    """Build a bounded PR plan; no external code, text, or commands are executed."""

    def __init__(self, root: Path | None = None, *, max_file_bytes: int = 2_000_000) -> None:
        self.root = Path(root).resolve() if root is not None else None
        if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.max_file_bytes = max_file_bytes

    def plan(
        self,
        artifacts: list[PublisherArtifact] | tuple[PublisherArtifact, ...],
        *,
        commit_message: str = "update observation data",
    ) -> PublisherPlan:
        if not isinstance(commit_message, str) or not commit_message.strip() or len(commit_message) > 200:
            raise PublisherIsolationError("publisher commit message is invalid")
        normalized: list[PublisherArtifact] = []
        seen: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, PublisherArtifact):
                raise PublisherIsolationError("publisher accepts only PublisherArtifact values")
            path = self._validate_path(artifact.path, artifact.kind)
            if path in seen:
                raise PublisherIsolationError(f"publisher plan repeats path: {path}")
            seen.add(path)
            digest = self._validate_content(artifact)
            normalized.append(PublisherArtifact(path, artifact.content, artifact.kind, digest))
        if not normalized:
            raise PublisherIsolationError("publisher plan cannot be empty")
        return PublisherPlan(
            files=tuple(sorted(normalized, key=lambda item: item.path)),
            commit_message=commit_message.strip(),
        )

    def publish(
        self,
        artifacts: list[PublisherArtifact] | tuple[PublisherArtifact, ...],
        *,
        sink: PublisherSink | None = None,
        commit_message: str = "update observation data",
    ) -> PublisherPlan:
        plan = self.plan(artifacts, commit_message=commit_message)
        if sink is not None:
            sink.open_or_update(plan)
        return plan

    def _validate_path(self, value: str, kind: ArtifactKind) -> str:
        if not isinstance(value, str) or not value or len(value) > 256:
            raise PublisherIsolationError("publisher path must be a short non-empty string")
        if "\\" in value or "\x00" in value or value.startswith("/"):
            raise PublisherIsolationError("publisher path must be a relative POSIX path")
        path = PurePosixPath(value)
        if str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
            raise PublisherIsolationError("publisher path is not normalized")
        if kind == "observation":
            if len(path.parts) != 4 or path.parts[:3] != ("data", "observations", "github"):
                raise PublisherIsolationError("observation publisher can only write github monthly logs")
            if _MONTH_FILE.fullmatch(path.name) is None:
                raise PublisherIsolationError("observation publisher requires a YYYY-MM.jsonl file")
        elif kind == "run":
            if len(path.parts) != 3 or path.parts[:2] != ("data", "runs") or _MONTH_FILE.fullmatch(path.name) is None:
                raise PublisherIsolationError("run publisher can only write monthly compact manifests")
        elif kind == "readme":
            if value != "README.md":
                raise PublisherIsolationError("readme publisher can only write README.md")
        else:
            raise PublisherIsolationError("unsupported publisher artifact kind")
        if self.root is not None:
            resolved = (self.root / Path(*path.parts)).resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise PublisherIsolationError("publisher path escapes repository root") from exc
            destination = self.root.joinpath(*path.parts)
            if destination.is_symlink():
                raise PublisherIsolationError("publisher refuses to write through symlinks")
        return value

    def _validate_content(self, artifact: PublisherArtifact) -> str:
        if not isinstance(artifact.content, str) or "\x00" in artifact.content:
            raise PublisherIsolationError("publisher content must be UTF-8 text without NUL bytes")
        encoded = artifact.content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise PublisherIsolationError("publisher artifact exceeds size limit")
        digest = hashlib.sha256(encoded).hexdigest()
        if artifact.sha256 is not None and artifact.sha256 != digest:
            raise PublisherIsolationError("publisher artifact sha256 does not match content")
        if artifact.kind in {"observation", "run"}:
            seen_events: set[str] = set()
            seen_slots: set[str] = set()
            seen_superseded: set[str] = set()
            existing_events: set[str] = set()
            if artifact.kind == "observation" and self.root is not None:
                try:
                    existing_events = {record.event_id for record in ObservationStore(self.root).all()}
                except (ValidationError, ValueError) as exc:
                    raise PublisherIsolationError("existing observation log is invalid") from exc
            for line_number, line in enumerate(artifact.content.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PublisherIsolationError(
                        f"publisher JSONL is invalid at line {line_number}"
                    ) from exc
                if not isinstance(value, dict):
                    raise PublisherIsolationError("publisher JSONL records must be objects")
                if artifact.kind == "observation":
                    try:
                        record = ObservationRecord.from_dict(value)
                    except (ValidationError, ValueError, TypeError) as exc:
                        raise PublisherIsolationError(
                            f"publisher observation is invalid at line {line_number}"
                        ) from exc
                    if record.event_id in seen_events:
                        raise PublisherIsolationError("publisher observation repeats event_id")
                    seen_events.add(record.event_id)
                    if record.record_type == "observation":
                        if record.collection_key in seen_slots:
                            raise PublisherIsolationError("publisher observation repeats collection_key")
                        seen_slots.add(record.collection_key)
                    elif record.supersedes is not None:
                        if record.supersedes == record.event_id:
                            raise PublisherIsolationError("publisher correction cannot supersede itself")
                        if record.supersedes in seen_superseded:
                            raise PublisherIsolationError("publisher correction branches are ambiguous")
                        if record.supersedes not in existing_events and record.supersedes not in seen_events:
                            raise PublisherIsolationError("publisher correction target is not present")
                        seen_superseded.add(record.supersedes)
                else:
                    try:
                        schema_path = self.root / "schemas" / "run-manifest.v1.json" if self.root else None
                        if schema_path is not None and schema_path.is_file():
                            SchemaValidator(self.root).validate("run-manifest.v1.json", value)
                        else:
                            required = {"schema_version", "run_id", "kind", "started_at", "finished_at", "status", "counts"}
                            allowed = required | {"errors", "metadata"}
                            if (
                                not required.issubset(value)
                                or set(value) - allowed
                                or value.get("schema_version") != 1
                                or not isinstance(value.get("run_id"), str)
                                or not isinstance(value.get("started_at"), str)
                                or not isinstance(value.get("finished_at"), str)
                                or not value["started_at"].endswith("Z")
                                or not value["finished_at"].endswith("Z")
                            ):
                                raise ValueError("required fields are missing")
                            if value.get("kind") not in {"ingest", "collect", "generate", "validate"}:
                                raise ValueError("kind is invalid")
                            if value.get("status") not in {"started", "succeeded", "partial", "pending", "failed"}:
                                raise ValueError("status is invalid")
                            counts = value.get("counts")
                            if not isinstance(counts, dict) or any(
                                isinstance(item, bool) or not isinstance(item, int) or item < 0
                                for item in counts.values()
                            ):
                                raise ValueError("counts are invalid")
                            if "errors" in value and (
                                not isinstance(value["errors"], list)
                                or any(not isinstance(item, str) for item in value["errors"])
                            ):
                                raise ValueError("errors are invalid")
                            if "metadata" in value and not isinstance(value["metadata"], dict):
                                raise ValueError("metadata is invalid")
                    except (ValueError, FileNotFoundError, JsonSchemaValidationError) as exc:
                        raise PublisherIsolationError(
                            f"publisher run manifest is invalid at line {line_number}"
                        ) from exc
        elif self.root is None:
            raise PublisherIsolationError("README verification requires a repository root")
        else:
            template_path = self.root / "templates" / "README.md.j2"
            try:
                expected = render_readme(
                    ProjectStore(self.root).all(),
                    ObservationStore(self.root),
                    template_path=template_path if template_path.is_file() else None,
                )
            except Exception as exc:
                raise PublisherIsolationError("unable to rebuild trusted README") from exc
            if artifact.content != expected:
                raise PublisherIsolationError("README does not match trusted generator output")
        return digest
