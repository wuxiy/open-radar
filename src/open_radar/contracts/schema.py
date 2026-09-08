"""JSON Schema validation for repository contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class SchemaValidator:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def validate(self, schema_name: str, data: Any) -> None:
        schema_path = self.root / "schemas" / schema_name
        if not schema_path.is_file():
            raise FileNotFoundError(schema_path)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
        if errors:
            path = ".".join(str(item) for item in errors[0].path) or "$"
            raise ValueError(f"{schema_name} invalid at {path}: {errors[0].message}")

    def validate_project(self, data: Any) -> None:
        self.validate("project.v1.json", data)

    def validate_observation(self, data: Any) -> None:
        self.validate("observation.v1.json", data)

    def validate_context(self, data: Any) -> None:
        self.validate("context.v1.json", data)

    def validate_relation(self, data: Any) -> None:
        self.validate("relation.v1.json", data)

    def validate_research_evidence(self, data: Any) -> None:
        self.validate("research-evidence.v1.json", data)

    def validate_report(self, data: Any) -> None:
        self.validate("report.v1.json", data)
