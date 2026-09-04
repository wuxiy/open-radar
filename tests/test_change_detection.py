from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

from open_radar.change_detection import (
    ChangeDetector,
    ChangeEvent,
    ChangeEventStore,
)
from open_radar.domain import ObservationRecord


UTC = timezone.utc


def observation(
    event_id: str,
    *,
    observed_at: str,
    stars: int | None = 100,
    archived: bool | None = False,
    license_spdx: str | None = "MIT",
    unavailable: dict[str, str] | None = None,
) -> ObservationRecord:
    facts = {
        "archived": archived,
        "language": "Python",
        "license_spdx": license_spdx,
        "topics": ["radar", "github"],
    }
    unavailable = unavailable or {}
    for key in unavailable:
        facts[key] = None
    timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    return ObservationRecord.from_dict(
        {
            "schema_version": 1,
            "record_type": "observation",
            "event_id": event_id,
            "collection_key": f"github:42:{observed_at}",
            "run_id": f"run-{event_id}",
            "project_id": "radar",
            "provider": "github",
            "repository_id": 42,
            "scheduled_at": observed_at,
            "observed_at": observed_at,
            "recorded_at": timestamp.isoformat().replace("+00:00", "Z"),
            "collector_version": "test",
            "source": "fixture",
            "metrics": {"stars": stars} if stars is not None else {},
            "facts": facts,
            "unavailable": unavailable,
        }
    )


def correction(
    event_id: str,
    *,
    supersedes: str,
    observed_at: str,
    archived: bool,
) -> ObservationRecord:
    timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    return ObservationRecord.from_dict(
        {
            "schema_version": 1,
            "record_type": "correction",
            "event_id": event_id,
            "collection_key": f"github:42:{observed_at}",
            "run_id": f"run-{event_id}",
            "project_id": "radar",
            "provider": "github",
            "repository_id": 42,
            "scheduled_at": observed_at,
            "observed_at": observed_at,
            "recorded_at": timestamp.isoformat().replace("+00:00", "Z"),
            "collector_version": "test",
            "source": "fixture-correction",
            "metrics": {"stars": 100},
            "facts": {"archived": archived, "language": "Python", "license_spdx": "MIT", "topics": ["github", "radar"]},
            "unavailable": {},
            "supersedes": supersedes,
            "correction_reason": "fixture correction",
        }
    )


