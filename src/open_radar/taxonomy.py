"""Controlled taxonomies for project metadata and relation types."""

from __future__ import annotations

from pathlib import Path

import yaml

from .contracts.schema import SchemaValidator
from .domain import ID_PATTERN, Project, ValidationError


def _load_identifiers(root: Path, kind: str) -> set[str]:
    root = Path(root)
    path = root / "data" / "taxonomy" / f"{kind}.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValidationError(f"{path}: invalid taxonomy YAML") from exc
    SchemaValidator(root).validate("taxonomy.v1.json", payload)
    if payload["kind"] != kind:
        raise ValueError(f"taxonomy file kind mismatch: {path}")
    identifiers = [item["id"] for item in payload["items"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"taxonomy contains duplicate ids: {path}")
    return set(identifiers)


class Taxonomy:
    def __init__(self, categories: set[str], tags: set[str]) -> None:
        self.categories = categories
        self.tags = tags

    @classmethod
    def load(cls, root: Path) -> "Taxonomy":
        return cls(_load_identifiers(root, "categories"), _load_identifiers(root, "tags"))

    def validate_project(self, project: Project) -> None:
        if project.primary_category not in self.categories:
            raise ValidationError(f"unknown primary category: {project.primary_category}")
        unknown_tags = sorted(set(project.tags) - self.tags)
        if unknown_tags:
            raise ValidationError(f"unknown project tags: {', '.join(unknown_tags)}")


class RelationTypeCatalog:
    """Controlled relation types, stored separately from project taxonomy."""

    def __init__(self, directions_by_type: dict[str, frozenset[str]]) -> None:
        self.directions_by_type = directions_by_type

    @property
    def relation_types(self) -> set[str]:
        return set(self.directions_by_type)

    @classmethod
    def load(cls, root: Path) -> "RelationTypeCatalog":
        root = Path(root)
        path = root / "data" / "taxonomy" / "relation-types.yaml"
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValidationError(f"{path}: invalid relation type YAML") from exc
        SchemaValidator(root).validate("relation-types.v1.json", payload)
        identifiers = [item["id"] for item in payload["items"]]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"relation type catalog contains duplicate ids: {path}")
        return cls(
            {
                item["id"]: frozenset(item["directions"])
                for item in payload["items"]
            }
        )

    def validate(self, relation_type: str, direction: str) -> None:
        if not isinstance(relation_type, str) or not ID_PATTERN.fullmatch(relation_type):
            raise ValidationError("relation type must be a lowercase slug")
        directions = self.directions_by_type.get(relation_type)
        if directions is None:
            raise ValidationError(f"unknown relation type: {relation_type}")
        if direction not in directions:
            raise ValidationError(
                f"relation type {relation_type} does not support direction: {direction}"
            )
