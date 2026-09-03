"""Domain objects and validation for the V0.1 data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Mapping


PROJECT_KEYS = {
    "schema_version",
    "id",
    "display_name",
    "aliases",
    "repositories",
    "primary_category",
    "tags",
    "discovery_sources",
    "research_stage",
    "decision",
    "tracking",
    "personal_notes",
    "summary",
    "why_interesting",
    "use_cases",
}
REPOSITORY_KEYS = {"provider", "repository_id", "owner", "repo", "role"}
SOURCE_KEYS = {"type", "url", "discovered_at"}
OBSERVATION_KEYS = {
    "schema_version",
    "record_type",
    "event_id",
    "collection_key",
    "run_id",
    "project_id",
    "provider",
    "repository_id",
    "scheduled_at",
    "observed_at",
    "recorded_at",
    "collector_version",
    "source",
    "metrics",
    "facts",
    "unavailable",
    "supersedes",
    "correction_reason",
}
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESEARCH_STAGES = {"watching", "researching", "evaluated"}
DECISIONS = {"undecided", "adopt", "reference", "reject"}
TRACKING_LEVELS = {"daily", "weekly", "monthly", "off"}
REPOSITORY_ROLES = {"primary", "sdk", "docs", "other"}
RECORD_TYPES = {"observation", "correction", "invalidation"}


class ValidationError(ValueError):
    """Raised when a project or observation violates its data contract."""


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{path} must be an object")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValidationError(f"{path} contains unknown fields: {', '.join(unknown)}")


def _require_string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValidationError(f"{path} must be a non-empty string")
    return value


def _parse_utc(value: Any, path: str) -> datetime:
    text = _require_string(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValidationError(f"{path} must use UTC")
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return iso_utc(value)


def ensure_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timezone.utc.utcoffset(value)
    ):
        raise ValueError("timestamp must use UTC")
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def _validate_list_of_strings(value: Any, path: str, *, unique: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{path} must be an array")
    result = [_require_string(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if unique and len(result) != len(set(result)):
        raise ValidationError(f"{path} must not contain duplicates")
    return result


@dataclass(frozen=True)
class RepositoryRef:
    provider: str
    repository_id: int
    owner: str
    repo: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "repository_id": self.repository_id,
            "owner": self.owner,
            "repo": self.repo,
            "role": self.role,
        }


@dataclass(frozen=True)
class Project:
    schema_version: int
    id: str
    display_name: str
    aliases: tuple[str, ...]
    repositories: tuple[RepositoryRef, ...]
    primary_category: str
    tags: tuple[str, ...]
    discovery_sources: tuple[dict[str, str], ...]
    research_stage: str
    decision: str
    tracking: str
    personal_notes: str = ""
    summary: str | None = None
    why_interesting: tuple[str, ...] = field(default_factory=tuple)
    use_cases: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Project":
        validate_project_data(data)
        repositories = tuple(
            RepositoryRef(
                provider=item["provider"],
                repository_id=item["repository_id"],
                owner=item["owner"],
                repo=item["repo"],
                role=item["role"],
            )
            for item in data["repositories"]
        )
        return cls(
            schema_version=data["schema_version"],
            id=data["id"],
            display_name=data["display_name"],
            aliases=tuple(data["aliases"]),
            repositories=repositories,
            primary_category=data["primary_category"],
            tags=tuple(data["tags"]),
            discovery_sources=tuple(dict(source) for source in data["discovery_sources"]),
            research_stage=data["research_stage"],
            decision=data["decision"],
            tracking=data["tracking"],
            personal_notes=data.get("personal_notes", ""),
            summary=data.get("summary"),
            why_interesting=tuple(data.get("why_interesting", [])),
            use_cases=tuple(data.get("use_cases", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "repositories": [repository.to_dict() for repository in self.repositories],
            "primary_category": self.primary_category,
            "tags": list(self.tags),
            "discovery_sources": [dict(source) for source in self.discovery_sources],
            "research_stage": self.research_stage,
            "decision": self.decision,
            "tracking": self.tracking,
            "personal_notes": self.personal_notes,
        }
        if self.summary is not None:
            value["summary"] = self.summary
        if self.why_interesting:
            value["why_interesting"] = list(self.why_interesting)
        if self.use_cases:
            value["use_cases"] = list(self.use_cases)
        return value


def validate_project_data(data: Mapping[str, Any]) -> None:
    data = _require_mapping(data, "project")
    _reject_unknown(data, PROJECT_KEYS, "project")
    if data.get("schema_version") != 1:
        raise ValidationError("project.schema_version must be 1")

    project_id = _require_string(data.get("id"), "project.id")
    if not ID_PATTERN.fullmatch(project_id):
        raise ValidationError("project.id must be a lowercase slug")
    _require_string(data.get("display_name"), "project.display_name")

    _validate_list_of_strings(data.get("aliases", []), "project.aliases", unique=True)
    tags = _validate_list_of_strings(data.get("tags", []), "project.tags", unique=True)
    if any(not ID_PATTERN.fullmatch(tag) for tag in tags):
        raise ValidationError("project.tags must contain lowercase identifiers")
    primary_category = _require_string(data.get("primary_category"), "project.primary_category")
    if not ID_PATTERN.fullmatch(primary_category):
        raise ValidationError("project.primary_category must be a lowercase identifier")

    repositories = data.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValidationError("project.repositories must be a non-empty array")
    seen_repositories: set[tuple[str, int]] = set()
    primary_count = 0
    for index, raw_repository in enumerate(repositories):
        repository = _require_mapping(raw_repository, f"project.repositories[{index}]")
        _reject_unknown(repository, REPOSITORY_KEYS, f"project.repositories[{index}]")
        provider = _require_string(repository.get("provider"), f"project.repositories[{index}].provider")
        repository_id = repository.get("repository_id")
        if not isinstance(repository_id, int) or isinstance(repository_id, bool) or repository_id <= 0:
            raise ValidationError(f"project.repositories[{index}].repository_id must be a positive integer")
        _require_string(repository.get("owner"), f"project.repositories[{index}].owner")
        _require_string(repository.get("repo"), f"project.repositories[{index}].repo")
        role = _require_string(repository.get("role"), f"project.repositories[{index}].role")
        if role not in REPOSITORY_ROLES:
            raise ValidationError(f"project.repositories[{index}].role is not supported")
        key = (provider, repository_id)
        if key in seen_repositories:
            raise ValidationError("project.repositories must not repeat a provider and repository_id")
        seen_repositories.add(key)
        primary_count += role == "primary"
    if primary_count != 1:
        raise ValidationError("project.repositories must contain exactly one primary repository")

    sources = data.get("discovery_sources", [])
    if not isinstance(sources, list):
        raise ValidationError("project.discovery_sources must be an array")
    for index, raw_source in enumerate(sources):
        source = _require_mapping(raw_source, f"project.discovery_sources[{index}]")
        _reject_unknown(source, SOURCE_KEYS, f"project.discovery_sources[{index}]")
        _require_string(source.get("type"), f"project.discovery_sources[{index}].type")
        _require_string(source.get("url"), f"project.discovery_sources[{index}].url")
        _parse_utc(source.get("discovered_at"), f"project.discovery_sources[{index}].discovered_at")

    for field_name, allowed in (
        ("research_stage", RESEARCH_STAGES),
        ("decision", DECISIONS),
        ("tracking", TRACKING_LEVELS),
    ):
        value = _require_string(data.get(field_name), f"project.{field_name}")
        if value not in allowed:
            raise ValidationError(f"project.{field_name} is not supported")
    _require_string(data.get("personal_notes", ""), "project.personal_notes", nonempty=False)
    if "summary" in data and data["summary"] is not None:
        _require_string(data["summary"], "project.summary", nonempty=False)
    for field_name in ("why_interesting", "use_cases"):
        if field_name in data:
            _validate_list_of_strings(data[field_name], f"project.{field_name}")


@dataclass(frozen=True)
class ObservationRecord:
    schema_version: int
    record_type: str
    event_id: str
    collection_key: str
    run_id: str
    project_id: str
    provider: str
    repository_id: int
    scheduled_at: datetime
    observed_at: datetime
    recorded_at: datetime
    collector_version: str
    source: str
    metrics: dict[str, int | float]
    facts: dict[str, Any]
    unavailable: dict[str, str]
    supersedes: str | None = None
    correction_reason: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObservationRecord":
        validate_observation_data(data)
        return cls(
            schema_version=data["schema_version"],
            record_type=data["record_type"],
            event_id=data["event_id"],
            collection_key=data["collection_key"],
            run_id=data["run_id"],
            project_id=data["project_id"],
            provider=data["provider"],
            repository_id=data["repository_id"],
            scheduled_at=_parse_utc(data["scheduled_at"], "observation.scheduled_at"),
            observed_at=_parse_utc(data["observed_at"], "observation.observed_at"),
            recorded_at=_parse_utc(data["recorded_at"], "observation.recorded_at"),
            collector_version=data["collector_version"],
            source=data["source"],
            metrics=dict(data["metrics"]),
            facts=dict(data["facts"]),
            unavailable=dict(data["unavailable"]),
            supersedes=data.get("supersedes"),
            correction_reason=data.get("correction_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "record_type": self.record_type,
            "event_id": self.event_id,
            "collection_key": self.collection_key,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "provider": self.provider,
            "repository_id": self.repository_id,
            "scheduled_at": _iso_utc(self.scheduled_at),
            "observed_at": _iso_utc(self.observed_at),
            "recorded_at": _iso_utc(self.recorded_at),
            "collector_version": self.collector_version,
            "source": self.source,
            "metrics": dict(self.metrics),
            "facts": dict(self.facts),
            "unavailable": dict(self.unavailable),
        }
        if self.supersedes is not None:
            value["supersedes"] = self.supersedes
        if self.correction_reason is not None:
            value["correction_reason"] = self.correction_reason
        return value


def validate_observation_data(data: Mapping[str, Any]) -> None:
    data = _require_mapping(data, "observation")
    _reject_unknown(data, OBSERVATION_KEYS, "observation")
    if data.get("schema_version") != 1:
        raise ValidationError("observation.schema_version must be 1")
    record_type = _require_string(data.get("record_type"), "observation.record_type")
    if record_type not in RECORD_TYPES:
        raise ValidationError("observation.record_type is not supported")
    for field_name in (
        "event_id",
        "collection_key",
        "run_id",
        "project_id",
        "provider",
        "collector_version",
        "source",
    ):
        _require_string(data.get(field_name), f"observation.{field_name}")
    if not ID_PATTERN.fullmatch(data["project_id"]):
        raise ValidationError("observation.project_id must be a lowercase slug")
    repository_id = data.get("repository_id")
    if not isinstance(repository_id, int) or isinstance(repository_id, bool) or repository_id <= 0:
        raise ValidationError("observation.repository_id must be a positive integer")
    for field_name in ("scheduled_at", "observed_at", "recorded_at"):
        _parse_utc(data.get(field_name), f"observation.{field_name}")

    metrics = data.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValidationError("observation.metrics must be an object")
    for key, value in metrics.items():
        _require_string(key, "observation.metrics key")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValidationError(f"observation.metrics.{key} must be a non-negative number")

    facts = data.get("facts")
    unavailable = data.get("unavailable")
    if not isinstance(facts, Mapping) or not isinstance(unavailable, Mapping):
        raise ValidationError("observation.facts and observation.unavailable must be objects")
    for key, reason in unavailable.items():
        _require_string(key, "observation.unavailable key")
        _require_string(reason, f"observation.unavailable.{key}")
        if key not in facts or facts[key] is not None:
            raise ValidationError(f"observation.unavailable.{key} requires a null fact")

    supersedes = data.get("supersedes")
    reason = data.get("correction_reason")
    if record_type == "observation":
        if supersedes is not None or reason is not None:
            raise ValidationError("ordinary observations cannot contain correction fields")
    else:
        _require_string(supersedes, "observation.supersedes")
        _require_string(reason, "observation.correction_reason")
