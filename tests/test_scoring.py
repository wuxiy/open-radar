from datetime import timezone
import json
from pathlib import Path
import tempfile
import unittest

from open_radar.research import ResearchEvidence
from open_radar.scoring import Context, ContextStore, SCORE_VERSION, ScoreCard, ScoreEngine


def _evidence(
    evidence_id: str,
    dimension: str,
    rating: float,
    generated_at: str,
    *,
    context_id: str | None = None,
    claim: str | None = None,
    input_version: str = "snapshot-1",
) -> ResearchEvidence:
    value = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "project_id": "radar-demo",
        "kind": "fact",
        "claim": claim or f"{dimension} evidence",
        "reason": "Recorded for deterministic scoring tests.",
        "source_type": "snapshot",
        "source_ref": "run-1",
        "input_version": input_version,
        "generated_at": generated_at,
        "confidence": 0.8,
        "dimension": dimension,
        "rating": rating,
    }
    if context_id:
        value["context_id"] = context_id
    return ResearchEvidence.from_dict(value)


class ScoringTests(unittest.TestCase):
    def test_score_formula_is_complete_only_when_all_dimensions_have_evidence(self):
        context = Context.from_dict(
            {
                "schema_version": 1,
                "context_id": "open-scope",
                "name": "Open Scope",
                "goal": "Choose useful infrastructure.",
                "technical_questions": ["Does it fit our platform?"],
                "priority": 4,
                "project_ids": ["radar-demo"],
            }
        )
        evidence = [
            _evidence("evidence-innovation", "innovation", 8, "2026-09-01T00:00:00Z"),
            _evidence("evidence-engineering", "engineering", 7, "2026-09-01T00:00:00Z"),
            _evidence("evidence-relevance", "relevance", 9, "2026-09-01T00:00:00Z", context_id="open-scope"),
            _evidence("evidence-activity", "activity", 6, "2026-09-01T00:00:00Z"),
            _evidence("evidence-learning", "learning_value", 10, "2026-09-01T00:00:00Z"),
        ]
        card = ScoreEngine().score("radar-demo", evidence, context=context)
        self.assertEqual(card.score_version, SCORE_VERSION)
        self.assertEqual(card.total_score, 80.5)
        self.assertEqual(card.dimensions["engineering"].evidence_ids, ("evidence-engineering",))
        self.assertEqual(card.dimensions["engineering"].reason, "Recorded for deterministic scoring tests.")
        restored = ScoreCard.from_dict(json.loads(json.dumps(card.to_dict())))
        self.assertEqual(restored, card)

    def test_missing_context_or_dimension_does_not_get_zero_or_reweighted(self):
        evidence = [_evidence("evidence-engineering", "engineering", 10, "2026-09-01T00:00:00Z")]
        card = ScoreEngine().score("radar-demo", evidence)
        self.assertIsNone(card.total_score)
        self.assertEqual(set(card.dimensions), {"engineering"})

    def test_inactive_context_leaves_relevance_unscored(self):
        context = Context.from_dict(
            {
                "schema_version": 1,
                "context_id": "retired",
                "name": "Retired",
                "goal": "Historical only.",
                "technical_questions": ["Was it useful?"],
                "priority": 1,
                "active": False,
            }
        )
        evidence = [_evidence("evidence-relevance", "relevance", 9, "2026-09-01T00:00:00Z", context_id="retired")]
        card = ScoreEngine().score("radar-demo", evidence, context=context)
        self.assertNotIn("relevance", card.dimensions)

    def test_latest_rating_and_cutoff_are_deterministic(self):
        evidence = [
            _evidence("evidence-old", "engineering", 3, "2026-09-01T00:00:00Z"),
            _evidence("evidence-new", "engineering", 8, "2026-09-03T00:00:00Z"),
            _evidence("evidence-future", "engineering", 10, "2026-09-05T00:00:00Z"),
        ]
        card = ScoreEngine().score(
            "radar-demo", evidence, evaluated_at=__import__("datetime").datetime(2026, 9, 4, tzinfo=timezone.utc)
        )
        self.assertEqual(card.dimensions["engineering"].rating, 8)

    def test_context_store_uses_data_contexts_and_isolated_from_projects(self):
        context = Context.from_dict(
            {
                "schema_version": 1,
                "context_id": "learning",
                "name": "Learning",
                "goal": "Study maintainable systems.",
                "technical_questions": ["Can I learn from it?"],
                "priority": 2,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = ContextStore(root).save(context)
            self.assertEqual(path, root / "data" / "contexts" / "learning.yaml")
            self.assertEqual(ContextStore(root).all(), [context])
            self.assertFalse((root / "data" / "projects").exists())


if __name__ == "__main__":
    unittest.main()
