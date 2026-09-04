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
                            "--discovered-at",
                            "2026-09-04T00:00:00Z",
                        ]
                    ),
                    0,
                )
            self.assertTrue((root / "data" / "projects" / "radar-demo.yaml").is_file())

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


if __name__ == "__main__":
    unittest.main()
