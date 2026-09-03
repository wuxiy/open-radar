from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_radar.domain import Project, RepositoryRef
from open_radar.github_provider import GitHubProvider
from open_radar.generation import render_readme
from open_radar.storage import ObservationStore, ProjectStore
from open_radar.workflows.admission import DuplicateRepositoryError, AdmissionService
from open_radar.workflows.collection import CollectionService


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
    def __init__(self, payload=PAYLOAD):
        self.payload = payload

    def get_repository(self, owner, repo):
        return self.payload


class FailingClient(FakeClient):
    def get_repository(self, owner, repo):
        if repo == "broken":
            raise RuntimeError("rate limited")
        return self.payload


def project(*, tracking="weekly", project_id="radar-demo"):
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
            "tracking": tracking,
        }
    )


class WorkflowTests(unittest.TestCase):
    def test_admission_creates_candidate_and_rejects_repository_duplicate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            provider = GitHubProvider(FakeClient())
            service = AdmissionService(provider, projects)
            candidate = service.build_candidate(
                "https://github.com/example-org/radar-demo",
                discovered_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
            )
            self.assertEqual(candidate.id, "radar-demo")
            service.admit(candidate)
            with self.assertRaises(DuplicateRepositoryError):
                service.admit(candidate)

    def test_collection_is_idempotent_and_skips_tracking_off(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(project())
            projects.save(project(tracking="off", project_id="off-project"))
            provider = GitHubProvider(FakeClient())
            service = CollectionService(provider, projects, observations)
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            self.assertEqual(service.collect_all(run_id="run-1", scheduled_at=now), 1)
            self.assertEqual(service.collect_all(run_id="run-2", scheduled_at=now), 0)
            self.assertEqual(service.last_skipped, ["radar-demo"])
            self.assertEqual(len(observations.all()), 1)

    def test_readme_is_deterministic_and_uses_current_observation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(project())
            service = CollectionService(GitHubProvider(FakeClient()), projects, observations)
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            service.collect_all(run_id="run-1", scheduled_at=now)

            first = render_readme(projects.all(), observations)
            second = render_readme(projects.all(), observations)
            self.assertEqual(first, second)
            self.assertIn("| [Radar Demo](https://github.com/example-org/radar-demo) | automation | watching | undecided | weekly | 42 |", first)
            self.assertIn("https://github.com/example-org/radar-demo", first)

    def test_collection_keeps_successes_when_one_project_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(project())
            broken = project(project_id="broken")
            broken = Project.from_dict(
                {
                    **broken.to_dict(),
                    "repositories": [
                        {
                            **broken.repositories[0].to_dict(),
                            "repository_id": 100000002,
                            "repo": "broken",
                        }
                    ],
                }
            )
            projects.save(broken)
            service = CollectionService(GitHubProvider(FailingClient()), projects, observations)
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            self.assertEqual(service.collect_all(run_id="run-1", scheduled_at=now), 1)
            self.assertEqual(len(service.last_errors), 1)
            self.assertEqual(len(observations.all()), 1)


if __name__ == "__main__":
    unittest.main()
