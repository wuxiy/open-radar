"""Observation-only publisher boundary with strict path and content checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path, PurePosixPath
import re
from typing import Literal, Protocol

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from .contracts.schema import SchemaValidator
from .change_detection import ChangeEvent, ChangeEventStore
from .domain import ObservationRecord, ValidationError, writable_month
from .generation import render_readme
from .storage import ObservationStore, ProjectStore


ArtifactKind = Literal["observation", "change_event", "run", "readme"]
_MONTH_FILE = re.compile(r"^(?:19|20)[0-9]{2}-(0[1-9]|1[0-2])\.jsonl$")


class PublisherIsolationError(PermissionError):
    """Raised when a machine-data artifact crosses its allowed boundary."""


@dataclass(frozen=True)
class PublisherArtifact:
    path: str
    content: str
    kind: ArtifactKind
    sha256: str | None = None
    base_sha256: str | None = None


@dataclass(frozen=True)
class PublisherPlan:
    files: tuple[PublisherArtifact, ...]
    commit_message: str = "update observation data"
    idempotency_key: str = ""
    base_state_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.files:
            raise PublisherIsolationError("publisher plan cannot be empty")
        paths: set[str] = set()
        for artifact in self.files:
            if not isinstance(artifact, PublisherArtifact) or artifact.path in paths:
                raise PublisherIsolationError("publisher plan contains duplicate or invalid artifacts")
            if re.fullmatch(r"[0-9a-f]{64}", artifact.sha256 or "") is None:
                raise PublisherIsolationError("publisher plan artifact digest is missing")
            if artifact.base_sha256 is not None and re.fullmatch(
                r"[0-9a-f]{64}", artifact.base_sha256
            ) is None:
                raise PublisherIsolationError("publisher plan baseline digest is invalid")
            paths.add(artifact.path)
        for name, value in (
            ("idempotency_key", self.idempotency_key),
            ("base_state_sha256", self.base_state_sha256),
        ):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise PublisherIsolationError(f"publisher plan {name} must be a SHA-256 digest")

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)


@dataclass(frozen=True)
class PublisherCommitResult:
    """Receipt proving a sink committed the exact CAS base and plan."""

    committed: bool
    base_state_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.committed, bool):
            raise PublisherIsolationError("publisher sink committed flag must be boolean")
        for name, value in (
            ("base_state_sha256", self.base_state_sha256),
            ("idempotency_key", self.idempotency_key),
        ):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise PublisherIsolationError(f"publisher sink {name} must be a SHA-256 digest")


class PublisherSink(Protocol):
    """Sink that must enforce the plan's baseline CAS before writing."""

    def open_or_update(
        self, plan: PublisherPlan, *, expected_base_state_sha256: str
    ) -> PublisherCommitResult: ...


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
            base_sha256 = self._validate_baseline(path, artifact)
            digest = self._validate_content(artifact)
            normalized.append(
                PublisherArtifact(
                    path,
                    artifact.content,
                    artifact.kind,
                    digest,
                    base_sha256,
                )
            )
        if not normalized:
            raise PublisherIsolationError("publisher plan cannot be empty")
        normalized.sort(key=lambda item: item.path)
        self._validate_overlay(normalized)
        canonical_baselines = "\n".join(
            f"{item.path}:{item.base_sha256 or '<absent>'}" for item in normalized
        )
        base_state_sha256 = hashlib.sha256(canonical_baselines.encode("utf-8")).hexdigest()
        idempotency_material = "\n".join(
            f"{item.path}:{item.sha256}:{item.base_sha256 or '<absent>'}" for item in normalized
        )
        idempotency_key = hashlib.sha256(idempotency_material.encode("utf-8")).hexdigest()
        return PublisherPlan(
            files=tuple(normalized),
            commit_message=commit_message.strip(),
            idempotency_key=idempotency_key,
            base_state_sha256=base_state_sha256,
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
            open_or_update = getattr(sink, "open_or_update", None)
            if not callable(open_or_update):
                raise PublisherIsolationError(
                    "publisher sink must implement open_or_update with compare-and-swap"
                )
            try:
                inspect.signature(open_or_update).bind(
                    plan, expected_base_state_sha256=plan.base_state_sha256
                )
            except (TypeError, ValueError) as exc:
                raise PublisherIsolationError(
                    "publisher sink must implement compare-and-swap with expected_base_state_sha256"
                ) from exc
            result = open_or_update(
                plan, expected_base_state_sha256=plan.base_state_sha256
            )
            if not isinstance(result, PublisherCommitResult):
                raise PublisherIsolationError(
                    "publisher sink must return PublisherCommitResult"
                )
            if not result.committed:
                raise PublisherIsolationError("publisher sink rejected CAS baseline")
            if (
                result.base_state_sha256 != plan.base_state_sha256
                or result.idempotency_key != plan.idempotency_key
            ):
                raise PublisherIsolationError(
                    "publisher sink receipt does not match the submitted plan"
                )
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
        elif kind == "change_event":
            if len(path.parts) != 3 or path.parts[:2] != ("data", "change-events"):
                raise PublisherIsolationError("change-event publisher can only write monthly event logs")
            if _MONTH_FILE.fullmatch(path.name) is None:
                raise PublisherIsolationError("change-event publisher requires a YYYY-MM.jsonl file")
        elif kind == "run":
            if len(path.parts) != 3 or path.parts[:2] != ("data", "runs") or _MONTH_FILE.fullmatch(path.name) is None:
                raise PublisherIsolationError("run publisher can only write monthly compact manifests")
        elif kind == "readme":
            if value != "README.md":
                raise PublisherIsolationError("readme publisher can only write README.md")
        else:
            raise PublisherIsolationError("unsupported publisher artifact kind")
        if self.root is not None:
            cursor = self.root
            for part in path.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise PublisherIsolationError(
                        "publisher refuses to traverse symlink path components"
                    )
            resolved = (self.root / Path(*path.parts)).resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise PublisherIsolationError("publisher path escapes repository root") from exc
            destination = self.root.joinpath(*path.parts)
            if destination.is_symlink():
                raise PublisherIsolationError("publisher refuses to write through symlinks")
        return value

    def _validate_baseline(self, path: str, artifact: PublisherArtifact) -> str | None:
        if self.root is None:
            if artifact.kind in {"observation", "change_event", "run"}:
                raise PublisherIsolationError(
                    "machine artifacts require a repository root for CAS and append validation"
                )
            if artifact.base_sha256 is not None:
                raise PublisherIsolationError("publisher base_sha256 requires a repository root")
            return None
        if artifact.kind in {"observation", "change_event", "run"}:
            month = PurePosixPath(path).stem
            if month < datetime.now(timezone.utc).strftime("%Y-%m"):
                raise PublisherIsolationError(
                    "publisher cannot mutate a closed historical month"
                )
        destination = self.root / Path(*PurePosixPath(path).parts)
        exists = destination.exists()
        if exists and not destination.is_file():
            raise PublisherIsolationError("publisher destination must be a regular file")
        current = destination.read_bytes() if exists else b""
        current_sha256 = hashlib.sha256(current).hexdigest() if exists else None
        if artifact.base_sha256 != current_sha256:
            raise PublisherIsolationError(
                f"publisher baseline CAS mismatch for {path}: expected {artifact.base_sha256 or '<absent>'}, "
                f"found {current_sha256 or '<absent>'}"
            )
        if exists and artifact.kind in {"observation", "change_event", "run"}:
            try:
                current_text = current.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PublisherIsolationError("publisher existing artifact is not UTF-8") from exc
            if not artifact.content.startswith(current_text):
                raise PublisherIsolationError(
                    f"publisher {artifact.kind} artifact must append to its baseline"
                )
        return current_sha256

    @staticmethod
    def _parse_observations(content: str, path: str) -> list[ObservationRecord]:
        records: list[ObservationRecord] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                records.append(ObservationRecord.from_dict(value))
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
                raise PublisherIsolationError(
                    f"publisher observation is invalid at {path}:{line_number}"
                ) from exc
        return records

    @staticmethod
    def _parse_change_events(content: str, path: str) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                events.append(ChangeEvent.from_dict(value))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise PublisherIsolationError(
                    f"publisher change event is invalid at {path}:{line_number}"
                ) from exc
        return events

    def _validate_overlay(self, artifacts: list[PublisherArtifact]) -> None:
        observation_artifacts = [item for item in artifacts if item.kind == "observation"]
        change_event_artifacts = [item for item in artifacts if item.kind == "change_event"]
        run_artifacts = [item for item in artifacts if item.kind == "run"]
        by_event: dict[str, ObservationRecord] = {}
        by_collection: dict[str, ObservationRecord] = {}
        overlay_event_ids: set[str] = set()
        overlay_collection_keys: set[str] = set()
        corrections: set[str] = set()
        existing_records: list[ObservationRecord] = []
        existing_observations_by_path: dict[str, list[ObservationRecord]] = {}
        existing_change_events: list[ChangeEvent] = []
        existing_change_events_by_path: dict[str, list[ChangeEvent]] = {}
        projects = []
        if self.root is not None:
            try:
                observation_directory = self.root / "data" / "observations" / "github"
                for path in sorted(observation_directory.glob("*.jsonl")):
                    path_key = path.relative_to(self.root).as_posix()
                    records = self._parse_observations(
                        path.read_text(encoding="utf-8"), path_key
                    )
                    existing_observations_by_path[path_key] = records
                    existing_records.extend(records)
                change_event_directory = self.root / "data" / "change-events"
                for path in sorted(change_event_directory.glob("*.jsonl")):
                    path_key = path.relative_to(self.root).as_posix()
                    events = self._parse_change_events(
                        path.read_text(encoding="utf-8"), path_key
                    )
                    existing_change_events_by_path[path_key] = events
                    existing_change_events.extend(events)
                projects = ProjectStore(self.root).all()
            except (ValidationError, ValueError, OSError) as exc:
                raise PublisherIsolationError("existing repository data is invalid") from exc
        all_records: list[tuple[str, ObservationRecord]] = []
        baseline_replays: set[tuple[str, str]] = set()
        for artifact in observation_artifacts:
            month = PurePosixPath(artifact.path).stem
            records = self._parse_observations(artifact.content, artifact.path)
            baseline = existing_observations_by_path.get(artifact.path, [])
            for record in records:
                if writable_month(record.recorded_at) != month:
                    raise PublisherIsolationError(
                        f"publisher observation timestamp does not match monthly path: {artifact.path}"
                    )
            for index, record in enumerate(records):
                if index < len(baseline) and record.event_id == baseline[index].event_id:
                    if not self._same_replay(record, baseline[index]):
                        raise PublisherIsolationError(
                            "publisher baseline observation was modified"
                        )
                    baseline_replays.add((artifact.path, record.event_id))
                all_records.append((artifact.path, record))
        for record in existing_records:
            by_event[record.event_id] = record
            if record.record_type == "observation":
                by_collection[record.collection_key] = record
            elif record.supersedes:
                corrections.add(record.supersedes)
        project_map = {project.id: project for project in projects}
        for artifact_path, record in all_records:
            if record.event_id in overlay_event_ids:
                raise PublisherIsolationError(
                    "publisher observations repeat event_id across artifacts"
                )
            overlay_event_ids.add(record.event_id)
            if record.record_type == "observation":
                if record.collection_key in overlay_collection_keys:
                    raise PublisherIsolationError(
                        "publisher observations repeat collection_key across artifacts"
                    )
                overlay_collection_keys.add(record.collection_key)
            previous = by_event.get(record.event_id)
            if previous is not None:
                if (artifact_path, record.event_id) in baseline_replays and self._same_replay(previous, record):
                    continue
                raise PublisherIsolationError(
                    "publisher observations repeat an existing event_id"
                )
            if record.record_type == "observation":
                previous_slot = by_collection.get(record.collection_key)
                if previous_slot is not None:
                    raise PublisherIsolationError(
                        "publisher observations repeat collection_key across artifacts"
                    )
            elif record.supersedes in corrections:
                raise PublisherIsolationError("publisher correction branches are ambiguous")
            elif record.supersedes not in by_event:
                raise PublisherIsolationError("publisher correction target is not present")
            target = by_event.get(record.supersedes) if record.supersedes else None
            if target is not None and (
                target.project_id != record.project_id
                or target.provider != record.provider
                or target.repository_id != record.repository_id
                or target.collection_key != record.collection_key
            ):
                raise PublisherIsolationError("publisher correction identity does not match target")
            if record.record_type != "observation" and record.supersedes:
                corrections.add(record.supersedes)
            by_event[record.event_id] = record
            if record.record_type == "observation":
                by_collection[record.collection_key] = record
            if self.root is not None:
                project = project_map.get(record.project_id)
                if project is None or not any(
                    repository.provider == record.provider
                    and repository.repository_id == record.repository_id
                    for repository in project.repositories
                ):
                    raise PublisherIsolationError(
                        "publisher observation repository is not bound to its project"
                    )

        all_change_events: list[tuple[str, ChangeEvent]] = []
        baseline_change_replays: set[tuple[str, str]] = set()
        for artifact in change_event_artifacts:
            month = PurePosixPath(artifact.path).stem
            events = self._parse_change_events(artifact.content, artifact.path)
            baseline = existing_change_events_by_path.get(artifact.path, [])
            for event in events:
                if writable_month(event.detected_at) != month:
                    raise PublisherIsolationError(
                        f"publisher change-event timestamp does not match monthly path: {artifact.path}"
                    )
            for index, event in enumerate(events):
                if index < len(baseline) and event.fingerprint == baseline[index].fingerprint:
                    baseline_change_replays.add((artifact.path, event.fingerprint))
                all_change_events.append((artifact.path, event))

        existing_change_by_fingerprint = {
            event.fingerprint: event for event in existing_change_events
        }
        existing_change_by_id = {event.change_id: event for event in existing_change_events}
        existing_change_by_transition = {
            self._change_transition_key(event): event for event in existing_change_events
        }
        overlay_change_fingerprints: set[str] = set()
        overlay_change_ids: set[str] = set()
        overlay_change_transitions: set[tuple[str, str, str]] = set()
        for artifact_path, event in all_change_events:
            if event.before_event_id not in by_event or event.after_event_id not in by_event:
                raise PublisherIsolationError(
                    "publisher change event evidence observations are not present"
                )
            transition = self._change_transition_key(event)
            if event.fingerprint in overlay_change_fingerprints or event.change_id in overlay_change_ids:
                raise PublisherIsolationError("publisher change events repeat identity")
            if transition in overlay_change_transitions:
                raise PublisherIsolationError("publisher change events repeat a transition")
            overlay_change_fingerprints.add(event.fingerprint)
            overlay_change_ids.add(event.change_id)
            overlay_change_transitions.add(transition)
            previous = existing_change_by_fingerprint.get(event.fingerprint)
            if previous is not None:
                if (artifact_path, event.fingerprint) in baseline_change_replays:
                    continue
                raise PublisherIsolationError("publisher change event repeats an existing fingerprint")
            if event.change_id in existing_change_by_id:
                raise PublisherIsolationError("publisher change event repeats an existing change_id")
            if transition in existing_change_by_transition:
                raise PublisherIsolationError("publisher change event repeats an existing transition")
            if self.root is not None:
                project = project_map.get(event.project_id)
                if project is None or not any(
                    repository.provider == event.provider
                    and repository.repository_id == event.repository_id
                    for repository in project.repositories
                ):
                    raise PublisherIsolationError(
                        "publisher change event repository is not bound to its project"
                    )

        existing_runs: dict[str, str] = {}
        if self.root is not None:
            for path in sorted((self.root / "data" / "runs").glob("*.jsonl")):
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError) as exc:
                    raise PublisherIsolationError("existing run manifest is unreadable") from exc
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PublisherIsolationError("existing run manifest is invalid") from exc
                    run_id = value.get("run_id") if isinstance(value, dict) else None
                    if isinstance(run_id, str):
                        existing_runs[run_id] = json.dumps(
                            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                        )
        seen_runs: set[str] = set()
        for artifact in run_artifacts:
            month = PurePosixPath(artifact.path).stem
            for line_number, line in enumerate(artifact.content.splitlines(), start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                run_id = value.get("run_id") if isinstance(value, dict) else None
                if not isinstance(run_id, str) or not run_id.strip():
                    raise PublisherIsolationError(
                        f"publisher run manifest has no run_id at {artifact.path}:{line_number}"
                    )
                if run_id in seen_runs:
                    raise PublisherIsolationError("publisher run manifest repeats run_id")
                seen_runs.add(run_id)
                canonical = json.dumps(
                    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                previous = existing_runs.get(run_id)
                if previous is not None and previous != canonical:
                    raise PublisherIsolationError(
                        "publisher run manifest changes an existing run_id"
                    )
                if isinstance(value.get("started_at"), str) and not value["started_at"].startswith(month):
                    raise PublisherIsolationError(
                        f"publisher run timestamp does not match monthly path: {artifact.path}"
                    )

        readme = next((item for item in artifacts if item.kind == "readme"), None)
        if readme is not None:
            if self.root is None:
                raise PublisherIsolationError("README verification requires a repository root")
            overlay_records = list(existing_records)
            for artifact in observation_artifacts:
                target_event_ids = {
                    record.event_id
                    for record in existing_observations_by_path.get(artifact.path, [])
                }
                overlay_records = [
                    record
                    for record in overlay_records
                    if record.event_id not in target_event_ids
                ]
                overlay_records.extend(self._parse_observations(artifact.content, artifact.path))
            template_path = self.root / "templates" / "README.md.j2"
            try:
                expected = render_readme(
                    projects,
                    overlay_records,
                    template_path=template_path if template_path.is_file() else None,
                )
            except Exception as exc:
                raise PublisherIsolationError("unable to rebuild trusted README") from exc
            if readme.content != expected:
                raise PublisherIsolationError("README does not match trusted generator output")

    @staticmethod
    def _same_replay(left: ObservationRecord, right: ObservationRecord) -> bool:
        left_data = left.to_dict()
        right_data = right.to_dict()
        left_data.pop("run_id", None)
        right_data.pop("run_id", None)
        return left_data == right_data

    @staticmethod
    def _change_transition_key(event: ChangeEvent) -> tuple[str, str, str]:
        return event.before_event_id, event.after_event_id, event.field

    def _validate_content(self, artifact: PublisherArtifact) -> str:
        if not isinstance(artifact.content, str) or "\x00" in artifact.content:
            raise PublisherIsolationError("publisher content must be UTF-8 text without NUL bytes")
        encoded = artifact.content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise PublisherIsolationError("publisher artifact exceeds size limit")
        digest = hashlib.sha256(encoded).hexdigest()
        if artifact.sha256 is not None and artifact.sha256 != digest:
            raise PublisherIsolationError("publisher artifact sha256 does not match content")
        if artifact.kind in {"observation", "change_event", "run"}:
            seen_events: set[str] = set()
            seen_slots: set[str] = set()
            seen_superseded: set[str] = set()
            existing_events: set[str] = set()
            existing_change_fingerprints: set[str] = set()
            if artifact.kind == "observation" and self.root is not None:
                try:
                    existing_events = {record.event_id for record in ObservationStore(self.root).all()}
                except (ValidationError, ValueError) as exc:
                    raise PublisherIsolationError("existing observation log is invalid") from exc
            if artifact.kind == "change_event" and self.root is not None:
                try:
                    existing_change_fingerprints = {
                        event.fingerprint for event in ChangeEventStore(self.root).all()
                    }
                except (ValueError, OSError) as exc:
                    raise PublisherIsolationError("existing change-event log is invalid") from exc
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
                elif artifact.kind == "change_event":
                    try:
                        event = ChangeEvent.from_dict(value)
                    except (ValueError, TypeError) as exc:
                        raise PublisherIsolationError(
                            f"publisher change event is invalid at line {line_number}"
                        ) from exc
                    if event.fingerprint in seen_events:
                        raise PublisherIsolationError("publisher change event repeats fingerprint")
                    seen_events.add(event.fingerprint)
                    if event.fingerprint in existing_change_fingerprints:
                        # Existing baseline rows are checked again by _validate_overlay;
                        # keeping this set here prevents duplicate new rows in one artifact.
                        continue
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
                            if value.get("kind") not in {
                                "ingest", "collect", "detect-changes", "generate", "validate"
                            }:
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
            # README content is checked after all observation artifacts are
            # overlaid, so the derived view cannot be stale.
            pass
        return digest
