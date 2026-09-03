"""Git-backed persistence for projects, observations, and run data."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterator

import yaml

from .domain import ObservationRecord, Project, ValidationError


class DuplicateCollectionError(ValueError):
    """Raised when a collection slot is replayed with different data."""


def current_observations(
    records: list[ObservationRecord], project_id: str | None = None
) -> list[ObservationRecord]:
    selected = [record for record in records if project_id is None or record.project_id == project_id]
    superseded = {
        record.supersedes
        for record in selected
        if record.record_type in {"correction", "invalidation"}
    }
    active = [
        record
        for record in selected
        if record.record_type != "invalidation" and record.event_id not in superseded
    ]
    latest: dict[tuple[str, int], ObservationRecord] = {}
    for record in active:
        key = (record.provider, record.repository_id)
        previous = latest.get(key)
        if previous is None or (record.observed_at, record.recorded_at) > (
            previous.observed_at,
            previous.recorded_at,
        ):
            latest[key] = record
    return sorted(latest.values(), key=lambda item: (item.provider, item.repository_id))


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "projects"
        self.lock_path = self.directory / ".write.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize admission check-and-write transactions across processes."""
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

    def save(self, project: Project) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{project.id}.yaml"
        temporary = destination.with_suffix(".yaml.tmp")
        temporary.write_text(
            yaml.safe_dump(
                project.to_dict(),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    def load(self, project_id: str) -> Project:
        path = self.directory / f"{project_id}.yaml"
        if not path.is_file():
            raise FileNotFoundError(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Project.from_dict(data)

    def all(self) -> list[Project]:
        projects = []
        for path in sorted(self.directory.glob("*.yaml")):
            projects.append(Project.from_dict(yaml.safe_load(path.read_text(encoding="utf-8"))))
        return projects

    def find_by_repository(self, provider: str, repository_id: int) -> Project | None:
        for project in self.all():
            if any(
                repository.provider == provider and repository.repository_id == repository_id
                for repository in project.repositories
            ):
                return project
        return None


class ObservationStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "observations" / "github"
        self.lock_path = self.directory / ".append.lock"

    def _paths(self) -> Iterator[Path]:
        yield from sorted(self.directory.glob("*.jsonl"))

    def all(self) -> list[ObservationRecord]:
        records: list[ObservationRecord] = []
        for path in self._paths():
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    records.append(ObservationRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise ValidationError(f"{path}:{line_number}: invalid observation") from exc
        return records

    @contextmanager
    def _locked(self) -> Iterator[None]:
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

    def append(self, record: ObservationRecord) -> bool:
        with self._locked():
            return self._append_unlocked(record)

    def _append_unlocked(self, record: ObservationRecord) -> bool:
        existing = self.all()
        by_event = {item.event_id: item for item in existing}
        if record.event_id in by_event:
            if self._same_replay(by_event[record.event_id], record):
                return False
            raise DuplicateCollectionError(f"event_id already exists: {record.event_id}")

        if record.record_type == "observation":
            matching_slots = [
                item for item in existing if item.collection_key == record.collection_key
            ]
            if matching_slots:
                if self._same_replay(matching_slots[0], record):
                    return False
                raise DuplicateCollectionError(
                    f"collection_key already exists: {record.collection_key}"
                )
        elif record.supersedes not in by_event:
            raise ValidationError(
                f"observation.supersedes does not exist: {record.supersedes}"
            )
        elif record.supersedes == record.event_id:
            raise ValidationError("observation corrections cannot supersede themselves")
        else:
            target = by_event[record.supersedes]
            if (
                target.project_id != record.project_id
                or target.provider != record.provider
                or target.repository_id != record.repository_id
                or target.collection_key != record.collection_key
            ):
                raise ValidationError(
                    "observation correction must preserve project, repository, and collection identity"
                )
            if any(
                item.record_type in {"correction", "invalidation"}
                and item.supersedes == record.supersedes
                for item in existing
            ):
                raise ValidationError(
                    f"observation supersedes has an existing correction: {record.supersedes}"
                )
            cursor = target
            visited = {record.event_id}
            while cursor.record_type in {"correction", "invalidation"} and cursor.supersedes:
                if cursor.event_id in visited:
                    raise ValidationError("observation correction chain contains a cycle")
                visited.add(cursor.event_id)
                cursor = by_event.get(cursor.supersedes, cursor)

        path = self.directory / f"{record.recorded_at:%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    record.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        return True

    @staticmethod
    def _same_replay(left: ObservationRecord, right: ObservationRecord) -> bool:
        """Treat a retry with a new run id as the same collection result."""
        left_data = left.to_dict()
        right_data = right.to_dict()
        left_data.pop("run_id", None)
        right_data.pop("run_id", None)
        return left_data == right_data

    def append_batch(self, records: list[ObservationRecord]) -> int:
        with self._locked():
            appended = 0
            for record in sorted(records, key=lambda item: (item.recorded_at, item.event_id)):
                appended += int(self._append_unlocked(record))
            return appended

    def current_for(self, project_id: str) -> list[ObservationRecord]:
        return current_observations(self.all(), project_id)

    def integrity_errors(self) -> list[str]:
        """Check correction references and branches in already-existing logs."""
        records = self.all()
        by_event = {record.event_id: record for record in records}
        errors: list[str] = []
        branches: dict[str, list[str]] = {}
        for record in records:
            if record.record_type not in {"correction", "invalidation"}:
                continue
            assert record.supersedes is not None
            branches.setdefault(record.supersedes, []).append(record.event_id)
            target = by_event.get(record.supersedes)
            if target is None:
                errors.append(f"{record.event_id}: supersedes unknown event {record.supersedes}")
                continue
            if (
                target.project_id != record.project_id
                or target.provider != record.provider
                or target.repository_id != record.repository_id
                or target.collection_key != record.collection_key
            ):
                errors.append(f"{record.event_id}: correction identity does not match target")
            visited: set[str] = set()
            cursor = record
            while cursor.supersedes is not None:
                if cursor.event_id in visited:
                    errors.append(f"{record.event_id}: correction chain contains a cycle")
                    break
                visited.add(cursor.event_id)
                next_record = by_event.get(cursor.supersedes)
                if next_record is None:
                    break
                cursor = next_record
        for superseded, event_ids in branches.items():
            if len(event_ids) > 1:
                errors.append(f"{superseded}: correction branch conflict ({', '.join(sorted(event_ids))})")
        return errors

    def month_files(self) -> list[Path]:
        return list(self._paths())
