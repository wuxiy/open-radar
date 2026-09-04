"""Deterministic change events derived from observation history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping

from .domain import ID_PATTERN, ObservationRecord, ensure_utc, iso_utc, writable_month


CHANGE_TYPES = {"archive", "license", "activity", "fact"}
SEVERITIES = {"low", "medium", "high"}
FIELD_PATTERN = re.compile(r"^(?:facts|metrics)\.[a-z][a-z0-9_]*$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHANGE_ID_PATTERN = re.compile(r"^change-[0-9a-f]{24}$")
RULE_VERSION = "change-rules/1"


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _json_value(value: Any, path: str) -> Any:
    try:
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be JSON serializable") from exc
    return value


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    return value


@dataclass(frozen=True)
class ChangeRule:
    """A deterministic field comparison and its analysis trigger threshold."""

    field: str
    change_type: str
    severity: str
    minimum_absolute: float | None = None
    minimum_relative: float | None = None

    def __post_init__(self) -> None:
        _require_string(self.field, "change rule field")
        if not FIELD_PATTERN.fullmatch(self.field):
            raise ValueError("change rule field must use facts.<name> or metrics.<name>")
        if self.change_type not in CHANGE_TYPES:
            raise ValueError("change rule type is not supported")
        if self.severity not in SEVERITIES:
            raise ValueError("change rule severity is not supported")
        for value, name in (
            (self.minimum_absolute, "minimum_absolute"),
            (self.minimum_relative, "minimum_relative"),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0
            ):
                raise ValueError(f"change rule {name} must be positive when provided")

    def qualifies(self, before: Any, after: Any) -> bool:
        """Return whether a changed value is large enough to emit an event."""
        if self.minimum_absolute is None and self.minimum_relative is None:
            return True
        if (
            isinstance(before, bool)
            or isinstance(after, bool)
            or not isinstance(before, (int, float))
            or not isinstance(after, (int, float))
        ):
            return False
        delta = abs(after - before)
        absolute_hit = self.minimum_absolute is not None and delta >= self.minimum_absolute
        relative = delta / abs(before) if before != 0 else 0.0
        relative_hit = self.minimum_relative is not None and relative >= self.minimum_relative
        return bool(absolute_hit or relative_hit)


DEFAULT_RULES: tuple[ChangeRule, ...] = (
    ChangeRule("facts.archived", "archive", "high"),
    ChangeRule("facts.license_spdx", "license", "high"),
    ChangeRule("facts.language", "fact", "medium"),
    ChangeRule("facts.topics", "fact", "medium"),
    ChangeRule("metrics.stars", "activity", "medium", minimum_absolute=100, minimum_relative=0.2),
    ChangeRule("metrics.forks", "activity", "medium", minimum_absolute=25, minimum_relative=0.2),
)
RULES_BY_FIELD = {rule.field: rule for rule in DEFAULT_RULES}


class DuplicateChangeEventError(ValueError):
    """Raised when a change transition is replayed with different evidence."""


@dataclass(frozen=True)
class ChangeEvent:
    """An immutable, evidence-bound deterministic change event."""

    schema_version: int
    change_id: str
    fingerprint: str
    project_id: str
    provider: str
    repository_id: int
    before_event_id: str
    after_event_id: str
    before_observed_at: datetime
    after_observed_at: datetime
    detected_at: datetime
    change_type: str
    field: str
    severity: str
    before: Any
    after: Any
    rule_version: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChangeEvent":
        if not isinstance(data, Mapping):
            raise ValueError("change event must be an object")
        expected = {
            "schema_version",
            "change_id",
            "fingerprint",
            "project_id",
            "provider",
            "repository_id",
            "before_event_id",
            "after_event_id",
            "before_observed_at",
            "after_observed_at",
            "detected_at",
            "change_type",
            "field",
            "severity",
            "before",
            "after",
            "rule_version",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"change event contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"change event is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("change event schema_version must be 1")
        change_id = _require_string(data.get("change_id"), "change_id")
        if not CHANGE_ID_PATTERN.fullmatch(change_id):
            raise ValueError("change_id must be change- followed by 24 lowercase hex characters")
        fingerprint = _require_string(data.get("fingerprint"), "fingerprint")
        if not FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        project_id = _require_string(data.get("project_id"), "project_id")
        if not ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id must be a lowercase slug")
        provider = _require_string(data.get("provider"), "provider")
        repository_id = data.get("repository_id")
        if isinstance(repository_id, bool) or not isinstance(repository_id, int) or repository_id <= 0:
            raise ValueError("repository_id must be a positive integer")
        before_event_id = _require_string(data.get("before_event_id"), "before_event_id")
        after_event_id = _require_string(data.get("after_event_id"), "after_event_id")
        if before_event_id == after_event_id:
            raise ValueError("before_event_id and after_event_id must differ")

        def timestamp(name: str) -> datetime:
            value = _require_string(data.get(name), name)
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
            try:
                return ensure_utc(parsed)
            except ValueError as exc:
                raise ValueError(f"{name} must use UTC") from exc

        before_observed_at = timestamp("before_observed_at")
        after_observed_at = timestamp("after_observed_at")
        detected_at = timestamp("detected_at")
        if before_observed_at > after_observed_at:
            raise ValueError("before_observed_at must not be after after_observed_at")
        if detected_at < after_observed_at:
            raise ValueError("detected_at must not be before after_observed_at")
        change_type = _require_string(data.get("change_type"), "change_type")
        if change_type not in CHANGE_TYPES:
            raise ValueError("change_type is not supported")
        field = _require_string(data.get("field"), "field")
        if not FIELD_PATTERN.fullmatch(field):
            raise ValueError("field must use facts.<name> or metrics.<name>")
        severity = _require_string(data.get("severity"), "severity")
        if severity not in SEVERITIES:
            raise ValueError("severity is not supported")
        before = _json_value(data.get("before"), "before")
        after = _json_value(data.get("after"), "after")
        if _canonical(before) == _canonical(after):
            raise ValueError("change event before and after values must differ")
        rule_version = _require_string(data.get("rule_version"), "rule_version")
        event = cls(
            schema_version=1,
            change_id=change_id,
            fingerprint=fingerprint,
            project_id=project_id,
            provider=provider,
            repository_id=repository_id,
            before_event_id=before_event_id,
            after_event_id=after_event_id,
            before_observed_at=before_observed_at,
            after_observed_at=after_observed_at,
            detected_at=detected_at,
            change_type=change_type,
            field=field,
            severity=severity,
            before=before,
            after=after,
            rule_version=rule_version,
        )
        _validate_rule_binding(event)
        expected_fingerprint = _fingerprint_for(event)
        if event.fingerprint != expected_fingerprint:
            raise ValueError("change event fingerprint does not match its evidence")
        if event.change_id != f"change-{event.fingerprint[:24]}":
            raise ValueError("change_id does not match fingerprint")
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "change_id": self.change_id,
            "fingerprint": self.fingerprint,
            "project_id": self.project_id,
            "provider": self.provider,
            "repository_id": self.repository_id,
            "before_event_id": self.before_event_id,
            "after_event_id": self.after_event_id,
            "before_observed_at": iso_utc(self.before_observed_at),
            "after_observed_at": iso_utc(self.after_observed_at),
            "detected_at": iso_utc(self.detected_at),
            "change_type": self.change_type,
            "field": self.field,
            "severity": self.severity,
            "before": self.before,
            "after": self.after,
            "rule_version": self.rule_version,
        }


def _fingerprint_for(event: ChangeEvent) -> str:
    payload = {
        "after_event_id": event.after_event_id,
        "after_observed_at": iso_utc(event.after_observed_at),
        "before": _canonical(event.before),
        "before_event_id": event.before_event_id,
        "before_observed_at": iso_utc(event.before_observed_at),
        "change_type": event.change_type,
        "field": event.field,
        "project_id": event.project_id,
        "provider": event.provider,
        "repository_id": event.repository_id,
        "rule_version": event.rule_version,
        "severity": event.severity,
        "after": _canonical(event.after),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_rule_binding(event: ChangeEvent) -> None:
    if event.rule_version != RULE_VERSION:
        raise ValueError(f"unsupported change rule version: {event.rule_version}")
    rule = RULES_BY_FIELD.get(event.field)
    if rule is None:
        raise ValueError(f"change field is not registered: {event.field}")
    if event.change_type != rule.change_type or event.severity != rule.severity:
        raise ValueError("change event type or severity does not match its registered rule")
    if event.field == "facts.archived":
        valid = isinstance(event.before, bool) and isinstance(event.after, bool)
    elif event.field in {"facts.license_spdx", "facts.language"}:
        valid = all(isinstance(value, str) and bool(value.strip()) for value in (event.before, event.after))
    elif event.field == "facts.topics":
        valid = all(
            isinstance(value, list)
            and all(isinstance(item, str) and bool(item.strip()) for item in value)
            for value in (event.before, event.after)
        )
    else:
        valid = all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
            for value in (event.before, event.after)
        )
    if not valid:
        raise ValueError(f"change event values are invalid for rule field: {event.field}")
    if not rule.qualifies(event.before, event.after):
        raise ValueError("change event values do not meet the registered rule threshold")


class ChangeDetector:
    """Compare active observation history and emit deterministic change events."""

    def __init__(self, rules: Iterable[ChangeRule] = DEFAULT_RULES) -> None:
        self._rules = tuple(rules)
        if not self._rules:
            raise ValueError("at least one change rule is required")
        fields = [rule.field for rule in self._rules]
        if len(fields) != len(set(fields)):
            raise ValueError("change rules must not repeat a field")
        if self._rules != DEFAULT_RULES:
            raise ValueError("custom change rules require a registered rule version")

    def detect(
        self,
        records: Iterable[ObservationRecord],
        *,
        detected_at: datetime,
        project_id: str | None = None,
    ) -> list[ChangeEvent]:
        detected_at = ensure_utc(detected_at)
        active_records = self._active_records(records)
        grouped: dict[tuple[str, str, int], list[ObservationRecord]] = {}
        for record in active_records:
            if project_id is not None and record.project_id != project_id:
                continue
            grouped.setdefault((record.project_id, record.provider, record.repository_id), []).append(record)

        events: list[ChangeEvent] = []
        for key in sorted(grouped):
            history = sorted(
                grouped[key],
                key=lambda item: (item.observed_at, item.recorded_at, item.event_id),
            )
            for before_record, after_record in zip(history, history[1:]):
                for rule in self._rules:
                    before = self._value(before_record, rule.field)
                    after = self._value(after_record, rule.field)
                    if before is None or after is None:
                        continue
                    before_value, after_value = before, after
                    if rule.field == "facts.topics":
                        before_value = sorted(before_value) if isinstance(before_value, list) else before_value
                        after_value = sorted(after_value) if isinstance(after_value, list) else after_value
                    if _canonical(before_value) == _canonical(after_value) or not rule.qualifies(
                        before_value, after_value
                    ):
                        continue
                    event_without_identity = ChangeEvent(
                        schema_version=1,
                        change_id="change-" + ("0" * 24),
                        fingerprint="0" * 64,
                        project_id=after_record.project_id,
                        provider=after_record.provider,
                        repository_id=after_record.repository_id,
                        before_event_id=before_record.event_id,
                        after_event_id=after_record.event_id,
                        before_observed_at=before_record.observed_at,
                        after_observed_at=after_record.observed_at,
                        detected_at=detected_at,
                        change_type=rule.change_type,
                        field=rule.field,
                        severity=rule.severity,
                        before=before_value,
                        after=after_value,
                        rule_version=RULE_VERSION,
                    )
                    fingerprint = _fingerprint_for(event_without_identity)
                    event = replace(
                        event_without_identity,
                        change_id=f"change-{fingerprint[:24]}",
                        fingerprint=fingerprint,
                    )
                    events.append(event)
        return events

    @staticmethod
    def _active_records(records: Iterable[ObservationRecord]) -> list[ObservationRecord]:
        materialized = list(records)
        superseded = {
            record.supersedes
            for record in materialized
            if record.record_type in {"correction", "invalidation"} and record.supersedes
        }
        return [
            record
            for record in materialized
            if record.record_type in {"observation", "correction"} and record.event_id not in superseded
        ]

    @staticmethod
    def _value(record: ObservationRecord, field: str) -> Any | None:
        namespace, name = field.split(".", 1)
        source = record.facts if namespace == "facts" else record.metrics
        if name not in source or name in record.unavailable:
            return None
        value = source[name]
        return None if value is None else value


def detect_changes(
    records: Iterable[ObservationRecord],
    *,
    detected_at: datetime,
    project_id: str | None = None,
) -> list[ChangeEvent]:
    """Convenience wrapper around the default deterministic rules."""
    return ChangeDetector().detect(records, detected_at=detected_at, project_id=project_id)


class ChangeEventStore:
    """Append-only JSONL storage with replay and transition-level deduplication."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "change-events"
        self.lock_path = self.directory / ".append.lock"

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

    def _paths(self) -> list[Path]:
        return sorted(self.directory.glob("*.jsonl"))

    def all(self) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        fingerprints: set[str] = set()
        transitions: set[tuple[str, str, str]] = set()
        for path in self._paths():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError(f"{path}: unreadable change event log") from exc
            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    event = ChangeEvent.from_dict(json.loads(line))
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"{path}:{line_number}: invalid change event") from exc
                if event.fingerprint in fingerprints:
                    raise ValueError(f"{path}:{line_number}: duplicate change fingerprint")
                transition = self._transition_key(event)
                if transition in transitions:
                    raise ValueError(f"{path}:{line_number}: duplicate change transition")
                fingerprints.add(event.fingerprint)
                transitions.add(transition)
                events.append(event)
        return events

    def append(self, event: ChangeEvent) -> bool:
        return self.append_many([event]) == 1

    def append_many(self, events: Iterable[ChangeEvent]) -> int:
        materialized = list(events)
        if not materialized:
            return 0
        with self._locked():
            return self._append_many_unlocked(materialized)

    def _append_many_unlocked(self, events: list[ChangeEvent]) -> int:
        existing = self.all()
        by_fingerprint = {event.fingerprint: event for event in existing}
        by_change_id = {event.change_id: event for event in existing}
        by_transition = {
            self._transition_key(event): event
            for event in existing
        }
        accepted: list[ChangeEvent] = []
        for candidate in events:
            if not isinstance(candidate, ChangeEvent):
                raise ValueError("change event must be a ChangeEvent")
            # Re-parse through the public contract so hand-built dataclass instances
            # cannot bypass identity, timestamp, or fingerprint validation.
            event = ChangeEvent.from_dict(candidate.to_dict())
            previous = by_fingerprint.get(event.fingerprint)
            if previous is not None:
                # detected_at is intentionally excluded from the fingerprint, so a
                # later replay of the same evidence is idempotent even when the run
                # clock has advanced.
                continue
            previous = by_change_id.get(event.change_id)
            if previous is not None:
                raise DuplicateChangeEventError(f"change_id already exists: {event.change_id}")
            transition = self._transition_key(event)
            previous = by_transition.get(transition)
            if previous is not None:
                raise DuplicateChangeEventError(
                    "change transition already exists: "
                    f"{transition[0]} -> {transition[1]} ({transition[2]})"
                )
            accepted.append(event)
            by_fingerprint[event.fingerprint] = event
            by_change_id[event.change_id] = event
            by_transition[transition] = event

        grouped: dict[Path, list[bytes]] = {}
        for event in accepted:
            path = self.directory / f"{writable_month(event.detected_at)}.jsonl"
            grouped.setdefault(path, []).append(
                (
                    json.dumps(
                        event.to_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            )
        if len(grouped) > 1:
            raise ValueError("change event batch must target one writable month partition")
        for path, payloads in grouped.items():
            original = path.read_bytes() if path.exists() else b""
            handle = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=self.directory,
                delete=False,
            )
            temporary = Path(handle.name)
            try:
                handle.write(original)
                for payload in payloads:
                    handle.write(payload)
                handle.close()
                temporary.replace(path)
            except Exception:
                handle.close()
                temporary.unlink(missing_ok=True)
                raise
        return len(accepted)

    @staticmethod
    def _transition_key(event: ChangeEvent) -> tuple[str, str, str]:
        return event.before_event_id, event.after_event_id, event.field
