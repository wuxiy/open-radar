"""Thin command-line orchestration for Open Radar."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

import yaml

from .contracts.schema import SchemaValidator
from .github_provider import GitHubApiClient, GitHubProvider
from .generation import render_readme, write_readme
from .storage import ObservationStore, ProjectStore
from .taxonomy import Taxonomy
from .workflows.admission import AdmissionService, DuplicateRepositoryError, SlugCollisionError
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


def _write_manifest(root: Path, *, run_id: str, kind: str, started_at: datetime, status: str, counts: dict[str, int], errors: list[str] | None = None) -> None:
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
    with destination.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _root(namespace: argparse.Namespace) -> Path:
    return Path(namespace.root).resolve()


def _provider(namespace: argparse.Namespace) -> GitHubProvider:
    return GitHubProvider(GitHubApiClient(token=namespace.token))


def _ingest(namespace: argparse.Namespace) -> int:
    root = _root(namespace)
    started = _now()
    run_id = _run_id()
    try:
        tags = tuple(tag.strip() for tag in namespace.tags.split(",") if tag.strip())
        service = AdmissionService(_provider(namespace), ProjectStore(root), Taxonomy.load(root))
        candidate = service.build_candidate(
            namespace.url,
            discovered_at=_timestamp(namespace.discovered_at) if namespace.discovered_at else started,
            project_id=namespace.project_id,
            primary_category=namespace.primary_category,
            tags=tags,
            tracking=namespace.tracking,
            research_stage=namespace.research_stage,
            decision=namespace.decision,
        )
        if namespace.write:
            path = service.admit(candidate)
            print(path)
            count = 1
        else:
            print(yaml.safe_dump(candidate.to_dict(), allow_unicode=True, sort_keys=False), end="")
            count = 0
        _write_manifest(root, run_id=run_id, kind="ingest", started_at=started, status="succeeded", counts={"admitted": count})
        return 0
    except (ValueError, FileNotFoundError, DuplicateRepositoryError, SlugCollisionError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="ingest", started_at=started, status="failed", counts={}, errors=[str(exc)])
        return 1


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
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"collect failed: {exc}", file=sys.stderr)
        _write_manifest(root, run_id=run_id, kind="collect", started_at=started, status="failed", counts={}, errors=[str(exc)])
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
        seen_run_ids: set[str] = set()
        for manifest_path in sorted((root / "data" / "runs").glob("*.jsonl")):
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
    ingest.set_defaults(handler=_ingest)

    collect = subparsers.add_parser("collect", help="collect tracking-enabled GitHub observations")
    collect.add_argument("--root", default=argparse.SUPPRESS)
    collect.add_argument("--token", default=None)
    collect.add_argument("--run-id")
    collect.add_argument("--scheduled-at")
    collect.set_defaults(handler=_collect)

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
