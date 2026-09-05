"""Scheduled observation collection workflow."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from ..domain import ObservationRecord, Project, RepositoryRef, ensure_utc
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
        project_id: str | None = None,
    ) -> int:
        scheduled_at = ensure_utc(scheduled_at)
        observed_at = ensure_utc(observed_at or scheduled_at)
        recorded_at = ensure_utc(recorded_at or observed_at)
        self.last_errors = []
        self.last_skipped = []
        records = []
        projects = self.projects.all()
        if project_id is not None:
            projects = [project for project in projects if project.id == project_id]
            if not projects:
                raise ValueError(f"project does not exist: {project_id}")
        for project in projects:
            if project.tracking == "off":
                continue
            latest = self.observations.current_for(project.id)
            due_repositories = [
                repository
                for repository in project.repositories
                if self._due(project, repository, scheduled_at, latest=latest)
            ]
            if not due_repositories:
                self.last_skipped.append(project.id)
                continue
            for repository in due_repositories:
                try:
                    identity = GitHubRepositoryIdentity(
                        owner=repository.owner, repo=repository.repo
                    )
                    metadata = self.provider.fetch_repository(identity)
                    if metadata.repository_id != repository.repository_id:
                        raise ValueError(
                            f"provider repository id mismatch for {project.id}: "
                            f"expected {repository.repository_id}, got {metadata.repository_id}"
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
                    scope = project.id
                    if repository.role != "primary":
                        scope += f" ({repository.provider}:{repository.repository_id})"
                    self.last_errors.append(f"{scope}: {exc}")
        return self.observations.append_batch(records)

    def _due(
        self,
        project: Project,
        repository: RepositoryRef,
        scheduled_at: datetime,
        *,
        latest: list[ObservationRecord] | None = None,
    ) -> bool:
        latest = latest if latest is not None else self.observations.current_for(project.id)
        if not latest:
            return True
        interval_days = {"daily": 1, "weekly": 7, "monthly": 30}[project.tracking]
        repository_latest = next(
            (
                record
                for record in latest
                if record.provider == repository.provider
                and record.repository_id == repository.repository_id
            ),
            None,
        )
        if repository_latest is None:
            return True
        return repository_latest.observed_at + timedelta(days=interval_days) <= scheduled_at
