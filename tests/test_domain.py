import unittest
from datetime import timedelta

from open_radar.domain import (
    ObservationRecord,
    Project,
    ValidationError,
    validate_project_data,
)


def project_data(**overrides):
    value = {
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
        "primary_category": "devtools",
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
    value.update(overrides)
    return value


class ProjectContractTests(unittest.TestCase):
    def test_project_round_trips_without_machine_owned_fields(self):
        project = Project.from_dict(project_data())

        self.assertEqual(project.id, "radar-demo")
        self.assertEqual(project.repositories[0].repository_id, 100000001)
        self.assertEqual(project.to_dict(), project_data())

    def test_project_rejects_legacy_single_status_and_metrics(self):
        for field in ("status", "metrics", "health", "evaluation", "radar_score"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    validate_project_data(project_data(**{field: {}}))

    def test_project_requires_one_primary_repository(self):
        repositories = project_data()["repositories"]
        for replacement in (
            [],
            [dict(repositories[0], role="sdk")],
            repositories + [dict(repositories[0], repository_id=100000002)],
        ):
            with self.subTest(replacement=replacement):
                with self.assertRaises(ValidationError):
                    validate_project_data(project_data(repositories=replacement))

    def test_primary_repository_is_selected_by_role_not_list_position(self):
        repositories = project_data()["repositories"]
        project = Project.from_dict(
            project_data(
                repositories=[
                    dict(repositories[0], repository_id=100000002, role="sdk"),
                    repositories[0],
                ]
            )
        )
        self.assertEqual(project.primary_repository.repository_id, 100000001)


class ObservationContractTests(unittest.TestCase):
    def test_observation_requires_utc_timestamps_and_preserves_unknown_values(self):
        record = ObservationRecord.from_dict(
            {
                "schema_version": 1,
                "record_type": "observation",
                "event_id": "obs-demo-001",
                "collection_key": "github:100000001:2026-09-03T00:00:00Z",
                "run_id": "run-demo-001",
                "project_id": "radar-demo",
                "provider": "github",
                "repository_id": 100000001,
                "scheduled_at": "2026-09-03T00:00:00Z",
                "observed_at": "2026-09-03T00:02:00Z",
                "recorded_at": "2026-09-03T00:03:00Z",
                "collector_version": "collector-v1",
                "source": "github-api",
                "metrics": {"stars": 42, "forks": 3},
                "facts": {"archived": False, "license_spdx": None},
                "unavailable": {"license_spdx": "not_reported"},
            }
        )

        self.assertEqual(record.to_dict()["facts"]["license_spdx"], None)
        self.assertEqual(record.recorded_at.utcoffset(), timedelta(0))

    def test_observation_rejects_negative_metrics_and_non_utc_time(self):
        base = {
            "schema_version": 1,
            "record_type": "observation",
            "event_id": "obs-demo-001",
            "collection_key": "slot",
            "run_id": "run-demo-001",
            "project_id": "radar-demo",
            "provider": "github",
            "repository_id": 100000001,
            "scheduled_at": "2026-09-03T00:00:00Z",
            "observed_at": "2026-09-03T00:02:00Z",
            "recorded_at": "2026-09-03T00:03:00Z",
            "collector_version": "collector-v1",
            "source": "github-api",
            "metrics": {"stars": 42},
            "facts": {},
            "unavailable": {},
        }
        with self.assertRaises(ValidationError):
            ObservationRecord.from_dict({**base, "metrics": {"stars": -1}})
        with self.assertRaises(ValidationError):
            ObservationRecord.from_dict(
                {**base, "recorded_at": "2026-09-03T08:03:00+08:00"}
            )

        with self.assertRaises(ValidationError):
            ObservationRecord.from_dict(
                {
                    **base,
                    "observed_at": "2026-09-03T00:04:00Z",
                    "recorded_at": "2026-09-03T00:03:00Z",
                }
            )

    def test_correction_must_reference_an_existing_event(self):
        base = {
            "schema_version": 1,
            "record_type": "correction",
            "event_id": "obs-demo-002",
            "collection_key": "slot",
            "run_id": "run-demo-002",
            "project_id": "radar-demo",
            "provider": "github",
            "repository_id": 100000001,
            "scheduled_at": "2026-09-03T00:00:00Z",
            "observed_at": "2026-09-03T00:02:00Z",
            "recorded_at": "2026-09-03T00:03:00Z",
            "collector_version": "collector-v1",
            "source": "github-api",
            "metrics": {"stars": 43},
            "facts": {},
            "unavailable": {},
            "supersedes": "obs-demo-001",
            "correction_reason": "stale response",
        }
        record = ObservationRecord.from_dict(base)
        self.assertEqual(record.supersedes, "obs-demo-001")

        with self.assertRaises(ValidationError):
            ObservationRecord.from_dict({**base, "supersedes": None})


if __name__ == "__main__":
    unittest.main()
