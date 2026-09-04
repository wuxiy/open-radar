import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from open_radar.domain import ObservationRecord, Project
from open_radar.storage import DuplicateCollectionError, ObservationStore, ProjectStore


def sample_project(project_id="radar-demo"):
    return Project.from_dict(
        {
            "schema_version": 1,
            "id": project_id,
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
            "discovery_sources": [],
            "research_stage": "watching",
            "decision": "undecided",
            "tracking": "weekly",
            "personal_notes": "",
        }
    )


def sample_observation(event_id="obs-demo-001", collection_key="slot-001", stars=42):
    return ObservationRecord.from_dict(
        {
            "schema_version": 1,
            "record_type": "observation",
            "event_id": event_id,
            "collection_key": collection_key,
            "run_id": "run-demo-001",
            "project_id": "radar-demo",
            "provider": "github",
            "repository_id": 100000001,
            "scheduled_at": "2026-09-03T00:00:00Z",
            "observed_at": "2026-09-03T00:02:00Z",
            "recorded_at": "2026-09-03T00:03:00Z",
            "collector_version": "collector-v1",
            "source": "github-api",
            "metrics": {"stars": stars, "forks": 3},
            "facts": {"archived": False, "license_spdx": None},
            "unavailable": {"license_spdx": "not_reported"},
        }
    )


class ProjectStoreTests(unittest.TestCase):
    def test_yaml_round_trip_and_repository_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = sample_project()
            path = store.save(project)

            self.assertEqual(path.name, "radar-demo.yaml")
            self.assertEqual(store.load("radar-demo"), project)
            self.assertEqual(
                store.find_by_repository("github", 100000001).id,
                "radar-demo",
            )


class ObservationStoreTests(unittest.TestCase):
    def test_append_is_idempotent_by_collection_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            record = sample_observation()

            self.assertTrue(store.append(record))
            self.assertFalse(store.append(record))
            path = Path(directory) / "data" / "observations" / "github" / "2026-09.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 1)

    def test_conflicting_replay_raises_instead_of_silently_duplicating(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            store.append(sample_observation(stars=42))

            with self.assertRaises(DuplicateCollectionError):
                store.append(sample_observation(event_id="obs-demo-002", stars=43))

    def test_correction_must_reference_an_existing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            original = sample_observation()
            store.append(original)
            correction = ObservationRecord.from_dict(
                {
                    **sample_observation(
                        event_id="obs-demo-002", stars=43
                    ).to_dict(),
                    "record_type": "correction",
                    "supersedes": original.event_id,
                    "correction_reason": "stale response",
                }
            )

            self.assertTrue(store.append(correction))
            self.assertEqual(store.current_for("radar-demo")[0].metrics["stars"], 43)

    def test_correction_cannot_point_to_an_unknown_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            correction = ObservationRecord.from_dict(
                {
                    **sample_observation(event_id="obs-demo-002").to_dict(),
                    "record_type": "correction",
                    "supersedes": "missing-event",
                    "correction_reason": "bad source",
                }
            )
            with self.assertRaises(ValueError):
                store.append(correction)

    def test_correction_cannot_change_collection_identity_or_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            original = sample_observation()
            store.append(original)
            changed_slot = ObservationRecord.from_dict(
                {
                    **sample_observation(event_id="obs-demo-002").to_dict(),
                    "record_type": "correction",
                    "collection_key": "different-slot",
                    "supersedes": original.event_id,
                    "correction_reason": "wrong slot",
                }
            )
            with self.assertRaises(ValueError):
                store.append(changed_slot)

            correction = ObservationRecord.from_dict(
                {
                    **sample_observation(event_id="obs-demo-003", stars=43).to_dict(),
                    "record_type": "correction",
                    "supersedes": original.event_id,
                    "correction_reason": "stale response",
                }
            )
            store.append(correction)
            branch = ObservationRecord.from_dict(
                {
                    **sample_observation(event_id="obs-demo-004", stars=44).to_dict(),
                    "record_type": "correction",
                    "supersedes": original.event_id,
                    "correction_reason": "another response",
                }
            )
            with self.assertRaises(ValueError):
                store.append(branch)

    def test_append_batch_validates_before_writing_any_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            first = sample_observation(event_id="obs-batch-001", collection_key="slot-a")
            conflicting = sample_observation(
                event_id="obs-batch-002", collection_key="slot-a", stars=99
            )
            with self.assertRaises(DuplicateCollectionError):
                store.append_batch([first, conflicting])
            self.assertEqual(store.all(), [])

    def test_late_record_is_routed_to_current_writable_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            late = ObservationRecord.from_dict(
                {
                    **sample_observation(
                        event_id="obs-late", collection_key="slot-late"
                    ).to_dict(),
                    "scheduled_at": "2026-08-01T00:00:00Z",
                    "observed_at": "2026-08-01T00:02:00Z",
                    "recorded_at": "2026-08-01T00:03:00Z",
                }
            )
            store.append(late)
            self.assertFalse(
                (Path(directory) / "data" / "observations" / "github" / "2026-08.jsonl").exists()
            )
            self.assertTrue(
                (Path(directory) / "data" / "observations" / "github" / "2026-09.jsonl").exists()
            )

    def test_future_record_is_clamped_to_current_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            current = sample_observation(event_id="obs-current", collection_key="slot-current")
            future = ObservationRecord.from_dict(
                {
                    **sample_observation(
                        event_id="obs-future", collection_key="slot-future"
                    ).to_dict(),
                    "scheduled_at": "2026-10-01T00:00:00Z",
                    "observed_at": "2026-10-01T00:02:00Z",
                    "recorded_at": "2026-10-01T00:03:00Z",
                }
            )
            self.assertEqual(store.append_batch([current, future]), 2)
            self.assertEqual(len(store.all()), 2)
            self.assertFalse(
                (Path(directory) / "data" / "observations" / "github" / "2026-10.jsonl").exists()
            )


if __name__ == "__main__":
    unittest.main()
