"""Controlled categories and tags for project metadata."""

from __future__ import annotations

from pathlib import Path

import yaml

from .contracts.schema import SchemaValidator
from .domain import Project, ValidationError


class Taxonomy:
    def __init__(self, categories: set[str], tags: set[str]) -> None:
        self.categories = categories
        self.tags = tags

    @classmethod
    def load(cls, root: Path) -> "Taxonomy":
        root = Path(root)
        schema = SchemaValidator(root)
        values: dict[str, set[str]] = {}
        for kind in ("categories", "tags"):
            path = root / "data" / "taxonomy" / f"{kind}.yaml"
            if not path.is_file():
                raise FileNotFoundError(path)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            schema.validate("taxonomy.v1.json", payload)
            if payload["kind"] != kind:
                raise ValueError(f"taxonomy file kind mismatch: {path}")
            identifiers = [item["id"] for item in payload["items"]]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"taxonomy contains duplicate ids: {path}")
            values[kind] = set(identifiers)
        return cls(values["categories"], values["tags"])

    def validate_project(self, project: Project) -> None:
        if project.primary_category not in self.categories:
            raise ValidationError(f"unknown primary category: {project.primary_category}")
        unknown_tags = sorted(set(project.tags) - self.tags)
        if unknown_tags:
            raise ValidationError(f"unknown project tags: {', '.join(unknown_tags)}")
