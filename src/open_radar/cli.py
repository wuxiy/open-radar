"""Thin command-line orchestration for Open Radar."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

import yaml

from .contracts.schema import SchemaValidator
from .admission_request import (
    AdmissionAuthorizationError,
    AdmissionRequest,
    AuthorizationPolicy,
)
from .admission_controls import (
    AdmissionGuard,
    DurableRateBudgetController,
    DurableReplayStore,
    RateBudgetExceeded,
    RateBudgetPolicy,
)
from .admission_transactions import AdmissionTransactionError, AdmissionTransactionStore
from .change_detection import ChangeDetector, ChangeEventStore
from .github_provider import GitHubApiClient, GitHubProvider, GitHubProviderError
from .generation import render_readme, write_readme
from .storage import ObservationStore, ProjectStore
from .taxonomy import Taxonomy
from .workflows.admission import (
    AdmissionMergeGateError,
    AdmissionService,
    AuthorizedCandidate,
    DuplicateRepositoryError,
    SlugCollisionError,
)
from .workflows.admission_pr import (
    AdmissionWorkflow,
    MergeReconciliationError,
    PullRequestError,
)
from .workflows.collection import CollectionService


def _timestamp(value: str | None) -> datetime:
    parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return parsed.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_id() -> str:
    return f"run-{uuid.uuid4().hex[:16]}"


def _positive_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _write_manifest(
    root: Path,
    *,
    run_id: str,
    kind: str,
    started_at: datetime,
    status: str,
    counts: dict[str, int],
    errors: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    destination = root / "data" / "runs" / f"{started_at:%Y-%m}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "kind": kind,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": _now().isoformat().replace("+00:00", "Z"),
        "status": status,
        "counts": counts,
    }
    if errors:
        payload["errors"] = errors
    if metadata:
        payload["metadata"] = metadata
    with destination.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _root(namespace: argparse.Namespace) -> Path:
    return Path(namespace.root).resolve()


def _provider(namespace: argparse.Namespace) -> GitHubProvider:
    return GitHubProvider(
        GitHubApiClient(token=namespace.token or os.environ.get("GITHUB_TOKEN"))
    )


def _ingest(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    request: AdmissionRequest | None = None
    try:
        tags = tuple(tag.strip() for tag in namespace.tags.split(",") if tag.strip())
        service = AdmissionService(_provider(namespace), ProjectStore(root), Taxonomy.load(root))
        if bool(namespace.request_id) != bool(namespace.requester):
            raise ValueError("--request-id and --requester must be provided together")
        if namespace.write and not namespace.request_id:
            raise ValueError("--write requires an authorized --request-id and --requester")
        candidate_options = {
            "project_id": namespace.project_id,
            "primary_category": namespace.primary_category,
            "tags": tags,
            "tracking": namespace.tracking,
            "research_stage": namespace.research_stage,
            "decision": namespace.decision,
        }
        if namespace.request_id:
            request = AdmissionRequest.from_dict(
                {
                    "schema_version": 1,
                    "request_id": namespace.request_id,
                    "intake_repository_id": namespace.intake_repository_id,
                    "issue_number": namespace.issue_number,
                    "project_url": namespace.url,
                    "requester": namespace.requester,
                    "labels": [],
                    "created_at": namespace.discovered_at
                    or started.isoformat().replace("+00:00", "Z"),
                    "source_url": namespace.source_url,
                    "comment": namespace.comment,
                }
            )
            SchemaValidator(root).validate("admission-request.v1.json", request.to_dict())
            trusted_users = {
                user.strip()
                for user in os.environ.get("OPEN_RADAR_TRUSTED_USERS", "").split(",")
                if user.strip()
            }
            policy = AuthorizationPolicy(trusted_users=trusted_users)
            if namespace.write:
                rate_budget = DurableRateBudgetController(
                    root,
                    RateBudgetPolicy(
                        max_requests=_positive_env("OPEN_RADAR_ADMISSION_MAX_REQUESTS", 60),
                        max_budget_units=_positive_env("OPEN_RADAR_ADMISSION_BUDGET_UNITS", 100),
                        window_seconds=_positive_env("OPEN_RADAR_ADMISSION_WINDOW_SECONDS", 3600),
                    ),
                )
                workflow = AdmissionWorkflow(
                    service,
                    policy,
                    AdmissionTransactionStore(root),
                    guard=AdmissionGuard(policy, rate_budget),
                )
                preparation = workflow.prepare_request(
                    request,
                    candidate_options=candidate_options,
                )
                candidate = preparation.candidate
            else:
                candidate = service.build_authorized_candidate(
                    request,
                    policy,
                    allow_uncontrolled=True,
                    **candidate_options,
                )
        else:
            candidate = service.build_candidate(
                namespace.url,
                discovered_at=_timestamp(namespace.discovered_at) if namespace.discovered_at else started,
                **candidate_options,
            )
        if namespace.write:
            if not isinstance(candidate, AuthorizedCandidate):
                raise AdmissionAuthorizationError(
                    "only an authorized request can be written"
                )
            if not namespace.merge_confirmed:
                raise AdmissionMergeGateError(
                    "admission PR is prepared; pass --merge-confirmed after human review"
                )
            if not namespace.merge_commit_sha or not namespace.merged_by:
                raise ValueError(
                    "--merge-confirmed requires --merge-commit-sha and --merged-by"
                )
            raise MergeReconciliationError(
                "CLI cannot self-assert a merge; use reconcile_merge_from_provider with "
                "authoritative pull-request state"
            )
        else:
            project = candidate.project if isinstance(candidate, AuthorizedCandidate) else candidate
            print(yaml.safe_dump(project.to_dict(), allow_unicode=True, sort_keys=False), end="")
            count = 0
        metadata = _request_metadata(request)
        _write_manifest(
            root,
            run_id=run_id,
            kind="ingest",
            started_at=started,
            status="succeeded",
            counts={"admitted": count},
            metadata=metadata,
        )
        return 0
    except AdmissionAuthorizationError as exc:
        print(f"ingest pending: {exc}", file=sys.stderr)
        _write_manifest(
            root,
            run_id=run_id,
            kind="ingest",
            started_at=started,
            status="pending",
            counts={},
            errors=[str(exc)],
            metadata=_request_metadata(request),
        )
        return 1
    except (
        AdmissionMergeGateError,
        ValueError,
        FileNotFoundError,
        DuplicateRepositoryError,
        SlugCollisionError,
        AdmissionTransactionError,
        MergeReconciliationError,
        PullRequestError,
        RateBudgetExceeded,
        GitHubProviderError,
    ) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        _write_manifest(
            root,
            run_id=run_id,
            kind="ingest",
            started_at=started,
            status="failed",
            counts={},
            errors=[str(exc)],
            metadata=_request_metadata(request),
        )
        return 1


def _request_metadata(request: AdmissionRequest | None) -> dict[str, object] | None:
    if request is None:
        return None
    comment_preview = request.comment[:512] if request.comment is not None else None
    return {
        "request_id": request.request_id,
        "intake_repository_id": request.intake_repository_id,
        "issue_number": request.issue_number,
        "requester": request.requester,
        "source_url": request.source_url,
        "comment_preview": comment_preview,
        "comment_truncated": request.comment is not None and len(request.comment) > 512,
    }


def _collect(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = namespace.run_id or _run_id()
    try:
        service = CollectionService(
            _provider(namespace), ProjectStore(root), ObservationStore(root)
        )
        count = service.collect_all(
            run_id=run_id,
            scheduled_at=_timestamp(namespace.scheduled_at) if namespace.scheduled_at else started,
        )
        errors = service.last_errors
        print(f"appended observations: {count}")
        if errors:
            for error in errors:
                print(f"collect warning: {error}", file=sys.stderr)
        status = "partial" if errors and count else "failed" if errors else "succeeded"
        _write_manifest(root, run_id=run_id, kind="collect", started_at=started, status=status, counts={"observations_appended": count, "projects_skipped": len(service.last_skipped), "errors": len(errors)}, errors=errors)
        return 1 if errors and not count else 0
    except (ValueError, FileNotFoundError, RuntimeError, GitHubProviderError) as exc:
        print(f"collect failed: {exc}", file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="collect", started_at=started, status="failed", counts={}, errors=[str(exc)])
        return 1


def _detect_changes(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        observations = ObservationStore(root).all()
        detected = ChangeDetector().detect(
            observations,
            detected_at=started,
            project_id=namespace.project_id,
        )
        appended = ChangeEventStore(root).append_many(detected)
        print(f"change events detected: {len(detected)}")
        print(f"change events appended: {appended}")
        _write_manifest(
            root,
            run_id=run_id,
            kind="detect-changes",
            started_at=started,
            status="succeeded",
            counts={
                "events_detected": len(detected),
                "events_appended": appended,
            },
            metadata={"project_id": namespace.project_id} if namespace.project_id else None,
        )
        return 0
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"detect-changes failed: {exc}", file=sys.stderr)
        _write_manifest(
            root,
            run_id=run_id,
            kind="detect-changes",
            started_at=started,
            status="failed",
            counts={},
            errors=[str(exc)],
        )
        return 1


def _generate(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        projects = ProjectStore(root)
        observations = ObservationStore(root)
        destination = Path(namespace.output)
        if not destination.is_absolute():
            destination = root / destination
        template_path = root / "templates" / "README.md.j2"
        if not template_path.is_file():
            template_path = None
        write_readme(
            destination,
            render_readme(projects.all(), observations, template_path=template_path),
            force=namespace.force,
        )
        print(destination)
        _write_manifest(root, run_id=run_id, kind="generate", started_at=started, status="succeeded", counts={"projects": len(projects.all())})
        return 0
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"generate failed: {exc}", file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="generate", started_at=started, status="failed", counts={}, errors=[str(exc)])
        return 1


def _validate(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    errors: list[str] = []
    validator = SchemaValidator(root)
    try:
        taxonomy = Taxonomy.load(root)
        project_store = ProjectStore(root)
        observation_store = ObservationStore(root)
        projects = project_store.all()
        project_by_id = {project.id: project for project in projects}
        repository_owners: dict[tuple[str, int], str] = {}
        for project in projects:
            try:
                validator.validate_project(project.to_dict())
                taxonomy.validate_project(project)
                for repository in project.repositories:
                    key = (repository.provider, repository.repository_id)
                    previous = repository_owners.get(key)
                    if previous is not None and previous != project.id:
                        raise ValueError(
                            f"repository identity is used by projects {previous} and {project.id}: {key}"
                        )
                    repository_owners[key] = project.id
            except ValueError as exc:
                errors.append(f"project {project.id}: {exc}")
        observations = observation_store.all()
        errors.extend(f"observation integrity: {error}" for error in observation_store.integrity_errors())
        for observation in observations:
            try:
                validator.validate_observation(observation.to_dict())
                project = project_by_id.get(observation.project_id)
                if project is None:
                    raise ValueError(f"observation references unknown project: {observation.project_id}")
                if not any(
                    repository.provider == observation.provider
                    and repository.repository_id == observation.repository_id
                    for repository in project.repositories
                ):
                    raise ValueError(
                        "observation repository is not registered on its project: "
                        f"{observation.provider}:{observation.repository_id}"
                    )
            except ValueError as exc:
                errors.append(f"observation {observation.event_id}: {exc}")
        try:
            change_store = ChangeEventStore(root)
            for event in change_store.all():
                try:
                    validator.validate("change-event.v1.json", event.to_dict())
                    project = project_by_id.get(event.project_id)
                    if project is None:
                        raise ValueError(f"change event references unknown project: {event.project_id}")
                    if not any(
                        repository.provider == event.provider
                        and repository.repository_id == event.repository_id
                        for repository in project.repositories
                    ):
                        raise ValueError(
                            "change event repository is not registered on its project: "
                            f"{event.provider}:{event.repository_id}"
                        )
                except ValueError as exc:
                    errors.append(f"change event {event.change_id}: {exc}")
        except (ValueError, FileNotFoundError) as exc:
            errors.append(f"change event ledger: {exc}")
        seen_run_ids: set[str] = set()
        for manifest_path in sorted((root / "data" / "runs").glob("*.jsonl")):
            if re.fullmatch(r"(?:19|20)[0-9]{2}-(?:0[1-9]|1[0-2])\.jsonl", manifest_path.name) is None:
                continue
            for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    manifest = json.loads(line)
                    validator.validate("run-manifest.v1.json", manifest)
                    if manifest["run_id"] in seen_run_ids:
                        raise ValueError(f"duplicate run_id: {manifest['run_id']}")
                    seen_run_ids.add(manifest["run_id"])
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"run manifest {manifest_path}:{line_number}: {exc}")
        try:
            transaction_store = AdmissionTransactionStore(root)
            for transaction in transaction_store.all():
                validator.validate("admission-transaction.v1.json", transaction.to_dict())
        except (AdmissionTransactionError, ValueError, FileNotFoundError) as exc:
            errors.append(f"admission transaction: {exc}")
        try:
            DurableReplayStore(root)._records()
        except (ValueError, OSError) as exc:
            errors.append(f"replay ledger: {exc}")
        try:
            DurableRateBudgetController(
                root,
                RateBudgetPolicy(
                    max_requests=_positive_env("OPEN_RADAR_ADMISSION_MAX_REQUESTS", 60),
                    max_budget_units=_positive_env("OPEN_RADAR_ADMISSION_BUDGET_UNITS", 100),
                    window_seconds=_positive_env("OPEN_RADAR_ADMISSION_WINDOW_SECONDS", 3600),
                ),
            )._records()
        except (ValueError, OSError) as exc:
            errors.append(f"rate/budget ledger: {exc}")
    except (ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="validate", started_at=started, status="failed", counts={"errors": len(errors)}, errors=errors)
        return 1
    print("validation ok")
    _write_manifest(root, run_id=run_id, kind="validate", started_at=started, status="succeeded", counts={"errors": 0})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open-radar")
    parser.add_argument("--root", default=".", help="repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="build or admit a GitHub project candidate")
    ingest.add_argument("url")
    ingest.add_argument("--root", default=argparse.SUPPRESS)
    ingest.add_argument("--token", default=None)
    ingest.add_argument("--write", action="store_true")
    ingest.add_argument("--project-id")
    ingest.add_argument("--primary-category", default="uncategorized")
    ingest.add_argument("--tags", default="")
    ingest.add_argument("--tracking", choices=["daily", "weekly", "monthly", "off"], default="weekly")
    ingest.add_argument("--research-stage", choices=["watching", "researching", "evaluated"], default="watching")
    ingest.add_argument("--decision", choices=["undecided", "adopt", "reference", "reject"], default="undecided")
    ingest.add_argument("--discovered-at")
    ingest.add_argument("--request-id")
    ingest.add_argument("--requester")
    ingest.add_argument("--intake-repository-id")
    ingest.add_argument("--issue-number", type=int)
    ingest.add_argument("--merge-confirmed", action="store_true")
    ingest.add_argument("--pr-number", type=int)
    ingest.add_argument("--merge-commit-sha")
    ingest.add_argument("--merged-by")
    ingest.add_argument("--source-url")
    ingest.add_argument("--comment")
    ingest.set_defaults(handler=_ingest)

    collect = subparsers.add_parser("collect", help="collect tracking-enabled GitHub observations")
    collect.add_argument("--root", default=argparse.SUPPRESS)
    collect.add_argument("--token", default=None)
    collect.add_argument("--run-id")
    collect.add_argument("--scheduled-at")
    collect.set_defaults(handler=_collect)

    detect_changes = subparsers.add_parser(
        "detect-changes", help="derive deterministic change events from observations"
    )
    detect_changes.add_argument("--root", default=argparse.SUPPRESS)
    detect_changes.add_argument("--project-id")
    detect_changes.set_defaults(handler=_detect_changes)

    generate = subparsers.add_parser("generate", help="render the deterministic README")
    generate.add_argument("--root", default=argparse.SUPPRESS)
    generate.add_argument("--output", default="README.md")
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(handler=_generate)

    validate = subparsers.add_parser("validate", help="validate projects, observations, and taxonomy")
    validate.add_argument("--root", default=argparse.SUPPRESS)
    validate.set_defaults(handler=_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    return namespace.handler(namespace)


if __name__ == "__main__":
    raise SystemExit(main())
