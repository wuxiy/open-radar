from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from open_radar.domain import ObservationRecord, Project
from open_radar.reporting import DuplicateReportError, ReportRenderer, ReportSnapshot, ReportStore
from open_radar.research import ResearchEvidence
from open_radar.scoring import Context, ScoreEngine


UTC = timezone.utc


PROJECT = Project.from_dict(
    {
        "schema_version": 1,
        "id": "radar-demo",
        "display_name": "Radar Demo",
        "aliases": [],
        "repositories": [{"provider": "github", "repository_id": 42, "owner": "example", "repo": "demo", "role": "primary"}],
        "primary_category": "automation",
        "tags": ["automation"],
        "discovery_sources": [{"type": "manual", "url": "https://github.com/example/demo", "discovered_at": "2026-09-01T00:00:00Z"}],
        "research_stage": "watching",
        "decision": "undecided",
        "tracking": "weekly",
    }
)


def _observation(event_id: str, observed_at: str) -> ObservationRecord:
    return ObservationRecord.from_dict(
        {
            "schema_version": 1,
            "record_type": "observation",
            "event_id": event_id,
            "collection_key": f"slot-{event_id}",
            "run_id": f"run-{event_id}",
            "project_id": "radar-demo",
            "provider": "github",
            "repository_id": 42,
            "scheduled_at": observed_at,
            "observed_at": observed_at,
            "recorded_at": observed_at,
            "collector_version": "test",
            "source": "fixture",
            "metrics": {"stars": 10},
            "facts": {"archived": False, "license_spdx": "MIT"},
            "unavailable": {},
        }
    )


def _scorecard():
    values = []
    for index, (dimension, rating) in enumerate(
        [("innovation", 8), ("engineering", 7), ("relevance", 9), ("activity", 6), ("learning_value", 10)]
    ):
        item = {
            "schema_version": 1,
            "evidence_id": f"evidence-{dimension.replace('_', '-')}",
            "project_id": "radar-demo",
            "kind": "fact",
            "claim": f"{dimension} claim",
            "reason": "Recorded for deterministic reporting tests.",
            "source_type": "snapshot",
            "source_ref": "run-1",
            "input_version": "snapshot-1",
            "generated_at": "2026-09-01T00:00:00Z",
            "confidence": 0.9,
            "dimension": dimension,
            "rating": rating,
        }
        if dimension == "relevance":
            item["context_id"] = "open-scope"
        values.append(ResearchEvidence.from_dict(item))
    return ScoreEngine().score(
        "radar-demo",
        values,
        context=Context.from_dict(
            {
                "schema_version": 1,
                "context_id": "open-scope",
                "name": "Open Scope",
                "goal": "Choose infrastructure.",
                "technical_questions": ["Does it fit?"],
                "priority": 3,
            }
        ),
        evaluated_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


class ReportingTests(unittest.TestCase):
    def test_report_is_cutoff_bound_and_deterministically_rendered(self):
        renderer = ReportRenderer()
        kwargs = {
            "cutoff_at": datetime(2026, 9, 2, tzinfo=UTC),
            "input_version": "observations:2026-09",
            "scorecards": [_scorecard()],
            "report_type": "monthly",
            "context_id": "open-scope",
        }
        first = renderer.render([PROJECT], [_observation("old", "2026-09-01T00:00:00Z"), _observation("future", "2026-09-03T00:00:00Z")], **kwargs)
        second = renderer.render([PROJECT], [_observation("old", "2026-09-01T00:00:00Z")], **kwargs)
        self.assertEqual(first, second)
        self.assertIn("80.50", first.content)
        self.assertEqual(first.context_id, "open-scope")
        self.assertEqual(len(first.input_digest), 64)
        self.assertIn("2026-09-01T00:00:00Z", first.content)
        self.assertNotIn("2026-09-03", first.content)
        self.assertEqual(first.report_id, "report-monthly-2026-09")
        self.assertEqual(ReportSnapshot.from_dict(first.to_dict()), first)

    def test_report_store_is_write_once_and_keeps_metadata(self):
        snapshot = ReportRenderer().render(
            [PROJECT], [], [], cutoff_at=datetime(2026, 9, 2, tzinfo=UTC), input_version="none"
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ReportStore(Path(directory))
            self.assertTrue(store.write(snapshot))
            self.assertFalse(store.write(snapshot))
            self.assertEqual(store.all(), [snapshot])
            store.metadata_path_for(snapshot.report_id).unlink()
            self.assertTrue(store.write(snapshot))
            self.assertEqual(store.all(), [snapshot])
            changed = ReportSnapshot.from_dict({**snapshot.to_dict(), "input_version": "changed"})
            with self.assertRaises(DuplicateReportError):
                store.write(changed)
            self.assertTrue(store.path_for(snapshot.report_id).is_file())
            self.assertTrue(store.metadata_path_for(snapshot.report_id).is_file())


if __name__ == "__main__":
    unittest.main()
