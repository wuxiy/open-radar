"""Render the explicitly whitelisted public Catalog view."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
import shutil
import tempfile
from urllib.parse import quote
import uuid

from jinja2 import Environment, StrictUndefined, select_autoescape

from .domain import ObservationRecord, Project
from .storage import ObservationStore, current_observations


def _template_text(template_name: str, template_path: Path | None = None) -> str:
    if template_path is not None:
        return Path(template_path).read_text(encoding="utf-8")
    checkout_template = Path(__file__).resolve().parent / "templates" / template_name
    if checkout_template.is_file():
        return checkout_template.read_text(encoding="utf-8")
    return files("open_radar").joinpath("templates", template_name).read_text(encoding="utf-8")


def _environment() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default=True, default_for_string=True),
        keep_trailing_newline=True,
    )


def _public_repository_url(project: Project) -> str:
    primary = project.primary_repository
    return "https://github.com/{}/{}".format(
        quote(primary.owner, safe=""), quote(primary.repo, safe="")
    )


def _current_observations(
    projects: list[Project], observations: ObservationStore | Iterable[ObservationRecord]
) -> dict[str, list[ObservationRecord]]:
    if isinstance(observations, ObservationStore):
        return {project.id: observations.current_for(project.id) for project in projects}
    records = list(observations)
    return {project.id: current_observations(records, project.id) for project in projects}


def _public_base_path(value: str) -> str:
    """Normalize the only relative root allowed in the public fallback."""
    if not value:
        return "/"
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "?" in value
        or "#" in value
        or "\\" in value
    ):
        raise ValueError("public base path must be an absolute path without query or fragment")
    if value == "/":
        return "/"
    segments = value.strip("/").split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("public base path must not contain empty, dot, or parent segments")
    return "/" + "/".join(segments) + "/"


def render_public_catalog(
    projects: Iterable[Project],
    observations: ObservationStore | Iterable[ObservationRecord],
    *,
    template_path: Path | None = None,
) -> str:
    """Render only approved Catalog fields into a standalone HTML document."""
    project_list = sorted(
        projects, key=lambda item: (item.primary_category, item.display_name.lower(), item.id)
    )
    current_by_project = _current_observations(project_list, observations)
    rows = []
    for project in project_list:
        primary = project.primary_repository
        latest = next(
            (
                record
                for record in current_by_project.get(project.id, [])
                if record.provider == primary.provider
                and record.repository_id == primary.repository_id
            ),
            None,
        )
        rows.append(
            {
                "name": project.display_name,
                "url": _public_repository_url(project),
                "category": project.primary_category,
                "stage": project.research_stage,
                "tracking": project.tracking,
                "stars": latest.metrics.get("stars") if latest is not None else None,
                "observed": (
                    latest.observed_at.isoformat().replace("+00:00", "Z")
                    if latest is not None
                    else None
                ),
            }
        )
    template = _environment().from_string(_template_text("public-catalog.html.j2", template_path))
    return template.render(projects=rows, project_count=len(rows))


def render_public_not_found(
    *, base_path: str = "/", template_path: Path | None = None
) -> str:
    """Render the bounded Pages fallback without exposing repository paths."""
    template = _environment().from_string(_template_text("public-404.html.j2", template_path))
    return template.render(home_url=_public_base_path(base_path))


def write_public_site(
    directory: Path,
    *,
    catalog: str,
    not_found: str,
    force: bool = False,
) -> tuple[Path, Path]:
    """Atomically write only the two Pages entry points, or reject the destination."""
    directory = Path(directory)
    entry_point_names = {"index.html", "404.html"}
    directory.parent.mkdir(parents=True, exist_ok=True)

    replace_existing = False
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise FileExistsError(f"public site output is not a real directory: {directory}")
        entries = list(directory.iterdir())
        if not entries:
            directory.rmdir()
        elif (
            force
            and {path.name for path in entries} == entry_point_names
            and all(path.is_file() and not path.is_symlink() for path in entries)
        ):
            replace_existing = True
        else:
            raise FileExistsError(
                "refusing public site output with existing non-entry-point files: "
                + str(directory)
            )

    if directory.exists() and not replace_existing:
        raise FileExistsError(
            "refusing to overwrite public site output without --force: " + str(directory)
        )

    stage = Path(tempfile.mkdtemp(prefix=f".{directory.name}.pages-", dir=directory.parent))
    try:
        (stage / "index.html").write_text(catalog, encoding="utf-8")
        (stage / "404.html").write_text(not_found, encoding="utf-8")
        if not replace_existing:
            stage.replace(directory)
        else:
            backup = directory.parent / f".{directory.name}.previous-{uuid.uuid4().hex}"
            directory.replace(backup)
            try:
                stage.replace(directory)
            except OSError:
                backup.replace(directory)
                raise
            shutil.rmtree(backup)
    except OSError:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return directory / "index.html", directory / "404.html"
