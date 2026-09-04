"""Candidate admission workflow: resolve, validate, deduplicate, then persist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..domain import Project, iso_utc
from ..github_provider import GitHubProvider
from ..github_webhook import VerifiedIssueEvent
from ..identity import project_slug
from ..storage import ProjectStore
from ..taxonomy import Taxonomy
from ..admission_request import (
    AdmissionAuthorizationError,
    AdmissionRequest,
    AuthorizationDecision,
    AuthorizationPolicy,
)


class DuplicateRepositoryError(ValueError):
    """The external repository is already represented by another project."""


class SlugCollisionError(ValueError):
    """A readable project slug is already used for a different repository."""


class AdmissionMergeGateError(PermissionError):
    """Raised when a candidate has not crossed the human merge gate."""


@dataclass(frozen=True)
class AuthorizedCandidate:
    """Candidate carrying the authorization decision that produced it."""

    project: Project
    request: AdmissionRequest
    decision: AuthorizationDecision


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

    def admit(self, candidate: AuthorizedCandidate, *, merge_confirmed: bool = False) -> Path:
        if not isinstance(candidate, AuthorizedCandidate):
            raise AdmissionAuthorizationError(
                "only an authorized candidate can be admitted"
            )
        if not candidate.decision.authorized:
            raise AdmissionAuthorizationError(
                f"admission request {candidate.request.request_id} is pending authorization"
            )
        if not merge_confirmed:
            raise AdmissionMergeGateError(
                "candidate must be confirmed as merged before entering the catalog"
            )
        return self._persist(candidate.project)

    def _persist(self, candidate: Project) -> Path:
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

    def build_authorized_candidate(
        self,
        request: AdmissionRequest,
        policy: AuthorizationPolicy,
        **candidate_options,
    ) -> AuthorizedCandidate:
        decision = policy.require_authorized(request)
        return self._authorized_candidate(
            request,
            decision,
            **candidate_options,
        )

    def build_verified_event_candidate(
        self,
        event: VerifiedIssueEvent,
        policy: AuthorizationPolicy,
        **candidate_options,
    ) -> AuthorizedCandidate:
        """Consume a verifier result without allowing event fields to be re-bound."""
        if not event.is_verified():
            raise AdmissionAuthorizationError(
                "admission events must pass GitHub webhook verification"
            )
        decision = policy.require_authorized_event(
            event.request,
            actor=event.sender,
            action=event.action,
            label=event.label_name,
        )
        return self._authorized_candidate(
            event.request,
            decision,
            **candidate_options,
        )

    def _authorized_candidate(
        self,
        request: AdmissionRequest,
        authorization: AuthorizationDecision,
        **candidate_options,
    ) -> AuthorizedCandidate:
        return AuthorizedCandidate(
            project=self.build_candidate(
                request.project_url,
                discovered_at=request.created_at,
                **candidate_options,
            ),
            request=request,
            decision=authorization,
        )
