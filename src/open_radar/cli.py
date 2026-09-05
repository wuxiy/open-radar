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
from .reporting import DuplicateReportError, ReportRenderer, ReportStore
from .research import ResearchEvidenceStore, build_analysis_proposals
from .run_manifests import RunManifestStore
from .scoring import ContextStore, ScoreEngine
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


class RunManifestError(RuntimeError):
    """Raised when a command cannot durably record its run outcome."""


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
) -> bool:
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
    try:
        return RunManifestStore(root).append(payload)
    except (OSError, ValueError) as exc:
        raise RunManifestError(f"unable to record run manifest: {exc}") from exc


def _root(namespace: argparse.Namespace) -> Path:
    return Path(namespace.root).resolve()


def _provider(namespace: argparse.Namespace) -> GitHubProvider:
    return GitHubProvider(
        GitHubApiClient(token=namespace.token or os.environ.get("GITHUB_TOKEN"))
    )


def _require_project(root: Path, project_id: str) -> None:
    try:
        ProjectStore(root).load(project_id)
    except FileNotFoundError as exc:
        raise ValueError(f"project does not exist: {project_id}") from exc


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
                # Resolve authorization before constructing the live-only
                # workflow, so pending requests remain pending rather than
                # failing on adapter configuration.
                policy.require_authorized(request)
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
    scope_metadata = {"project_id": namespace.project_id} if namespace.project_id else None
    try:
        service = CollectionService(
            _provider(namespace), ProjectStore(root), ObservationStore(root)
        )
        count = service.collect_all(
            run_id=run_id,
            scheduled_at=_timestamp(namespace.scheduled_at) if namespace.scheduled_at else started,
            project_id=namespace.project_id,
        )
        errors = service.last_errors
        print(f"appended observations: {count}")
        if errors:
            for error in errors:
                print(f"collect warning: {error}", file=sys.stderr)
        status = "partial" if errors and count else "failed" if errors else "succeeded"
        _write_manifest(
            root,
            run_id=run_id,
            kind="collect",
            started_at=started,
            status=status,
            counts={
                "observations_appended": count,
                "projects_skipped": len(service.last_skipped),
                "errors": len(errors),
            },
            errors=errors,
            metadata=scope_metadata,
        )
        return 1 if errors and not count else 0
    except (ValueError, FileNotFoundError, RuntimeError, GitHubProviderError) as exc:
        print(f"collect failed: {exc}", file=sys.stderr)
        _write_manifest(
            root,
            run_id=run_id,
            kind="collect",
            started_at=started,
            status="failed",
            counts={},
            errors=[str(exc)],
            metadata=scope_metadata,
        )
        return 1


