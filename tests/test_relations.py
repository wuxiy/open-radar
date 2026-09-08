from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest

import yaml

from open_radar.cli import main
from open_radar.contracts.schema import SchemaValidator
from open_radar.domain import Project
from open_radar.relations import (
    DuplicateRelationError,
    Relation,
    RelationEndpoint,
    RelationStore,
)
from open_radar.research import ResearchEvidence, ResearchEvidenceStore
from open_radar.scoring import Context, ContextStore
from open_radar.storage import ProjectStore


ROOT = Path(__file__).parents[1]


def _relation_root(directory: str) -> Path:
    root = Path(directory)
    shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
    shutil.copytree(ROOT / "schemas", root / "schemas")
    return root


def _project(project_id: str = "radar-demo") -> Project:
    return Project.from_dict(
        {
            "schema_version": 1,
            "id": project_id,
            "display_name": project_id.replace("-", " ").title(),
            "aliases": [],
            "repositories": [
                {
                    "provider": "github",
                    "repository_id": 100000001 if project_id == "radar-demo" else 100000002,
                    "owner": "example-org",
                    "repo": project_id,
                    "role": "primary",
                }
            ],
            "primary_category": "automation",
            "tags": ["automation"],
            "discovery_sources": [
                {
                    "type": "manual",
                    "url": f"https://github.com/example-org/{project_id}",
                    "discovered_at": "2026-09-08T00:00:00Z",
                }
            ],
            "research_stage": "researching",
            "decision": "reference",
            "tracking": "weekly",
            "personal_notes": "",
        }
    )


def _relation(
    *,
    relation_id: str = "radar-demo-supports-open-scope",
    source: dict[str, str] | None = None,
    target: dict[str, str] | None = None,
    relation_type: str = "supports",
    direction: str = "directed",
) -> Relation:
    return Relation.from_dict(
        {
            "schema_version": 1,
            "relation_id": relation_id,
            "source": source or {"kind": "project", "id": "radar-demo"},
            "target": target or {"kind": "context", "id": "open-scope"},
            "relation_type": relation_type,
            "direction": direction,
            "reason": "The project supports the selected private technical context.",
            "evidence_ids": ["evidence-supports"],
        }
    )


class RelationContractTests(unittest.TestCase):
    def test_relation_round_trip_uses_typed_endpoints_and_evidence(self):
        relation = _relation()
        self.assertEqual(relation.source, RelationEndpoint("project", "radar-demo"))
        self.assertEqual(relation.target, RelationEndpoint("context", "open-scope"))
        self.assertEqual(relation.evidence_ids, ("evidence-supports",))
        self.assertEqual(Relation.from_dict(relation.to_dict()), relation)
        SchemaValidator(ROOT).validate("relation.v1.json", relation.to_dict())

    def test_relation_rejects_self_edges_and_noncanonical_symmetric_edges(self):
        invalid = _relation().to_dict()
        invalid["target"] = {"kind": "project", "id": "radar-demo"}
        with self.assertRaises(ValueError):
            Relation.from_dict(invalid)

    def test_relation_store_rejects_a_direction_not_allowed_by_its_controlled_type(self):
        invalid = _relation(relation_type="alternative-to", direction="directed")
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                RelationStore(_relation_root(directory)).save(invalid)

        invalid = _relation().to_dict()
        invalid["relation_type"] = "alternative-to"
        invalid["direction"] = "symmetric"
        with self.assertRaises(ValueError):
            Relation.from_dict(invalid)


