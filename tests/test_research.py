from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

from open_radar.change_detection import ChangeDetector
from open_radar.domain import ObservationRecord
from open_radar.research import (
    AnalysisProposal,
    ResearchEvidence,
    ResearchEvidenceStore,
    build_analysis_proposals,
)


UTC = timezone.utc


def _observation(event_id: str, observed_at: str, license_spdx: str) -> ObservationRecord:
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
            "metrics": {"stars": 100},
            "facts": {"archived": False, "license_spdx": license_spdx, "topics": []},
            "unavailable": {},
        }
    )


def _proposal() -> AnalysisProposal:
    events = ChangeDetector().detect(
        [
            _observation("obs-1", "2026-09-01T00:00:00Z", "MIT"),
            _observation("obs-2", "2026-09-02T00:00:00Z", "Apache-2.0"),
        ],
        detected_at=datetime(2026, 9, 3, tzinfo=UTC),
    )
    return build_analysis_proposals(events)[0]


class ResearchContractTests(unittest.TestCase):
    def test_change_event_produces_stable_review_proposal(self):
        first = _proposal()
        second = _proposal()

        self.assertEqual(first, second)
        self.assertEqual(first.status, "pending")
        self.assertTrue(first.trigger_event_id.startswith("change-"))
        self.assertIn("license", first.question.lower())
        self.assertEqual(len(first.fingerprint), 64)
        self.assertEqual(first.proposal_id, f"proposal-{first.fingerprint[:24]}")
        events = ChangeDetector().detect(
            [
                _observation("obs-1", "2026-09-01T00:00:00Z", "MIT"),
                _observation("obs-2", "2026-09-02T00:00:00Z", "Apache-2.0"),
            ],
            detected_at=datetime(2026, 9, 3, tzinfo=UTC),
        )
        self.assertEqual(build_analysis_proposals(events + events), [first])

    def test_proposal_round_trip_rejects_status_or_identity_mutation(self):
        proposal = _proposal()
        restored = AnalysisProposal.from_dict(json.loads(json.dumps(proposal.to_dict())))
        self.assertEqual(restored, proposal)

        invalid = proposal.to_dict()
        invalid["status"] = "unknown"
        with self.assertRaises(ValueError):
            AnalysisProposal.from_dict(invalid)

        invalid = proposal.to_dict()
        invalid["trigger_event_id"] = "forged"
        with self.assertRaises(ValueError):
            AnalysisProposal.from_dict(invalid)

    def test_research_evidence_requires_source_and_typed_rating(self):
        evidence = ResearchEvidence.from_dict(
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "project_id": "radar-demo",
                "kind": "fact",
                "claim": "The repository uses Python.",
                "reason": "The language fact is recorded in the repository snapshot.",
                "source_type": "url",
                "source_ref": "https://github.com/example/radar-demo",
                "input_version": "commit:abc123",
                "generated_at": "2026-09-04T00:00:00Z",
                "confidence": 0.9,
                "dimension": "engineering",
                "rating": 8,
            }
        )
        self.assertEqual(evidence.kind, "fact")
        self.assertEqual(evidence.rating, 8)

        invalid = evidence.to_dict()
        invalid["source_ref"] = ""
        with self.assertRaises(ValueError):
            ResearchEvidence.from_dict(invalid)

        invalid = evidence.to_dict()
        invalid["rating"] = 11
        with self.assertRaises(ValueError):
            ResearchEvidence.from_dict(invalid)

        invalid = evidence.to_dict()
        invalid.pop("reason")
        with self.assertRaises(ValueError):
            ResearchEvidence.from_dict(invalid)

    def test_evidence_store_is_idempotent_and_keeps_records_out_of_projects(self):
        evidence = ResearchEvidence.from_dict(
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "project_id": "radar-demo",
                "kind": "opinion",
                "claim": "Useful for learning.",
                "reason": "The claim is an explicitly labeled learning opinion.",
                "source_type": "snapshot",
                "source_ref": "run-1",
                "input_version": "snapshot-1",
                "generated_at": "2026-09-04T00:00:00Z",
                "confidence": 0.5,
                "dimension": "learning_value",
                "rating": 7,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchEvidenceStore(Path(directory))
            self.assertTrue(store.append(evidence))
            self.assertFalse(store.append(evidence))
            self.assertEqual(store.all(), [evidence])

    def test_observation_source_must_reference_an_observation_record(self):
        evidence = ResearchEvidence.from_dict(
            {
                "schema_version": 1,
                "evidence_id": "evidence-observation",
                "project_id": "radar-demo",
                "kind": "fact",
                "claim": "A recorded observation supports this fact.",
                "reason": "The source is an internal observation edge.",
                "source_type": "observation",
                "source_ref": "missing-observation",
                "input_version": "snapshot-1",
                "generated_at": "2026-09-04T00:00:00Z",
                "confidence": 0.8,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                ResearchEvidenceStore(Path(directory)).append(evidence)


if __name__ == "__main__":
    unittest.main()
