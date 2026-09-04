"""Deterministic derived README generation."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from .domain import ObservationRecord, Project
from .storage import ObservationStore, current_observations


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _primary_url(project: Project) -> str:
    primary = next(repository for repository in project.repositories if repository.role == "primary")
    return f"https://github.com/{primary.owner}/{primary.repo}"


def render_readme(
    projects: Iterable[Project],
    observations: ObservationStore | Iterable[ObservationRecord],
    *,
    template_path: Path | None = None,
) -> str:
    project_list = sorted(projects, key=lambda item: (item.primary_category, item.display_name.lower(), item.id))
    current_by_project: dict[str, list[ObservationRecord]] = {}
    if isinstance(observations, ObservationStore):
        current_by_project = {project.id: observations.current_for(project.id) for project in project_list}
    else:
        records = list(observations)
        current_by_project = {
            project.id: current_observations(records, project.id) for project in project_list
        }

    rows = []
    for project in project_list:
        current = current_by_project.get(project.id, [])
        primary = project.primary_repository
        latest = next(
            (
                record
                for record in current
                if record.provider == primary.provider
                and record.repository_id == primary.repository_id
            ),
            None,
        )
        stars = latest.metrics.get("stars", "N/A") if latest else "N/A"
        observed = latest.observed_at.isoformat().replace("+00:00", "Z") if latest else "N/A"
        rows.append(
            {
                "display_name": _escape(project.display_name),
                "url": _primary_url(project),
                "category": _escape(project.primary_category),
                "stage": _escape(project.research_stage),
                "decision": _escape(project.decision),
                "tracking": _escape(project.tracking),
                "stars": _escape(stars),
                "observed": _escape(observed),
            }
        )
    if template_path is None:
        checkout_template = Path(__file__).resolve().parents[2] / "templates" / "README.md.j2"
        if checkout_template.is_file():
            template_text = checkout_template.read_text(encoding="utf-8")
        else:
            template_text = files("open_radar").joinpath(
                "templates", "README.md.j2"
            ).read_text(encoding="utf-8")
    else:
        template_text = Path(template_path).read_text(encoding="utf-8")
    template = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True).from_string(
        template_text
    )
    return template.render(projects=rows)


def write_readme(path: Path, content: str, *, force: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing README: {path}")
    path.write_text(content, encoding="utf-8")
    return path