def _detect_changes(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        if namespace.project_id:
            _require_project(root, namespace.project_id)
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


def _write_json_lines(path: Path, records: list[dict[str, object]]) -> None:
    content = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _propose_analysis(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        if namespace.project_id:
            _require_project(root, namespace.project_id)
        events = ChangeEventStore(root).all()
        proposals = build_analysis_proposals(
            event for event in events if namespace.project_id is None or event.project_id == namespace.project_id
        )
        values = [proposal.to_dict() for proposal in proposals]
        validator = SchemaValidator(root)
        for value in values:
            validator.validate("research-proposal.v1.json", value)
        if namespace.output:
            destination = Path(namespace.output)
            if not destination.is_absolute():
                destination = root / destination
            _write_json_lines(destination, values)
            print(destination)
        else:
            for value in values:
                print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        _write_manifest(
            root,
            run_id=run_id,
            kind="propose-analysis",
            started_at=started,
            status="succeeded",
            counts={"proposals": len(proposals)},
            metadata={"project_id": namespace.project_id} if namespace.project_id else None,
        )
        return 0
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"propose-analysis failed: {exc}", file=sys.stderr)
        _write_manifest(
            root,
            run_id=run_id,
            kind="propose-analysis",
            started_at=started,
            status="failed",
            counts={},
            errors=[str(exc)],
        )
        return 1


def _context(namespace: argparse.Namespace):
    return ContextStore(_root(namespace)).load(namespace.context_id) if namespace.context_id else None


def _score(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        _require_project(root, namespace.project_id)
        context = _context(namespace)
        evaluated_at = _timestamp(namespace.evaluated_at) if namespace.evaluated_at else None
        card = ScoreEngine().score(
            namespace.project_id,
            ResearchEvidenceStore(root).all(),
            context=context,
            evaluated_at=evaluated_at,
            input_version=namespace.input_version,
        )
        SchemaValidator(root).validate("score-card.v1.json", card.to_dict())
        print(json.dumps(card.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        _write_manifest(
            root,
            run_id=run_id,
            kind="score",
            started_at=started,
            status="succeeded",
            counts={"dimensions": len(card.dimensions), "complete": int(card.total_score is not None)},
            metadata={
                "project_id": namespace.project_id,
                **({"context_id": namespace.context_id} if namespace.context_id else {}),
            },
        )
        return 0
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"score failed: {exc}", file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="score", started_at=started, status="failed", counts={}, errors=[str(exc)])
        return 1


def _report_input_version(evidence, *, cutoff_at: datetime) -> str:
    versions = sorted({item.input_version for item in evidence if item.generated_at <= cutoff_at})
    if not versions:
        return "research:none"
    if len(versions) == 1:
        return versions[0]
    import hashlib

    return "research:" + hashlib.sha256("\n".join(versions).encode("utf-8")).hexdigest()[:16]


def _report(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        cutoff_at = _timestamp(namespace.cutoff_at)
        projects = ProjectStore(root).all()
        observations = ObservationStore(root).all()
        evidence = ResearchEvidenceStore(root).all()
        context = _context(namespace)
        scorecards = [
            ScoreEngine().score(
                project.id,
                evidence,
                context=context,
                evaluated_at=cutoff_at,
                input_version=namespace.input_version,
            )
            for project in projects
        ]
        snapshot = ReportRenderer().render(
            projects,
            observations,
            scorecards,
            cutoff_at=cutoff_at,
            input_version=namespace.input_version or _report_input_version(evidence, cutoff_at=cutoff_at),
            report_type=namespace.report_type,
            report_id=namespace.report_id,
            score_version=namespace.score_version,
            prompt_versions={
                item.prompt_version
                for item in evidence
                if item.generated_at <= cutoff_at and item.prompt_version is not None
            },
            context_id=namespace.context_id,
            context=context,
        )
        SchemaValidator(root).validate("report.v1.json", snapshot.to_dict())
        if namespace.output:
            destination = Path(namespace.output)
            if not destination.is_absolute():
                destination = root / destination
            ReportStore(root).write_to(snapshot, destination)
            print(destination)
        else:
            ReportStore(root).write(snapshot)
            print(ReportStore(root).path_for(snapshot.report_id))
        _write_manifest(
            root,
            run_id=run_id,
            kind="report",
            started_at=started,
            status="succeeded",
            counts={"projects": len(projects), "reports": 1},
            metadata={
                "report_id": snapshot.report_id,
                "input_version": snapshot.input_version,
                **({"context_id": namespace.context_id} if namespace.context_id else {}),
            },
        )
        return 0
    except (DuplicateReportError, ValueError, FileNotFoundError, OSError) as exc:
        print(f"report failed: {exc}", file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="report", started_at=started, status="failed", counts={}, errors=[str(exc)])
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
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
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
        observation_ids = {observation.event_id for observation in observations}
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
        try:
            contexts = ContextStore(root).all()
            context_by_id = {context.context_id: context for context in contexts}
            for context in contexts:
                try:
                    validator.validate("context.v1.json", context.to_dict())
                    unknown_projects = sorted(set(context.project_ids) - set(project_by_id))
                    if unknown_projects:
                        raise ValueError(
                            "context references unknown projects: " + ", ".join(unknown_projects)
                        )
                except ValueError as exc:
                    errors.append(f"context {context.context_id}: {exc}")
        except (ValueError, FileNotFoundError, OSError) as exc:
            context_by_id = {}
            errors.append(f"context store: {exc}")
        try:
            evidence_store = ResearchEvidenceStore(root)
            for evidence in evidence_store.all():
                try:
                    validator.validate("research-evidence.v1.json", evidence.to_dict())
                    if evidence.project_id not in project_by_id:
                        raise ValueError(f"research evidence references unknown project: {evidence.project_id}")
                    if evidence.source_type == "observation" and evidence.source_ref not in observation_ids:
                        raise ValueError(
                            f"research evidence references unknown observation: {evidence.source_ref}"
                        )
                    if evidence.context_id is not None and evidence.context_id not in context_by_id:
                        raise ValueError(f"research evidence references unknown context: {evidence.context_id}")
                except ValueError as exc:
                    errors.append(f"research evidence {evidence.evidence_id}: {exc}")
        except (ValueError, FileNotFoundError, OSError) as exc:
            errors.append(f"research evidence ledger: {exc}")
        try:
            for report in ReportStore(root).all():
                try:
                    validator.validate("report.v1.json", report.to_dict())
                    unknown_projects = sorted(set(report.project_ids) - set(project_by_id))
                    if unknown_projects:
                        raise ValueError(f"report references unknown projects: {', '.join(unknown_projects)}")
                except ValueError as exc:
                    errors.append(f"report {report.report_id}: {exc}")
        except (ValueError, FileNotFoundError, OSError) as exc:
            errors.append(f"report store: {exc}")
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
    except (ValueError, FileNotFoundError, OSError) as exc:
        errors.append(str(exc))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        if namespace.record_run:
            _write_manifest(root, run_id=run_id, kind="validate", started_at=started, status="failed", counts={"errors": len(errors)}, errors=errors)
        return 1
    print("validation ok")
    if namespace.record_run:
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
    collect.add_argument("--project-id", help="collect only one project")
    collect.set_defaults(handler=_collect)

    detect_changes = subparsers.add_parser(
        "detect-changes", help="derive deterministic change events from observations"
    )
    detect_changes.add_argument("--root", default=argparse.SUPPRESS)
    detect_changes.add_argument("--project-id")
    detect_changes.set_defaults(handler=_detect_changes)

    propose_analysis = subparsers.add_parser(
        "propose-analysis", help="build review-only analysis proposals from change events"
    )
    propose_analysis.add_argument("--root", default=argparse.SUPPRESS)
    propose_analysis.add_argument("--project-id")
    propose_analysis.add_argument("--output", help="optional PR artifact path; never writes data/proposals")
    propose_analysis.set_defaults(handler=_propose_analysis)

    score = subparsers.add_parser("score", help="derive a score card from accepted research evidence")
    score.add_argument("--root", default=argparse.SUPPRESS)
    score.add_argument("--project-id", required=True)
    score.add_argument("--context-id")
    score.add_argument("--evaluated-at")
    score.add_argument("--input-version")
    score.set_defaults(handler=_score)

    report = subparsers.add_parser("report", help="render and freeze a historical Markdown report")
    report.add_argument("--root", default=argparse.SUPPRESS)
    report.add_argument("--cutoff-at", required=True)
    report.add_argument("--report-type", choices=["weekly", "monthly"], default="monthly")
    report.add_argument("--report-id")
    report.add_argument("--context-id")
    report.add_argument("--input-version")
    report.add_argument("--score-version", default="radar-score/1")
    report.add_argument("--output", help="optional explicit Markdown path; default is reports/<report-id>.md")
    report.set_defaults(handler=_report)

    generate = subparsers.add_parser("generate", help="render the deterministic README")
    generate.add_argument("--root", default=argparse.SUPPRESS)
    generate.add_argument("--output", default="README.md")
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(handler=_generate)

    validate = subparsers.add_parser("validate", help="validate projects, observations, and taxonomy")
    validate.add_argument("--root", default=argparse.SUPPRESS)
    validate.add_argument("--record-run", action="store_true", help="persist a validation run manifest")
    validate.set_defaults(handler=_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    try:
        return namespace.handler(namespace)
    except RunManifestError as exc:
        print(f"{namespace.command} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
