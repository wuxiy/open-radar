import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_radar.admission_request import (
    AdmissionAuthorizationError,
    AdmissionRequest,
    AuthorizationPolicy,
)
from open_radar.domain import Project, RepositoryRef
from open_radar.github_provider import GitHubProvider, RepositoryMetadata
from open_radar.github_webhook import GitHubWebhookVerifier, VerifiedIssueEvent
from open_radar.generation import render_readme
from open_radar.storage import ObservationStore, ProjectStore
from open_radar.workflows.admission import (
    AdmissionMergeGateError,
    AdmissionService,
)
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


class MultiRepositoryClient(FakeClient):
    def get_repository(self, owner, repo):
        payload = dict(self.payload)
        if repo == "sdk":
            payload.update(
                {
                    "id": 100000002,
                    "name": "sdk",
                    "full_name": "example-org/sdk",
                    "html_url": "https://github.com/example-org/sdk",
                }
            )
        return payload


class MultiRepositoryFailingClient(MultiRepositoryClient):
    def get_repository(self, owner, repo):
        if repo == "sdk":
            raise RuntimeError("rate limited")
        return super().get_repository(owner, repo)


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


def multi_repository_project():
    base = project().to_dict()
    base["repositories"].append(
        {
            "provider": "github",
            "repository_id": 100000002,
            "owner": "example-org",
            "repo": "sdk",
            "role": "sdk",
        }
    )
    return Project.from_dict(base)


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
            request = AdmissionRequest.from_dict(
                {
                    "schema_version": 1,
                    "request_id": "issue-42",
                    "intake_repository_id": "987654321",
                    "issue_number": 42,
                    "project_url": "https://github.com/example-org/radar-demo",
                    "requester": "maintainer",
                    "labels": [],
                    "created_at": "2026-09-03T00:00:00Z",
                    "source_url": None,
                    "comment": None,
                }
            )
            authorized = service.build_authorized_candidate(
                request,
                AuthorizationPolicy(trusted_users={"maintainer"}),
                allow_uncontrolled=True,
            )
            event_payload = {
                "action": "opened",
                "issue": {
                    "number": 42,
                    "body": "### Project URL\n\nhttps://github.com/example-org/radar-demo",
                    "user": {"login": "maintainer"},
                    "labels": [],
                    "created_at": "2026-09-03T00:00:00Z",
                },
                "repository": {"id": 987654321},
                "sender": {"login": "maintainer"},
            }
            event_body = json.dumps(event_payload, separators=(",", ":")).encode()
            event_signature = "sha256=" + hmac.new(
                b"test-secret", event_body, hashlib.sha256
            ).hexdigest()
            verified_event_candidate = service.build_verified_event_candidate(
                GitHubWebhookVerifier(
                    b"test-secret", expected_repository_id=987654321,
                    allow_untracked_replay=True,
                ).verify_issue_event(
                    event_body,
                    event_signature,
                    event_name="issues",
                    delivery_id="delivery-42",
                ),
                AuthorizationPolicy(trusted_users={"maintainer"}),
                allow_uncontrolled=True,
            )
            self.assertEqual(verified_event_candidate.project.id, "radar-demo")
            with self.assertRaises(AdmissionAuthorizationError):
                service.build_verified_event_candidate(
                    VerifiedIssueEvent(
                        request=request,
                        action="opened",
                        sender="maintainer",
                        label_name=None,
                        delivery_id="delivery-42",
                        _verifier=object(),
                        _snapshot=(),
                    ),
                    AuthorizationPolicy(trusted_users={"maintainer"}),
                    allow_uncontrolled=True,
                )
            with self.assertRaises(AdmissionMergeGateError):
                service.admit(authorized)
            with self.assertRaises(AdmissionMergeGateError):
                service.admit(authorized, merge_confirmed=True)

    def test_verified_candidate_rejects_duck_typed_event(self):
        class ForgedEvent:
            request = None
            sender = "maintainer"
            action = "opened"
            label_name = None
            replay_managed = True

            def is_verified(self):
                return True

        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = AdmissionService(GitHubProvider(FakeClient()), ProjectStore(root))
            with self.assertRaises(AdmissionAuthorizationError):
                service.build_verified_event_candidate(
                    ForgedEvent(),
                    AuthorizationPolicy(trusted_users={"maintainer"}),
                    allow_uncontrolled=True,
                )

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

    def test_collection_collects_each_due_repository(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(multi_repository_project())
            service = CollectionService(
                GitHubProvider(MultiRepositoryClient()), projects, observations
            )
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            self.assertEqual(service.collect_all(run_id="run-1", scheduled_at=now), 2)
            self.assertEqual(
                {record.repository_id for record in observations.all()},
                {100000001, 100000002},
            )
            self.assertEqual(service.collect_all(run_id="run-2", scheduled_at=now), 0)
            self.assertEqual(service.last_skipped, ["radar-demo"])

    def test_collection_schedules_repositories_independently(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(multi_repository_project())
            service = CollectionService(
                GitHubProvider(MultiRepositoryClient()), projects, observations
            )
            first = datetime(2026, 9, 3, tzinfo=timezone.utc)
            self.assertEqual(service.collect_all(run_id="run-1", scheduled_at=first), 2)
            primary_refresh = GitHubProvider(MultiRepositoryClient()).to_observation(
                "radar-demo",
                RepositoryMetadata.from_api(PAYLOAD),
                run_id="run-primary-refresh",
                scheduled_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
                observed_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
                recorded_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            )
            observations.append(primary_refresh)
            self.assertEqual(
                service.collect_all(
                    run_id="run-2",
                    scheduled_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
                ),
                1,
            )
            current = {
                record.repository_id: record
                for record in observations.current_for("radar-demo")
            }
            self.assertEqual(
                current[100000001].observed_at,
                datetime(2026, 9, 10, tzinfo=timezone.utc),
            )
            self.assertEqual(
                current[100000002].observed_at,
                datetime(2026, 9, 11, tzinfo=timezone.utc),
            )

    def test_collection_keeps_success_when_associated_repository_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(multi_repository_project())
            service = CollectionService(
                GitHubProvider(MultiRepositoryFailingClient()), projects, observations
            )
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            self.assertEqual(service.collect_all(run_id="run-1", scheduled_at=now), 1)
            self.assertEqual(
                [record.repository_id for record in observations.all()], [100000001]
            )
            self.assertEqual(
                service.last_errors,
                ["radar-demo (github:100000002): rate limited"],
            )

    def test_collection_can_target_one_project(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(project())
            other = project(project_id="other")
            other_data = other.to_dict()
            other_data["repositories"][0].update(
                {
                    "repository_id": 100000002,
                    "repo": "sdk",
                }
            )
            projects.save(Project.from_dict(other_data))
            service = CollectionService(
                GitHubProvider(MultiRepositoryClient()), projects, observations
            )
            now = datetime(2026, 9, 3, tzinfo=timezone.utc)
            self.assertEqual(
                service.collect_all(
                    run_id="run-other",
                    scheduled_at=now,
                    project_id="other",
                ),
                1,
            )
            self.assertEqual(
                [record.project_id for record in observations.all()], ["other"]
            )
            self.assertEqual(
                service.collect_all(
                    run_id="run-main",
                    scheduled_at=now,
                    project_id="radar-demo",
                ),
                1,
            )
            with self.assertRaisesRegex(ValueError, "project does not exist: missing"):
                service.collect_all(
                    run_id="run-missing",
                    scheduled_at=now,
                    project_id="missing",
                )

    def test_targeted_collection_ignores_unrelated_invalid_project(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            projects.save(project())
            (root / "data" / "projects" / "unrelated.yaml").write_text(
                "id: [invalid\n", encoding="utf-8"
            )
            service = CollectionService(
                GitHubProvider(FakeClient()), projects, observations
            )
            self.assertEqual(
                service.collect_all(
                    run_id="run-targeted",
                    scheduled_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
                    project_id="radar-demo",
                ),
                1,
            )

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
