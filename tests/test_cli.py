from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import shutil
import os

import yaml

from open_radar.cli import main
from open_radar.domain import ObservationRecord, Project
from open_radar.github_provider import GitHubProvider
from open_radar.storage import ObservationStore, ProjectStore
from open_radar.admission_controls import DurableRateBudgetController, DurableReplayStore, RateBudgetPolicy
from open_radar.admission_transactions import AdmissionTransaction, AdmissionTransactionStore
from open_radar.change_detection import ChangeEventStore
from open_radar.research import ResearchEvidence, ResearchEvidenceStore
from open_radar.scoring import Context, ContextStore
from datetime import datetime, timezone

ROOT = Path(__file__).parents[1]


PAYLOAD = {
    "id": 100000001,
    "name": "radar-demo",
    "full_name": "example-org/radar-demo",
    "html_url": "https://github.com/example-org/radar-demo",
    "description": "A demo",
    "stargazers_count": 42,
    "forks_count": 3,
    "archived": False,
    "language": "Python",
    "topics": ["automation"],
    "license": {"spdx_id": "MIT"},
}


class FakeClient:
    def get_repository(self, owner, repo):
        return PAYLOAD


class CliTests(unittest.TestCase):
    def test_ingest_prints_candidate_without_writing_by_default(self):
        with TemporaryDirectory() as directory:
            shutil.copytree(ROOT / "data" / "taxonomy", Path(directory) / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", Path(directory) / "schemas")
            output = StringIO()
            with patch("open_radar.cli.GitHubApiClient", return_value=FakeClient()):
                with redirect_stdout(output):
                    result = main(
                        [
                            "ingest",
                            "https://github.com/example-org/radar-demo",
                            "--root",
                            directory,
                            "--discovered-at",
                            "2026-09-03T00:00:00Z",
                        ]
                    )
            self.assertEqual(result, 0)
            self.assertIn("id: radar-demo", output.getvalue())
            self.assertFalse((Path(directory) / "data" / "projects" / "radar-demo.yaml").exists())

    def test_ingest_write_requires_and_checks_authorized_request(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            with patch("open_radar.cli.GitHubApiClient", return_value=FakeClient()), patch.dict(
                os.environ, {"OPEN_RADAR_TRUSTED_USERS": "maintainer"}, clear=False
            ):
                self.assertEqual(
                    main(
                        [
                            "ingest",
                            "https://github.com/example-org/radar-demo",
                            "--root",
                            directory,
                            "--write",
                            "--discovered-at",
                            "2026-09-04T00:00:00Z",
                        ]
                    ),
                    1,
                )
                self.assertEqual(
                    main(
                        [
                            "ingest",
                            "https://github.com/example-org/radar-demo",
                            "--root",
                            directory,
                            "--write",
                            "--request-id",
                            "issue-42",
                            "--requester",
                            "maintainer",
                            "--intake-repository-id",
                            "987654321",
                            "--issue-number",
                            "42",
                            "--merge-confirmed",
                            "--merge-commit-sha",
                            "cli-merge-1",
                            "--merged-by",
                            "maintainer",
                            "--discovered-at",
                            "2026-09-04T00:00:00Z",
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "data" / "projects" / "radar-demo.yaml").exists())

    def test_ingest_write_rejects_untrusted_request_without_traceback(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            with patch("open_radar.cli.GitHubApiClient", return_value=FakeClient()):
                self.assertEqual(
                    main(
                        [
                            "ingest",
                            "https://github.com/example-org/radar-demo",
                            "--root",
                            directory,
                            "--write",
                            "--request-id",
                            "issue-42",
                            "--requester",
                            "contributor",
                            "--intake-repository-id",
                            "987654321",
                            "--issue-number",
                            "42",
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "data" / "projects" / "radar-demo.yaml").exists())
            manifest_lines = list((root / "data" / "runs").glob("*.jsonl"))
            self.assertEqual(len(manifest_lines), 1)
            manifest = json.loads(manifest_lines[0].read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(manifest["status"], "pending")
            self.assertEqual(manifest["metadata"]["issue_number"], 42)
            self.assertIn("comment_preview", manifest["metadata"])

    def test_generate_and_validate_commands(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            project = Project.from_dict(
                {
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
            )
            ProjectStore(root).save(project)
            self.assertEqual(main(["generate", "--root", directory, "--force"]), 0)
            self.assertTrue((root / "README.md").is_file())
            self.assertEqual(main(["validate", "--root", directory]), 0)

    def test_validate_rejects_observation_for_unknown_project(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            record = ObservationRecord.from_dict(
                {
                    "schema_version": 1,
                    "record_type": "observation",
                    "event_id": "event-1",
                    "collection_key": "slot-1",
                    "run_id": "run-1",
                    "project_id": "missing-project",
                    "provider": "github",
                    "repository_id": 100000001,
                    "scheduled_at": "2026-09-03T00:00:00Z",
                    "observed_at": "2026-09-03T00:00:00Z",
                    "recorded_at": "2026-09-03T00:00:00Z",
                    "collector_version": "collector-v1",
                    "source": "github-api",
                    "metrics": {},
                    "facts": {},
                    "unavailable": {},
                }
            )
            ObservationStore(root).append(record)
            self.assertEqual(main(["validate", "--root", directory]), 1)

    def test_validate_handles_control_ledgers_and_admission_transactions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            DurableReplayStore(root).claim("delivery-1")
            DurableRateBudgetController(root, RateBudgetPolicy(2, 2)).reserve("alice", "9", reservation_key="issue-1")
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            AdmissionTransactionStore(root).ensure(
                AdmissionTransaction(
                    schema_version=1,
                    idempotency_key="github:9:issue-1",
                    request_id="issue-1",
                    intake_repository_id="9",
                    issue_number=1,
                    project_id="radar-demo",
                    repository_id=100000001,
                    project_url="https://github.com/example-org/radar-demo",
                    requester="alice",
                    branch_name="admission/github-9-issue-1",
                    status="pr_open",
                    created_at=now,
                    updated_at=now,
                    pr_number=10001,
                    pr_url="https://github.com/open-radar/admissions/pull/10001",
                )
            )
            self.assertEqual(main(["validate", "--root", directory]), 0)

    def test_detect_changes_is_idempotent_and_records_manifest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            ProjectStore(root).save(
                Project.from_dict(
                    {
                        "schema_version": 1,
                        "id": "radar-demo",
                        "display_name": "Radar Demo",
                        "aliases": [],
                        "repositories": [
                            {
                                "provider": "github",
                                "repository_id": 100000001,
                                "owner": "example",
                                "repo": "radar-demo",
                                "role": "primary",
                            }
                        ],
                        "primary_category": "automation",
                        "tags": ["automation"],
                        "discovery_sources": [],
                        "research_stage": "watching",
                        "decision": "undecided",
                        "tracking": "weekly",
                        "personal_notes": "",
                    }
                )
            )
            observed = []
            for event_id, observed_at, archived in (
                ("obs-1", "2026-09-01T00:00:00Z", False),
                ("obs-2", "2026-09-02T00:00:00Z", True),
            ):
                observed.append(
                    ObservationRecord.from_dict(
                        {
                            "schema_version": 1,
                            "record_type": "observation",
                            "event_id": event_id,
                            "collection_key": f"slot-{event_id}",
                            "run_id": f"run-{event_id}",
                            "project_id": "radar-demo",
                            "provider": "github",
                            "repository_id": 100000001,
                            "scheduled_at": observed_at,
                            "observed_at": observed_at,
                            "recorded_at": observed_at,
                            "collector_version": "collector-v1",
                            "source": "fixture",
                            "metrics": {"stars": 100},
                            "facts": {"archived": archived, "license_spdx": "MIT"},
                            "unavailable": {},
                        }
                    )
                )
            ObservationStore(root).append_batch(observed)

            self.assertEqual(main(["detect-changes", "--root", directory]), 0)
            self.assertEqual(main(["detect-changes", "--root", directory]), 0)
            self.assertEqual(len(ChangeEventStore(root).all()), 1)
            manifests = list((root / "data" / "runs").glob("*.jsonl"))
            self.assertEqual(len(manifests), 1)
            entries = [json.loads(line) for line in manifests[0].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(entries[-1]["kind"], "detect-changes")
            self.assertEqual(entries[-1]["counts"]["events_appended"], 0)
            proposals = StringIO()
            with redirect_stdout(proposals):
                self.assertEqual(main(["propose-analysis", "--root", directory]), 0)
            proposal = json.loads(proposals.getvalue().strip())
            self.assertTrue(proposal["trigger_event_id"].startswith("change-"))
            self.assertFalse((root / "data" / "proposals").exists())
            self.assertEqual(main(["validate", "--root", directory]), 0)

    def test_propose_score_and_report_commands_are_offline_and_historical(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data" / "taxonomy", root / "data" / "taxonomy")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            ProjectStore(root).save(
                Project.from_dict(
                    {
                        "schema_version": 1,
                        "id": "radar-demo",
                        "display_name": "Radar Demo",
                        "aliases": [],
                        "repositories": [{"provider": "github", "repository_id": 100000001, "owner": "example", "repo": "radar-demo", "role": "primary"}],
                        "primary_category": "automation",
                        "tags": ["automation"],
                        "discovery_sources": [],
                        "research_stage": "watching",
                        "decision": "undecided",
                        "tracking": "weekly",
                    }
                )
            )
            context = Context.from_dict(
                {
                    "schema_version": 1,
                    "context_id": "open-scope",
                    "name": "Open Scope",
                    "goal": "Select useful tools.",
                    "technical_questions": ["Does it fit?"],
                    "priority": 4,
                    "project_ids": ["radar-demo"],
                }
            )
            ContextStore(root).save(context)
            for dimension, rating in (("innovation", 8), ("engineering", 7), ("relevance", 9), ("activity", 6), ("learning_value", 10)):
                value = {
                    "schema_version": 1,
                    "evidence_id": f"evidence-{dimension.replace('_', '-')}",
                    "project_id": "radar-demo",
                    "kind": "fact",
                    "claim": f"{dimension} evidence",
                    "reason": "Recorded for deterministic CLI tests.",
                    "source_type": "snapshot",
                    "source_ref": "run-1",
                    "input_version": "snapshot-1",
                    "generated_at": "2026-09-01T00:00:00Z",
                    "confidence": 0.9,
                    "dimension": dimension,
                    "rating": rating,
                }
                if dimension == "relevance":
                    value["context_id"] = "open-scope"
                if dimension == "engineering":
                    value["prompt_version"] = "research-prompt/1"
                ResearchEvidenceStore(root).append(ResearchEvidence.from_dict(value))
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["score", "--root", directory, "--project-id", "radar-demo", "--context-id", "open-scope", "--evaluated-at", "2026-09-02T00:00:00Z"]),
                    0,
                )
            self.assertIn('"total_score":80.5', output.getvalue())
            self.assertEqual(
                main(["report", "--root", directory, "--cutoff-at", "2026-09-02T00:00:00Z", "--context-id", "open-scope"]),
                0,
            )
            self.assertTrue((root / "reports" / "report-monthly-2026-09.md").is_file())
            report_metadata = json.loads((root / "reports" / "report-monthly-2026-09.json").read_text(encoding="utf-8"))
            self.assertEqual(report_metadata["prompt_versions"], ["research-prompt/1"])
            self.assertEqual(main(["validate", "--root", directory]), 0)


if __name__ == "__main__":
    unittest.main()
