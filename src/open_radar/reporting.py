"""Deterministic historical Markdown reports."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping

from .domain import ID_PATTERN, ObservationRecord, Project, ensure_utc, iso_utc
from .scoring import Context, SCORE_VERSION, ScoreCard
from .storage import current_observations


REPORT_TYPES = {"weekly", "monthly"}
REPORT_ID_PATTERN = re.compile(r"^report-[a-z0-9][a-z0-9-]*$")


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


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _input_digest(
    projects: Iterable[Project],
    observations: Iterable[ObservationRecord],
    scorecards: Iterable[ScoreCard],
    *,
    context: Context | None = None,
    context_id: str | None = None,
) -> str:
    payload = {
        "projects": [project.to_dict() for project in sorted(projects, key=lambda item: item.id)],
        "observations": [
            observation.to_dict()
            for observation in sorted(
                observations,
                key=lambda item: (item.project_id, item.provider, item.repository_id, item.observed_at, item.event_id),
            )
        ],
        "scorecards": [card.to_dict() for card in sorted(scorecards, key=lambda item: (item.project_id, item.context_id or ""))],
        "context": context.to_dict() if context is not None else {"context_id": context_id},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ReportSnapshot:
    """Immutable metadata and content for one historical report."""

    schema_version: int
    report_id: str
    report_type: str
    cutoff_at: datetime
    generated_at: datetime
    input_version: str
    input_digest: str
    score_version: str
    prompt_versions: tuple[str, ...]
    project_ids: tuple[str, ...]
    context_id: str | None
    content: str
    content_sha256: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReportSnapshot":
        if not isinstance(data, Mapping):
            raise ValueError("report snapshot must be an object")
        expected = {
            "schema_version", "report_id", "report_type", "cutoff_at", "generated_at",
            "input_version", "input_digest", "score_version", "prompt_versions", "project_ids", "context_id",
            "content", "content_sha256",
        }
        unknown = sorted(set(data) - expected)
        if unknown:
            raise ValueError(f"report snapshot contains unknown fields: {', '.join(unknown)}")
        missing = sorted(expected - set(data))
        if missing:
            raise ValueError(f"report snapshot is missing fields: {', '.join(missing)}")
        if data.get("schema_version") != 1:
            raise ValueError("report snapshot schema_version must be 1")
        report_id = _require_string(data.get("report_id"), "report_id")
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            raise ValueError("report_id must be a report- slug")
        report_type = _require_string(data.get("report_type"), "report_type")
        if report_type not in REPORT_TYPES:
            raise ValueError("report_type is not supported")
        cutoff_at = _timestamp(data.get("cutoff_at"), "cutoff_at")
        generated_at = _timestamp(data.get("generated_at"), "generated_at")
        if generated_at < cutoff_at:
            raise ValueError("generated_at must not be before cutoff_at")
        input_version = _require_string(data.get("input_version"), "input_version")
        input_digest = _require_string(data.get("input_digest"), "input_digest")
        if re.fullmatch(r"[0-9a-f]{64}", input_digest) is None:
            raise ValueError("input_digest must be a lowercase SHA-256 hex digest")
        score_version = _require_string(data.get("score_version"), "score_version")
        prompt_versions = _strings(data.get("prompt_versions"), "prompt_versions")
        project_ids = _strings(data.get("project_ids"), "project_ids")
        if any(not ID_PATTERN.fullmatch(project_id) for project_id in project_ids):
            raise ValueError("project_ids must contain lowercase slugs")
        context_id = data.get("context_id")
        if context_id is not None:
            context_id = _require_string(context_id, "context_id")
            if not ID_PATTERN.fullmatch(context_id):
                raise ValueError("context_id must be a lowercase slug")
        content = _require_string(data.get("content"), "content")
        content_sha256 = _require_string(data.get("content_sha256"), "content_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        if content_sha256 != _hash_content(content):
            raise ValueError("content_sha256 does not match content")
        return cls(
            1, report_id, report_type, cutoff_at, generated_at, input_version,
            input_digest, score_version, prompt_versions, project_ids, context_id,
            content, content_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "report_type": self.report_type,
            "cutoff_at": iso_utc(self.cutoff_at),
            "generated_at": iso_utc(self.generated_at),
            "input_version": self.input_version,
            "input_digest": self.input_digest,
            "score_version": self.score_version,
            "prompt_versions": list(self.prompt_versions),
            "project_ids": list(self.project_ids),
            "context_id": self.context_id,
            "content": self.content,
            "content_sha256": self.content_sha256,
        }


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    result = tuple(_require_string(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise ValueError(f"{path} must not contain duplicates")
    return result


def _strings_from_iterable(value: Iterable[str], path: str) -> tuple[str, ...]:
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{path} must be an array") from exc
    result = tuple(_require_string(item, f"{path}[{index}]") for index, item in enumerate(values))
    if len(result) != len(set(result)):
        raise ValueError(f"{path} must not contain duplicates")
    return tuple(sorted(result))


class ReportRenderer:
    """Render the same report for the same versioned inputs."""

    def render(
        self,
        projects: Iterable[Project],
        observations: Iterable[ObservationRecord],
        scorecards: Iterable[ScoreCard],
        *,
        cutoff_at: datetime,
        input_version: str,
        report_type: str = "monthly",
        report_id: str | None = None,
        generated_at: datetime | None = None,
        score_version: str = SCORE_VERSION,
        prompt_versions: Iterable[str] = (),
        context_id: str | None = None,
        input_digest: str | None = None,
        context: Context | None = None,
    ) -> ReportSnapshot:
        cutoff_at = ensure_utc(cutoff_at)
        generated_at = ensure_utc(generated_at or cutoff_at)
        if generated_at < cutoff_at:
            raise ValueError("generated_at must not be before cutoff_at")
        if report_type not in REPORT_TYPES:
            raise ValueError("report_type is not supported")
        input_version = _require_string(input_version, "input_version")
        if score_version != SCORE_VERSION:
            raise ValueError(f"unsupported score version: {score_version}")
        if context_id is not None:
            context_id = _require_string(context_id, "context_id")
            if not ID_PATTERN.fullmatch(context_id):
                raise ValueError("context_id must be a lowercase slug")
        if context is not None:
            if not isinstance(context, Context):
                raise ValueError("context must be a Context")
            if context_id is not None and context.context_id != context_id:
                raise ValueError("context_id does not match context")
            context_id = context.context_id
        prompt_versions = _strings_from_iterable(prompt_versions, "prompt_versions")
        project_values = tuple(projects)
        if any(not isinstance(project, Project) for project in project_values):
            raise ValueError("reports require Project records")
        project_list = sorted(project_values, key=lambda project: project.id)
        project_ids = tuple(project.id for project in project_list)
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("projects must not contain duplicate IDs")
        if report_id is None:
            suffix = cutoff_at.strftime("%Y-%m") if report_type == "monthly" else cutoff_at.strftime("%Y-%m-%d")
            report_id = f"report-{report_type}-{suffix}"
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            raise ValueError("report_id must be a report- slug")
        observation_values = tuple(observations)
        if any(not isinstance(item, ObservationRecord) for item in observation_values):
            raise ValueError("reports require ObservationRecord records")
        records = [item for item in observation_values if item.observed_at <= cutoff_at]
        score_map: dict[str, ScoreCard] = {}
        scorecard_values = tuple(scorecards)
        if any(not isinstance(card, ScoreCard) for card in scorecard_values):
            raise ValueError("reports require ScoreCard records")
        for card in scorecard_values:
            if card.project_id not in project_ids:
                continue
            if card.evaluated_at > cutoff_at:
                continue
            if context_id is None and card.context_id is not None:
                continue
            if context_id is not None and card.context_id != context_id:
                continue
            previous = score_map.get(card.project_id)
            if previous is None or (card.evaluated_at, card.context_id or "") > (
                previous.evaluated_at, previous.context_id or ""
            ):
                score_map[card.project_id] = card
        current_by_project = {
            project.id: current_observations(records, project.id)
            for project in project_list
        }
        selected_cards = tuple(score_map[project_id] for project_id in sorted(score_map))
        if input_digest is None:
            input_digest = _input_digest(
                project_list,
                records,
                selected_cards,
                context=context,
                context_id=context_id,
            )
        if re.fullmatch(r"[0-9a-f]{64}", input_digest) is None:
            raise ValueError("input_digest must be a lowercase SHA-256 hex digest")
        lines = [
            f"# Open Radar {report_type} report",
            "",
            "<!-- Historical snapshot: do not edit; update inputs and publish a new report. -->",
            f"- Cutoff (UTC): `{iso_utc(cutoff_at)}`",
            f"- Input version: `{input_version}`",
            f"- Input digest: `{input_digest}`",
            f"- Score version: `{score_version}`",
            f"- Context: `{context_id or 'none'}`",
            f"- Prompt versions: `{', '.join(prompt_versions) or 'none'}`",
            "",
            "| Project | Radar score | Last observed (UTC) | Repositories |",
            "| --- | ---: | --- | ---: |",
        ]
        for project in project_list:
            observations_for_project = current_by_project[project.id]
            latest = max((item.observed_at for item in observations_for_project), default=None)
            card = score_map.get(project.id)
            score = f"{card.total_score:.2f}" if card and card.total_score is not None else "—"
            observed = iso_utc(latest) if latest is not None else "暂无数据"
            lines.append(f"| {project.display_name} (`{project.id}`) | {score} | {observed} | {len(project.repositories)} |")
        lines.extend(["", "## Scope", "", "Projects are listed from the fixed input set; missing observations and scores are shown explicitly.", ""])
        content = "\n".join(lines) + "\n"
        return ReportSnapshot(
            schema_version=1,
            report_id=report_id,
            report_type=report_type,
            cutoff_at=cutoff_at,
            generated_at=generated_at,
            input_version=input_version,
            input_digest=input_digest,
            score_version=score_version,
            prompt_versions=prompt_versions,
            project_ids=project_ids,
            context_id=context_id,
            content=content,
            content_sha256=_hash_content(content),
        )


class DuplicateReportError(ValueError):
    """Raised when a historical report is reused with different content."""


class ReportStore:
    """Write-once report snapshots and their human-readable Markdown files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "reports"
        self.lock_path = self.directory / ".reports.lock"

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

    def path_for(self, report_id: str) -> Path:
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            raise ValueError("report_id must be a report- slug")
        return self.directory / f"{report_id}.md"

    def metadata_path_for(self, report_id: str) -> Path:
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            raise ValueError("report_id must be a report- slug")
        return self.directory / f"{report_id}.json"

    def all(self) -> list[ReportSnapshot]:
        if not self.directory.exists():
            return []
        snapshots: list[ReportSnapshot] = []
        metadata_paths = {path.stem: path for path in self.directory.glob("report-*.json")}
        markdown_paths = {path.stem: path for path in self.directory.glob("report-*.md")}
        if set(metadata_paths) != set(markdown_paths):
            missing_metadata = sorted(set(markdown_paths) - set(metadata_paths))
            missing_markdown = sorted(set(metadata_paths) - set(markdown_paths))
            details = []
            if missing_metadata:
                details.append("missing metadata for " + ", ".join(missing_metadata))
            if missing_markdown:
                details.append("missing markdown for " + ", ".join(missing_markdown))
            raise ValueError("report store has incomplete snapshots: " + "; ".join(details))
        for path in sorted(self.directory.glob("report-*.json")):
            try:
                snapshot = ReportSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
                markdown = markdown_paths[path.stem].read_text(encoding="utf-8")
                if markdown != snapshot.content:
                    raise ValueError("Markdown content does not match metadata")
                snapshots.append(snapshot)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}: invalid report snapshot") from exc
        return snapshots

    def write(self, snapshot: ReportSnapshot) -> bool:
        if not isinstance(snapshot, ReportSnapshot):
            raise ValueError("report must be a ReportSnapshot")
        return self.write_to(snapshot, self.path_for(snapshot.report_id))

    def write_to(self, snapshot: ReportSnapshot, markdown_path: Path) -> bool:
        """Write to an explicit Markdown path while retaining the store lock."""
        if not isinstance(snapshot, ReportSnapshot):
            raise ValueError("report must be a ReportSnapshot")
        expected_markdown = Path(markdown_path)
        expected_metadata = expected_markdown.with_suffix(".json")
        expected_markdown.parent.mkdir(parents=True, exist_ok=True)
        expected_metadata.parent.mkdir(parents=True, exist_ok=True)
        markdown = snapshot.content
        metadata = json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with self._locked():
            existing_md = expected_markdown.read_text(encoding="utf-8") if expected_markdown.exists() else None
            existing_json = expected_metadata.read_text(encoding="utf-8") if expected_metadata.exists() else None
            if existing_md == markdown and existing_json == metadata:
                return False
            # A crash between the two atomic renames leaves one half. Complete
            # that half on an idempotent retry instead of making the report
            # permanently unrecoverable.
            if existing_md == markdown and existing_json is None:
                _atomic_write(expected_metadata, metadata, expected_metadata.parent)
                return True
            if existing_md is None and existing_json == metadata:
                _atomic_write(expected_markdown, markdown, expected_markdown.parent)
                return True
            if existing_md is not None or existing_json is not None:
                raise DuplicateReportError(f"report already exists: {snapshot.report_id}")
            md_fd, md_name = tempfile.mkstemp(prefix=f".{snapshot.report_id}.", suffix=".md.tmp", dir=expected_markdown.parent)
            json_fd, json_name = tempfile.mkstemp(prefix=f".{snapshot.report_id}.", suffix=".json.tmp", dir=expected_metadata.parent)
            os.close(md_fd)
            os.close(json_fd)
            temporary_md = Path(md_name)
            temporary_json = Path(json_name)
            try:
                temporary_md.write_text(markdown, encoding="utf-8")
                temporary_json.write_text(metadata, encoding="utf-8")
                temporary_md.replace(expected_markdown)
                temporary_json.replace(expected_metadata)
            except Exception:
                temporary_md.unlink(missing_ok=True)
                temporary_json.unlink(missing_ok=True)
                expected_markdown.unlink(missing_ok=True)
                expected_metadata.unlink(missing_ok=True)
                raise
            return True


def _atomic_write(path: Path, content: str, directory: Path) -> None:
    """Atomically replace one report side, used for crash recovery."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    os.close(fd)
    temporary = Path(name)
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