class ChangeEventContractTests(unittest.TestCase):
    def test_detector_emits_significant_license_and_activity_changes(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z", stars=100),
            observation(
                "obs-2",
                observed_at="2026-09-02T00:00:00Z",
                stars=140,
                license_spdx="Apache-2.0",
            ),
        ]

        events = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )

        self.assertEqual([event.field for event in events], ["facts.license_spdx", "metrics.stars"])
        self.assertEqual(events[0].change_type, "license")
        self.assertEqual(events[0].severity, "high")
        self.assertEqual(events[0].before, "MIT")
        self.assertEqual(events[0].after, "Apache-2.0")
        self.assertEqual(len(events[0].fingerprint), 64)
        self.assertEqual(events[0].change_id, f"change-{events[0].fingerprint[:24]}")

    def test_detector_skips_unknown_values_and_subthreshold_metrics(self):
        records = [
            observation(
                "obs-1",
                observed_at="2026-09-01T00:00:00Z",
                stars=100,
                license_spdx=None,
                unavailable={"license_spdx": "not_reported"},
            ),
            observation(
                "obs-2",
                observed_at="2026-09-02T00:00:00Z",
                stars=110,
                license_spdx="MIT",
            ),
        ]

        events = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )

        self.assertEqual(events, [])

        zero_baseline = [
            observation("obs-3", observed_at="2026-09-01T00:00:00Z", stars=0),
            observation("obs-4", observed_at="2026-09-02T00:00:00Z", stars=1),
        ]
        self.assertEqual(
            ChangeDetector().detect(
                zero_baseline,
                detected_at=datetime(2026, 9, 3, tzinfo=UTC),
            ),
            [],
        )

    def test_change_event_round_trip_rejects_mutation(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z"),
            observation("obs-2", observed_at="2026-09-02T00:00:00Z", archived=True),
        ]
        event = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )[0]

        restored = ChangeEvent.from_dict(json.loads(json.dumps(event.to_dict())))
        self.assertEqual(restored, event)
        invalid = event.to_dict()
        invalid["after"] = event.before
        with self.assertRaises(ValueError):
            ChangeEvent.from_dict(invalid)

        activity_event = ChangeDetector().detect(
            [
                observation("obs-3", observed_at="2026-09-01T00:00:00Z", stars=100),
                observation("obs-4", observed_at="2026-09-02T00:00:00Z", stars=140),
            ],
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )[0]
        invalid = activity_event.to_dict()
        invalid["after"] = 110
        with self.assertRaises(ValueError):
            ChangeEvent.from_dict(invalid)

        invalid = event.to_dict()
        invalid["detected_at"] = "2026-09-01T12:00:00Z"
        with self.assertRaises(ValueError):
            ChangeEvent.from_dict(invalid)
        invalid = event.to_dict()
        del invalid["before"]
        with self.assertRaises(ValueError):
            ChangeEvent.from_dict(invalid)

    def test_store_is_idempotent_for_replayed_detection(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z"),
            observation("obs-2", observed_at="2026-09-02T00:00:00Z", archived=True),
        ]
        detected_at = datetime(2026, 9, 3, tzinfo=UTC)
        events = ChangeDetector().detect(records, detected_at=detected_at)

        with tempfile.TemporaryDirectory() as directory:
            store = ChangeEventStore(Path(directory))
            self.assertEqual(store.append_many(events), 1)
            self.assertEqual(store.append_many(events), 0)
            self.assertEqual(store.all(), events)

    def test_store_rejects_event_with_forged_identity(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z"),
            observation("obs-2", observed_at="2026-09-02T00:00:00Z", archived=True),
        ]
        event = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )[0]
        conflicting = ChangeEvent(
            **{
                **event.__dict__,
                "change_id": "change-" + "f" * 24,
                "fingerprint": "f" * 64,
                "after": False,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ChangeEventStore(Path(directory))
            with self.assertRaises(ValueError):
                store.append(conflicting)

    def test_store_validates_a_batch_before_writing_any_event(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z"),
            observation("obs-2", observed_at="2026-09-02T00:00:00Z", archived=True),
        ]
        event = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )[0]
        invalid = ChangeEvent(
            **{
                **event.__dict__,
                "change_id": "change-" + "f" * 24,
                "fingerprint": "f" * 64,
                "after": False,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ChangeEventStore(Path(directory))
            with self.assertRaises(ValueError):
                store.append_many([event, invalid])
            self.assertEqual(store.all(), [])
            self.assertEqual(list((Path(directory) / "data" / "change-events").glob("*.jsonl")), [])

    def test_store_detects_duplicate_rows_already_present_on_disk(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z"),
            observation("obs-2", observed_at="2026-09-02T00:00:00Z", archived=True),
        ]
        event = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "change-events" / "2026-09.jsonl"
            path.parent.mkdir(parents=True)
            line = json.dumps(event.to_dict(), sort_keys=True) + "\n"
            path.write_text(line + line, encoding="utf-8")
            with self.assertRaises(ValueError):
                ChangeEventStore(Path(directory)).all()

    def test_detector_uses_corrections_and_ignores_invalidated_history(self):
        records = [
            observation("obs-1", observed_at="2026-09-01T00:00:00Z", archived=False),
            observation("obs-2", observed_at="2026-09-02T00:00:00Z", archived=True),
            correction(
                "corr-2",
                supersedes="obs-2",
                observed_at="2026-09-02T00:00:00Z",
                archived=False,
            ),
        ]

        events = ChangeDetector().detect(
            records,
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