class RelationStoreTests(unittest.TestCase):
    def test_store_is_idempotent_rejects_semantic_duplicates_and_finds_both_symmetric_endpoints(self):
        symmetric = _relation(
            relation_id="open-scope-alternative-radar-demo",
            source={"kind": "context", "id": "open-scope"},
            target={"kind": "project", "id": "radar-demo"},
            relation_type="alternative-to",
            direction="symmetric",
        )
        with TemporaryDirectory() as directory:
            store = RelationStore(_relation_root(directory))
            destination = store.save(symmetric)
            self.assertTrue(destination.is_file())
            self.assertEqual(store.save(symmetric), destination)
            self.assertEqual(
                store.for_endpoint(RelationEndpoint("project", "radar-demo")), [symmetric]
            )
            self.assertEqual(
                store.for_endpoint(RelationEndpoint("context", "open-scope")), [symmetric]
            )
            view = symmetric.view_for_endpoint(RelationEndpoint("project", "radar-demo"))
            self.assertEqual(view["query_endpoint"], {"kind": "project", "id": "radar-demo"})
            self.assertEqual(view["other_endpoint"], {"kind": "context", "id": "open-scope"})

            duplicate = _relation(
                relation_id="same-relation-different-id",
                source={"kind": "context", "id": "open-scope"},
                target={"kind": "project", "id": "radar-demo"},
                relation_type="alternative-to",
                direction="symmetric",
            )
            with self.assertRaises(DuplicateRelationError):
                store.save(duplicate)

    def test_store_rejects_relation_id_that_does_not_match_its_filename(self):
        relation = _relation()
        with TemporaryDirectory() as directory:
            store = RelationStore(_relation_root(directory))
            store.directory.mkdir(parents=True)
            (store.directory / "wrong-name.yaml").write_text(
                "schema_version: 1\n"
                "relation_id: radar-demo-supports-open-scope\n"
                "source:\n  kind: project\n  id: radar-demo\n"
                "target:\n  kind: context\n  id: open-scope\n"
                "relation_type: supports\n"
                "direction: directed\n"
                "reason: The project supports the selected private technical context.\n"
                "evidence_ids:\n  - evidence-supports\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                store.all()


class RelationCliTests(unittest.TestCase):
    def _checkout_with_relation(self, directory: str) -> Path:
        root = _relation_root(directory)
        ProjectStore(root).save(_project())
        ContextStore(root).save(
            Context.from_dict(
                {
                    "schema_version": 1,
                    "context_id": "open-scope",
                    "name": "Open Scope",
                    "goal": "Select useful technology.",
                    "technical_questions": ["Does it fit?"],
                    "priority": 4,
                }
            )
        )
        ResearchEvidenceStore(root).append(
            ResearchEvidence.from_dict(
                {
                    "schema_version": 1,
                    "evidence_id": "evidence-supports",
                    "project_id": "radar-demo",
                    "kind": "fact",
                    "claim": "The project supports the selected context.",
                    "reason": "The documented capability matches the selected context.",
                    "source_type": "url",
                    "source_ref": "https://github.com/example-org/radar-demo",
                    "input_version": "snapshot-1",
                    "generated_at": "2026-09-08T00:00:00Z",
                    "confidence": 0.9,
                    "dimension": "relevance",
                    "rating": 8,
                    "context_id": "open-scope",
                }
            )
        )
        RelationStore(root).save(_relation())
        return root

    def test_relations_query_is_read_only_and_filters_by_typed_endpoint(self):
        with TemporaryDirectory() as directory:
            root = self._checkout_with_relation(directory)
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["relations", "--root", directory, "--project-id", "radar-demo"]),
                    0,
                )
            self.assertIn('"relation_id":"radar-demo-supports-open-scope"', output.getvalue())
            self.assertIn('"other_endpoint":{"id":"open-scope","kind":"context"}', output.getvalue())
            self.assertEqual(before, sorted(path.relative_to(root) for path in root.rglob("*")))

    def test_relations_query_rejects_unknown_endpoint(self):
        with TemporaryDirectory() as directory:
            self._checkout_with_relation(directory)
            errors = StringIO()
            with redirect_stderr(errors):
                self.assertEqual(
                    main(["relations", "--root", directory, "--context-id", "missing-context"]),
                    1,
                )
            self.assertIn("relations failed", errors.getvalue())

    def test_context_store_rejects_file_identity_mismatch(self):
        with TemporaryDirectory() as directory:
            root = _relation_root(directory)
            contexts = root / "data" / "contexts"
            contexts.mkdir(parents=True)
            (contexts / "wrong-name.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "context_id": "open-scope",
                        "name": "Open Scope",
                        "goal": "Select useful technology.",
                        "technical_questions": ["Does it fit?"],
                        "priority": 4,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                ContextStore(root).load("wrong-name")

    def test_relations_query_rejects_invalid_cross_file_relation(self):
        with TemporaryDirectory() as directory:
            root = self._checkout_with_relation(directory)
            relation = _relation().to_dict()
            relation["target"] = {"kind": "project", "id": "missing-project"}
            relation["relation_type"] = "uncontrolled-type"
            relation["evidence_ids"] = ["evidence-missing"]
            (root / "data" / "relations" / "radar-demo-supports-open-scope.yaml").write_text(
                yaml.safe_dump(relation, sort_keys=False), encoding="utf-8"
            )
            errors = StringIO()
            with redirect_stderr(errors):
                self.assertEqual(
                    main(["relations", "--root", directory, "--project-id", "radar-demo"]),
                    1,
                )
            self.assertIn("unknown relation type", errors.getvalue())

    def test_validate_rejects_unknown_relation_endpoints_types_and_evidence(self):
        with TemporaryDirectory() as directory:
            root = self._checkout_with_relation(directory)
            relation = _relation().to_dict()
            relation["target"] = {"kind": "project", "id": "missing-project"}
            relation["relation_type"] = "uncontrolled-type"
            relation["evidence_ids"] = ["evidence-missing"]
            (root / "data" / "relations" / "radar-demo-supports-open-scope.yaml").write_text(
                yaml.safe_dump(relation, sort_keys=False), encoding="utf-8"
            )
            errors = StringIO()
            with redirect_stderr(errors):
                self.assertEqual(main(["validate", "--root", directory]), 1)
            self.assertIn("relation radar-demo-supports-open-scope", errors.getvalue())
            self.assertIn("unknown relation type", errors.getvalue())

    def test_validate_rejects_evidence_not_bound_to_relation_project_endpoint(self):
        with TemporaryDirectory() as directory:
            root = self._checkout_with_relation(directory)
            ProjectStore(root).save(_project("other-demo"))
            ResearchEvidenceStore(root).append(
                ResearchEvidence.from_dict(
                    {
                        "schema_version": 1,
                        "evidence_id": "evidence-other-project",
                        "project_id": "other-demo",
                        "kind": "fact",
                        "claim": "The other project supports a separate context.",
                        "reason": "The source belongs to the other project.",
                        "source_type": "url",
                        "source_ref": "https://github.com/example-org/other-demo",
                        "input_version": "snapshot-1",
                        "generated_at": "2026-09-08T00:00:00Z",
                        "confidence": 0.9,
                    }
                )
            )
            relation = _relation().to_dict()
            relation["evidence_ids"] = ["evidence-other-project"]
            (root / "data" / "relations" / "radar-demo-supports-open-scope.yaml").write_text(
                yaml.safe_dump(relation, sort_keys=False), encoding="utf-8"
            )
            errors = StringIO()
            with redirect_stderr(errors):
                self.assertEqual(main(["validate", "--root", directory]), 1)
            self.assertIn("evidence does not support project endpoint: radar-demo", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
