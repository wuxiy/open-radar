from pathlib import Path
import unittest

from open_radar.contracts.schema import SchemaValidator
from open_radar.admission_request import AdmissionRequest
from open_radar.domain import Project, ValidationError
from open_radar.taxonomy import Taxonomy
from open_radar.admission_transactions import AdmissionTransaction
from datetime import datetime, timezone


ROOT = Path(__file__).parents[1]


PROJECT = {
    "schema_version": 1,
    "id": "radar-demo",
    "display_name": "Radar Demo",
    "aliases": [],
    "repositories": [
        {
            "provider": "github",
            "repository_id": 100000001,
            "owner": "example-org",
            "repo": "radar-demo",
            "role": "primary",
        }
    ],
    "primary_category": "automation",
    "tags": ["automation"],
    "discovery_sources": [
        {
            "type": "manual",
            "url": "https://github.com/example-org/radar-demo",
            "discovered_at": "2026-09-03T00:00:00Z",
        }
    ],
    "research_stage": "watching",
    "decision": "undecided",
    "tracking": "weekly",
    "personal_notes": "",
}


OBSERVATION = {
    "schema_version": 1,
    "record_type": "observation",
    "event_id": "github-100000001-2026-09-03T00:00:00+00:00",
    "collection_key": "github:100000001:2026-09-03T00:00:00+00:00",
    "run_id": "run-1",
    "project_id": "radar-demo",
    "provider": "github",
    "repository_id": 100000001,
    "scheduled_at": "2026-09-03T00:00:00Z",
    "observed_at": "2026-09-03T00:02:00Z",
    "recorded_at": "2026-09-03T00:03:00Z",
    "collector_version": "open-radar-github/0.1",
    "source": "github-api",
    "metrics": {"stars": 42, "forks": 3},
    "facts": {"archived": False, "license_spdx": None},
    "unavailable": {"license_spdx": "not_reported"},
}


class SchemaTests(unittest.TestCase):
    def test_versioned_project_and_observation_validate(self):
        validator = SchemaValidator(ROOT)
        validator.validate("project.v1.json", PROJECT)
        validator.validate("observation.v1.json", OBSERVATION)
        request = AdmissionRequest.from_dict(
            {
                "schema_version": 1,
                "request_id": "issue-42",
                "intake_repository_id": "987654321",
                "issue_number": 42,
                "project_url": "https://github.com/example-org/radar-demo",
                "requester": "contributor",
                "labels": [],
                "created_at": "2026-09-04T00:00:00Z",
                "source_url": None,
                "comment": None,
            }
        )
        validator.validate("admission-request.v1.json", request.to_dict())
        transaction = AdmissionTransaction(
            schema_version=1,
            idempotency_key="github:987654321:issue-42",
            request_id="issue-42",
            intake_repository_id="987654321",
            issue_number=42,
            project_id="radar-demo",
            repository_id=100000001,
            project_url="https://github.com/example-org/radar-demo",
            requester="contributor",
            branch_name="admission/github-987654321-issue-42",
            status="pr_open",
            created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            pr_number=10001,
            pr_url="https://github.com/open-radar/admissions/pull/10001",
        )
        validator.validate("admission-transaction.v1.json", transaction.to_dict())

    def test_unknown_fields_are_rejected(self):
        validator = SchemaValidator(ROOT)
        invalid = dict(PROJECT)
        invalid["metrics"] = {}
        with self.assertRaises(ValueError):
            validator.validate("project.v1.json", invalid)

    def test_taxonomy_rejects_uncontrolled_category_and_tag(self):
        taxonomy = Taxonomy.load(ROOT)
        project = Project.from_dict(PROJECT)
        taxonomy.validate_project(project)
        invalid = dict(PROJECT)
        invalid["primary_category"] = "made-up"
        invalid["tags"] = ["made-up"]
        with self.assertRaises(ValidationError):
            taxonomy.validate_project(Project.from_dict(invalid))


if __name__ == "__main__":
    unittest.main()
