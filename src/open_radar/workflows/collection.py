"""Scheduled observation collection workflow."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from ..domain import Project, ensure_utc
from ..github_provider import GitHubProvider
from ..identity import GitHubRepositoryIdentity
from ..storage import ObservationStore, ProjectStore


class CollectionService:
    def __init__(
        self,
        provider: GitHubProvider,
        projects: ProjectStore,
        observations: ObservationStore,
    ) -> None:
        self.provider = provider
        self.projects = projects
        self.observations = observations
        self.last_errors: list[str] = []
        self.last_skipped: list[str] = []

    def collect_all(
        self,
        *,
        run_id: str,
        scheduled_at: datetime,
        observed_at: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> int:
        scheduled_at = ensure_utc(scheduled_at)
        observed_at = ensure_utc(observed_at or scheduled_at)
        recorded_at = ensure_utc(recorded_at or observed_at)
        self.last_errors = []
        self.last_skipped = []
        records = []
        for project in self.projects.all():
            if project.tracking == "off":
                continue
            if not self._due(project, scheduled_at):
                self.last_skipped.append(project.id)
                continue
            try:
                primary = project.primary_repository
                identity = GitHubRepositoryIdentity(owner=primary.owner, repo=primary.repo)
                metadata = self.provider.fetch_repository(identity)
                if metadata.repository_id != primary.repository_id:
                    raise ValueError(
                        f"provider repository id mismatch for {project.id}: "
                        f"expected {primary.repository_id}, got {metadata.repository_id}"
                    )
                records.append(
                    self.provider.to_observation(
                        project.id,
                        metadata,
                        run_id=run_id,
                        scheduled_at=scheduled_at,
                        observed_at=observed_at,
                        recorded_at=recorded_at,
                    )
                )
            except (RuntimeError, ValueError, StopIteration) as exc:
                self.last_errors.append(f"{project.id}: {exc}")
        return self.observations.append_batch(records)

    def _due(self, project: Project, scheduled_at: datetime) -> bool:
        latest = self.observations.current_for(project.id)
        if not latest:
            return True
        interval_days = {"daily": 1, "weekly": 7, "monthly": 30}[project.tracking]
        primary = project.primary_repository
        primary_latest = next(
            (
                record
                for record in latest
                if record.provider == primary.provider
                and record.repository_id == primary.repository_id
            ),
            None,
        )
        if primary_latest is None:
            return True
        return primary_latest.observed_at + timedelta(days=interval_days) <= scheduled_at
