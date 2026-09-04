"""Admission PR planning and human-merge reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Protocol

import yaml

from ..admission_controls import AdmissionGuard
from ..admission_request import AdmissionRequest, AuthorizationDecision, AuthorizationPolicy
from ..admission_transactions import (
    AdmissionTransaction,
    AdmissionTransactionStore,
    TransactionConflictError,
)
from ..domain import Project, ensure_utc
from ..github_webhook import VerifiedIssueEvent
from ..workflows.admission import (
    AdmissionService,
    AuthorizedCandidate,
    DuplicateRepositoryError,
    SlugCollisionError,
)


class PullRequestError(ValueError):
    """Raised when a provider returns an unsafe or mismatched pull request."""


class MergeReconciliationError(PermissionError):
    """Raised when an observed PR has not crossed the human merge gate."""


@dataclass(frozen=True)
class PullRequestRef:
    number: int
    url: str
    head_branch: str
    base_branch: str = "main"

    def __post_init__(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number <= 0:
            raise PullRequestError("pull request number must be positive")
        if not isinstance(self.url, str) or not self.url.startswith("https://"):
            raise PullRequestError("pull request url must use HTTPS")
        if not isinstance(self.head_branch, str) or not self.head_branch.startswith("admission/"):
            raise PullRequestError("pull request head branch must be in admission namespace")
        if self.base_branch != "main":
            raise PullRequestError("admission pull requests must target main")


@dataclass(frozen=True)
class MergedPullRequest:
    number: int
    head_branch: str
    merged: bool
    merge_commit_sha: str | None
    merged_by: str | None
    url: str | None = None
    project: Project | None = None
    is_bot: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number <= 0:
            raise PullRequestError("merged pull request number must be positive")
        if not isinstance(self.head_branch, str) or not self.head_branch.startswith("admission/"):
            raise PullRequestError("merged pull request branch is invalid")
        if not isinstance(self.merged, bool):
            raise PullRequestError("merged must be boolean")
        if self.merged and (
            not isinstance(self.merge_commit_sha, str) or not self.merge_commit_sha.strip()
        ):
            raise PullRequestError("a merged pull request must include merge_commit_sha")
        if self.merged_by is not None and (
            not isinstance(self.merged_by, str) or not self.merged_by.strip()
        ):
            raise PullRequestError("merged_by must be a non-empty string or null")
        if not isinstance(self.is_bot, bool):
            raise PullRequestError("is_bot must be boolean")
        if self.project is not None and not isinstance(self.project, Project):
            raise PullRequestError("merged project must be a validated Project")


@dataclass(frozen=True)
class PullRequestPlan:
    idempotency_key: str
    title: str
    body: str
    head_branch: str
    base_branch: str
    files: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.head_branch.startswith("admission/") or self.base_branch != "main":
            raise PullRequestError("admission PR branches are invalid")
        if not self.files:
            raise PullRequestError("admission PR must contain a project file")
        for path, content in self.files:
            if path != path.strip() or not path.startswith("data/projects/") or not path.endswith(".yaml"):
                raise PullRequestError(f"admission PR contains an invalid path: {path}")
            if not isinstance(content, str) or not content.strip():
                raise PullRequestError("admission PR file content must be non-empty text")


class AdmissionPRClient(Protocol):
    def find_by_branch(self, branch_name: str) -> PullRequestRef | None: ...

    def open_or_update(
        self,
        plan: PullRequestPlan,
        *,
        existing: PullRequestRef | None = None,
    ) -> PullRequestRef: ...


class PullRequestStateProvider(Protocol):
    """Read-only seam for an adapter that verifies GitHub's merged PR facts.

    Adapters must populate ``MergedPullRequest.is_bot`` from the provider's
    actor type, rather than inferring human review from a display name alone.
    """

    def get_pull_request(self, reference: PullRequestRef) -> MergedPullRequest: ...


class DeterministicAdmissionPRClient:
    """Offline-safe PR provider used until a separately-authorized GitHub adapter is wired."""

    def __init__(self) -> None:
        self._refs: dict[str, PullRequestRef] = {}

    def find_by_branch(self, branch_name: str) -> PullRequestRef | None:
        return self._refs.get(branch_name)

    def open_or_update(
        self,
        plan: PullRequestPlan,
        *,
        existing: PullRequestRef | None = None,
    ) -> PullRequestRef:
        if existing is not None and existing.head_branch != plan.head_branch:
            raise PullRequestError("existing PR branch does not match admission transaction")
        digest = hashlib.sha256(plan.idempotency_key.encode("utf-8")).hexdigest()
        number = 10_000 + (int(digest[:8], 16) % 80_000)
        reference = PullRequestRef(
            number=existing.number if existing is not None else number,
            url=existing.url if existing is not None else f"https://github.com/open-radar/admissions/pull/{number}",
            head_branch=plan.head_branch,
            base_branch=plan.base_branch,
        )
        self._refs[plan.head_branch] = reference
        return reference


@dataclass(frozen=True)
class AdmissionPreparation:
    candidate: AuthorizedCandidate
    transaction: AdmissionTransaction
    plan: PullRequestPlan
    pull_request: PullRequestRef


class AdmissionWorkflow:
    """Turn a verified Issue into one PR transaction and reconcile its human merge."""

    def __init__(
        self,
        service: AdmissionService,
        policy: AuthorizationPolicy,
        transactions: AdmissionTransactionStore,
        *,
        pr_client: AdmissionPRClient | None = None,
        guard: AdmissionGuard | None = None,
        allow_uncontrolled: bool = False,
    ) -> None:
        self.service = service
        self.policy = policy
        self.transactions = transactions
        if not isinstance(allow_uncontrolled, bool):
            raise ValueError("allow_uncontrolled must be boolean")
        if pr_client is None:
            if not allow_uncontrolled:
                raise PullRequestError(
                    "a live admission PR client is required outside offline test mode"
                )
            pr_client = DeterministicAdmissionPRClient()
        self.pr_client = pr_client
        self.guard = guard
        self.allow_uncontrolled = allow_uncontrolled

    def prepare(
        self,
        event: VerifiedIssueEvent,
        *,
        candidate_options: dict[str, object] | None = None,
    ) -> AdmissionPreparation:
        options = dict(candidate_options or {})
        try:
            if self.guard is None and not self.allow_uncontrolled:
                raise MergeReconciliationError(
                    "admission guard is required for webhook admission"
                )
            if not event.replay_managed and not self.allow_uncontrolled:
                raise MergeReconciliationError(
                    "durable replay control is required for webhook admission"
                )
            candidate = self.service.build_verified_event_candidate(
                event,
                self.policy,
                guard=self.guard,
                allow_uncontrolled=self.allow_uncontrolled,
                **options,
            )
            preparation = self._prepare_candidate(candidate)
            if not event.complete_replay(
                idempotency_key=candidate.request.idempotency_key
            ):
                raise PullRequestError("replay delivery could not be marked completed")
            return preparation
        except Exception as exc:
            try:
                if not event.fail_replay(
                    reason=str(exc)[:512] or "admission preparation failed"
                ):
                    raise PullRequestError("replay failure state was not applied")
            except Exception as state_exc:
                raise PullRequestError(
                    "admission failed and replay failure state could not be persisted"
                ) from state_exc
            raise

    def prepare_request(
        self,
        request: AdmissionRequest,
        *,
        candidate_options: dict[str, object] | None = None,
    ) -> AdmissionPreparation:
        """Prepare a locally authorized request for CLI/admin flows.

        This path still creates the same transaction and PR plan; it is not a
        direct project write and therefore cannot bypass the merge reconciler.
        """
        options = dict(candidate_options or {})
        candidate = self.service.build_authorized_candidate(
            request,
            self.policy,
            guard=self.guard,
            allow_uncontrolled=self.allow_uncontrolled,
            **options,
        )
        return self._prepare_candidate(candidate)

    def _prepare_candidate(self, candidate: AuthorizedCandidate) -> AdmissionPreparation:
        request = candidate.request
        branch = self._branch_name(request.idempotency_key)
        now = max(ensure_utc(request.created_at), datetime.now(timezone.utc))
        transaction = self.transactions.ensure(
            AdmissionTransaction(
                schema_version=1,
                idempotency_key=request.idempotency_key,
                request_id=request.request_id,
                intake_repository_id=request.intake_repository_id,
                issue_number=request.issue_number,
                project_id=candidate.project.id,
                repository_id=candidate.project.primary_repository.repository_id,
                repository_provider=candidate.project.primary_repository.provider,
                project_url=request.project_url,
                requester=request.requester,
                branch_name=branch,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
        transition_now = max(now, transaction.updated_at)
        if transaction.status in {"admitted", "merged"}:
            existing_ref = self._ref_from_transaction(transaction)
            if existing_ref is None:
                raise PullRequestError(
                    f"admission transaction {transaction.idempotency_key} has no recorded PR"
                )
            return AdmissionPreparation(candidate, transaction, self._plan(candidate, branch), existing_ref)
        if transaction.status == "rejected":
            raise PullRequestError("rejected admission transactions are terminal")
        if transaction.status == "pending":
            transaction = self.transactions.transition(
                transaction.idempotency_key, "authorized", now=transition_now
            )
        plan = self._plan(candidate, branch)
        existing_ref = self._ref_from_transaction(transaction)
        if existing_ref is not None and existing_ref.head_branch != branch:
            raise PullRequestError("recorded PR branch does not match admission transaction")
        if transaction.status in {"authorized", "failed"}:
            transaction = self.transactions.transition(
                transaction.idempotency_key, "pr_creating", now=transition_now
            )
        if existing_ref is not None and transaction.status == "pr_open":
            return AdmissionPreparation(candidate, transaction, plan, existing_ref)
        if existing_ref is None:
            finder = getattr(self.pr_client, "find_by_branch", None)
            if not callable(finder):
                raise PullRequestError(
                    "admission PR client must support find_by_branch for idempotent retries"
                )
            try:
                existing_ref = finder(branch)
            except Exception as exc:
                self.transactions.transition(
                    transaction.idempotency_key,
                    "failed",
                    now=transition_now,
                    last_error=str(exc)[:512] or "PR lookup failed",
                )
                raise
            if existing_ref is not None:
                if not isinstance(existing_ref, PullRequestRef):
                    self.transactions.transition(
                        transaction.idempotency_key,
                        "failed",
                        now=transition_now,
                        last_error="PR lookup returned an invalid reference",
                    )
                    raise PullRequestError("PR lookup returned an invalid reference")
                if existing_ref.head_branch != branch:
                    raise PullRequestError("found PR branch does not match admission transaction")
                transaction = self.transactions.transition(
                    transaction.idempotency_key,
                    "pr_open",
                    now=transition_now,
                    pr_number=existing_ref.number,
                    pr_url=existing_ref.url,
                )
                return AdmissionPreparation(candidate, transaction, plan, existing_ref)
        try:
            pull_request = self.pr_client.open_or_update(plan, existing=existing_ref)
            if pull_request.head_branch != branch:
                raise PullRequestError(
                    "PR provider returned a branch outside the admission transaction"
                )
        except Exception as exc:
            self.transactions.transition(
                transaction.idempotency_key,
                "failed",
                now=transition_now,
                last_error=str(exc)[:512] or "PR provider failed",
            )
            raise
        if transaction.status == "pr_creating":
            transaction = self.transactions.transition(
                transaction.idempotency_key,
                "pr_open",
                now=transition_now,
                pr_number=pull_request.number,
                pr_url=pull_request.url,
            )
        elif transaction.pr_number != pull_request.number or transaction.pr_url != pull_request.url:
            raise TransactionConflictError("PR identity changed for an existing admission transaction")
        return AdmissionPreparation(candidate, transaction, plan, pull_request)

    def reconcile_merge_by_key(
        self,
        idempotency_key: str,
        provider: PullRequestStateProvider,
        *,
        now: datetime | None = None,
    ) -> Path:
        """Recover a merge by querying the authoritative PR state provider."""
        transaction = self.transactions.get(idempotency_key)
        if transaction is None:
            raise MergeReconciliationError("admission transaction is missing")
        if transaction.pr_number is None or transaction.pr_url is None:
            raise MergeReconciliationError("admission transaction has no recorded PR")
        reference = self._ref_from_transaction(transaction)
        assert reference is not None
        try:
            merged_pr = provider.get_pull_request(reference)
        except Exception as exc:
            raise MergeReconciliationError("unable to verify pull request state") from exc
        if not isinstance(merged_pr, MergedPullRequest):
            raise MergeReconciliationError("pull request provider returned an invalid state")
        self._validate_merge_observation(transaction, merged_pr)
        if transaction.status == "admitted":
            path = self.service.projects.directory / f"{transaction.project_id}.yaml"
            if not path.is_file():
                raise MergeReconciliationError("admission transaction is admitted but project file is missing")
            return path
        if merged_pr.project is None:
            raise MergeReconciliationError(
                "authoritative merged project content is required for reconciliation"
            )
        request = AdmissionRequest.from_dict(
            {
                "schema_version": 1,
                "request_id": transaction.request_id,
                "intake_repository_id": transaction.intake_repository_id,
                "issue_number": transaction.issue_number,
                "project_url": transaction.project_url,
                "requester": transaction.requester,
                "labels": [],
                "created_at": transaction.created_at.isoformat().replace("+00:00", "Z"),
                "source_url": None,
                "comment": None,
            }
        )
        project = merged_pr.project
        candidate = AuthorizedCandidate(
            project=project,
            request=request,
            decision=AuthorizationDecision(status="authorized", reason="trusted_user"),
        )
        if (
            candidate.project.primary_repository.provider != transaction.repository_provider
            or candidate.project.primary_repository.repository_id != transaction.repository_id
        ):
            raise MergeReconciliationError("reconciled repository identity changed")
        plan = self._plan(candidate, transaction.branch_name)
        preparation = AdmissionPreparation(
            candidate=candidate,
            transaction=transaction,
            plan=plan,
            pull_request=PullRequestRef(
                number=transaction.pr_number,
                url=transaction.pr_url,
                head_branch=transaction.branch_name,
            ),
        )
        return self._reconcile_merge(preparation, merged_pr, now=now)

    def reconcile_merge_from_provider(
        self,
        preparation: AdmissionPreparation,
        provider: PullRequestStateProvider,
        *,
        now: datetime | None = None,
    ) -> Path:
        """Fetch authoritative merge facts before applying the catalog gate."""
        try:
            merged_pr = provider.get_pull_request(preparation.pull_request)
        except Exception as exc:
            raise MergeReconciliationError("unable to verify pull request state") from exc
        if not isinstance(merged_pr, MergedPullRequest):
            raise MergeReconciliationError("pull request provider returned an invalid state")
        return self._reconcile_merge(preparation, merged_pr, now=now)

    def reconcile_merge(
        self,
        preparation: AdmissionPreparation,
        merged_pr: MergedPullRequest,
        *,
        now: datetime | None = None,
    ) -> Path:
        """Reject unverified caller-supplied merge facts.

        Use ``reconcile_merge_from_provider`` or ``reconcile_merge_by_key`` so
        the state object is obtained from the read-only provider seam.
        """
        raise MergeReconciliationError(
            "merge reconciliation requires an authoritative pull-request provider"
        )

    def _reconcile_merge(
        self,
        preparation: AdmissionPreparation,
        merged_pr: MergedPullRequest,
        *,
        now: datetime | None = None,
    ) -> Path:
        transaction = self.transactions.get(preparation.transaction.idempotency_key)
        if transaction is None:
            raise MergeReconciliationError("admission transaction is missing")
        self._validate_preparation_identity(preparation, transaction)
        self._validate_merge_observation(transaction, merged_pr)
        if transaction.status == "admitted":
            path = self._project_path(preparation.candidate.project)
            if not path.is_file():
                raise MergeReconciliationError("admission transaction is admitted but project file is missing")
            return path
        if merged_pr.project is None:
            raise MergeReconciliationError(
                "authoritative merged project content is required for reconciliation"
            )
        if (
            merged_pr.project.id != transaction.project_id
            or merged_pr.project.primary_repository.provider
            != transaction.repository_provider
            or merged_pr.project.primary_repository.repository_id
            != transaction.repository_id
        ):
            raise MergeReconciliationError(
                "merged project identity does not match admission transaction"
            )
        candidate = AuthorizedCandidate(
            project=merged_pr.project,
            request=preparation.candidate.request,
            decision=preparation.candidate.decision,
        )
        merged_at = ensure_utc(now or datetime.now(timezone.utc))
        transaction = self.transactions.transition(
            transaction.idempotency_key,
            "merged",
            now=merged_at,
            merge_commit_sha=merged_pr.merge_commit_sha,
            merged_by=merged_pr.merged_by,
        )
        try:
            path = self.service.admit(
                candidate,
                merge_confirmed=True,
                merge_proof=self.service._merge_gate_token,
            )
        except DuplicateRepositoryError:
            existing = self.service.projects.find_by_repository(
                candidate.project.primary_repository.provider,
                candidate.project.primary_repository.repository_id,
            )
            if (
                existing is None
                or existing.id != candidate.project.id
                or existing.to_dict() != candidate.project.to_dict()
            ):
                raise
            path = self._project_path(existing)
        except SlugCollisionError:
            try:
                existing = self.service.projects.load(candidate.project.id)
            except FileNotFoundError:
                raise
            if existing.to_dict() != candidate.project.to_dict():
                raise
            path = self._project_path(existing)
        self.transactions.transition(
            transaction.idempotency_key,
            "admitted",
            now=merged_at,
        )
        return path

    @staticmethod
    def _branch_name(idempotency_key: str) -> str:
        safe = "".join(char if char.isalnum() else "-" for char in idempotency_key.lower()).strip("-")
        return f"admission/{safe[:180]}"

    @staticmethod
    def _plan(candidate: AuthorizedCandidate, branch: str) -> PullRequestPlan:
        project = candidate.project
        content = yaml.safe_dump(
            project.to_dict(),
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        return PullRequestPlan(
            idempotency_key=candidate.request.idempotency_key,
            title=f"admit {project.id}",
            body=(
                "Automated admission proposal. Human review and merge are required before "
                f"catalog persistence. Request: {candidate.request.request_id}."
            ),
            head_branch=branch,
            base_branch="main",
            files=((f"data/projects/{project.id}.yaml", content),),
        )

    @staticmethod
    def _ref_from_transaction(transaction: AdmissionTransaction) -> PullRequestRef | None:
        if transaction.pr_number is None or transaction.pr_url is None:
            return None
        return PullRequestRef(
            number=transaction.pr_number,
            url=transaction.pr_url,
            head_branch=transaction.branch_name,
        )

    def _project_path(self, project: Project) -> Path:
        return self.service.projects.directory / f"{project.id}.yaml"

    @staticmethod
    def _validate_merge_observation(
        transaction: AdmissionTransaction,
        merged_pr: MergedPullRequest,
    ) -> None:
        if not merged_pr.merged:
            raise MergeReconciliationError("admission PR is not merged by a human")
        if transaction.pr_number != merged_pr.number:
            raise MergeReconciliationError("merged PR number does not match admission transaction")
        if transaction.branch_name != merged_pr.head_branch:
            raise MergeReconciliationError("merged PR branch does not match admission transaction")
        if merged_pr.url is not None and transaction.pr_url != merged_pr.url:
            raise MergeReconciliationError("merged PR URL does not match admission transaction")
        if not isinstance(merged_pr.merged_by, str) or not merged_pr.merged_by.strip():
            raise MergeReconciliationError("a human merger identity is required")
        actor = merged_pr.merged_by.strip()
        normalized_actor = actor.lower()
        known_bot_names = {
            "dependabot",
            "renovate",
            "bot",
            "github-actions",
            "github-actions[bot]",
        }
        if (
            merged_pr.is_bot
            or normalized_actor.endswith("[bot]")
            or normalized_actor in known_bot_names
            or normalized_actor.endswith("-bot")
            or normalized_actor.endswith("_bot")
        ):
            raise MergeReconciliationError("automated actors cannot cross the human merge gate")
        if transaction.status in {"merged", "admitted"}:
            if transaction.merge_commit_sha != merged_pr.merge_commit_sha:
                raise MergeReconciliationError("merge commit identity changed")
            if transaction.merged_by != merged_pr.merged_by.strip():
                raise MergeReconciliationError("merge actor identity changed")

    @staticmethod
    def _validate_preparation_identity(
        preparation: AdmissionPreparation,
        transaction: AdmissionTransaction,
    ) -> None:
        candidate = preparation.candidate
        request = candidate.request
        if request.idempotency_key != transaction.idempotency_key:
            raise MergeReconciliationError("candidate idempotency key does not match transaction")
        for name in (
            "request_id",
            "intake_repository_id",
            "issue_number",
            "project_url",
            "requester",
        ):
            if getattr(request, name) != getattr(transaction, name):
                raise MergeReconciliationError(f"candidate request identity changed: {name}")
        if candidate.project.id != transaction.project_id:
            raise MergeReconciliationError("candidate project identity changed")
        if (
            candidate.project.primary_repository.provider != transaction.repository_provider
            or candidate.project.primary_repository.repository_id != transaction.repository_id
        ):
            raise MergeReconciliationError("candidate repository identity changed")
        if preparation.plan.idempotency_key != transaction.idempotency_key:
            raise MergeReconciliationError("PR plan idempotency key does not match transaction")
        if preparation.plan.head_branch != transaction.branch_name:
            raise MergeReconciliationError("PR plan branch does not match transaction")
        if preparation.pull_request.number != transaction.pr_number or (
            preparation.pull_request.url != transaction.pr_url
        ):
            raise MergeReconciliationError("PR reference does not match transaction")
