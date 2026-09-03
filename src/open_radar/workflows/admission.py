"""Candidate admission workflow: resolve, validate, deduplicate, then persist."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..domain import Project, iso_utc
from ..github_provider import GitHubProvider
from ..identity import project_slug
from ..storage import ProjectStore
from ..taxonomy import Taxonomy


class DuplicateRepositoryError(ValueError):
    """The external repository is already represented by another project."""


class SlugCollisionError(ValueError):
    """A readable project slug is already used for a different repository."""


class AdmissionService:
    def __init__(
        self,
        provider: GitHubProvider,
        projects: ProjectStore,
        taxonomy: Taxonomy | None = None,
    ) -> None:
        self.provider = provider
        self.projects = projects
        self.taxonomy = taxonomy

    def build_candidate(
        self,
        url: str,
        *,
        discovered_at: datetime,
        project_id: str | None = None,
        primary_category: str = "uncategorized",
        tags: tuple[str, ...] = (),
        tracking: str = "weekly",
        research_stage: str = "watching",
        decision: str = "undecided",
    ) -> Project:
        identity = self.provider.resolve(url)
        metadata = self.provider.fetch_repository(identity)
        identifier = project_id or project_slug(metadata.name)
        candidate = Project.from_dict(
            {
                "schema_version": 1,
                "id": identifier,
                "display_name": metadata.name,
                "aliases": [],
                "repositories": [
                    {
                        "provider": "github",
                        "repository_id": metadata.repository_id,
                        "owner": identity.owner,
                        "repo": identity.repo,
                        "role": "primary",
                    }
                ],
                "primary_category": primary_category,
                "tags": list(tags),
                "discovery_sources": [
                    {
                        "type": "manual",
                        "url": url.strip(),
                        "discovered_at": iso_utc(discovered_at),
                    }
                ],
                "research_stage": research_stage,
                "decision": decision,
                "tracking": tracking,
            }
        )
        if self.taxonomy is not None:
            self.taxonomy.validate_project(candidate)
        return candidate

    def admit(self, candidate: Project) -> Path:
        with self.projects.locked():
            duplicate = self.projects.find_by_repository(
                "github", candidate.repositories[0].repository_id
            )
            if duplicate is not None:
                raise DuplicateRepositoryError(
                    f"repository is already represented by project {duplicate.id}"
                )
            try:
                existing = self.projects.load(candidate.id)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                raise SlugCollisionError(f"project id is already in use: {candidate.id}")
            return self.projects.save(candidate)
