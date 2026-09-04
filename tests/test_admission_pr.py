import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

from open_radar.admission_request import AuthorizationPolicy
from open_radar.admission_controls import (
    AdmissionGuard,
    DurableRateBudgetController,
    DurableReplayStore,
    RateBudgetPolicy,
)
from open_radar.admission_transactions import AdmissionTransactionStore
from open_radar.admission_transactions import AdmissionTransaction, TransactionConflictError
from open_radar.github_provider import GitHubProvider
from open_radar.github_webhook import GitHubWebhookVerifier
from open_radar.storage import ObservationStore, ProjectStore
from open_radar.workflows.admission import AdmissionService
from open_radar.workflows.admission_pr import (
    AdmissionWorkflow,
    DeterministicAdmissionPRClient,
    MergeReconciliationError,
    MergedPullRequest,
)
from open_radar.workflows.collection import CollectionService
from open_radar.generation import render_readme
from open_radar.publisher import ObservationOnlyPublisher, PublisherArtifact
from open_radar.domain import Project


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


class AdmissionPrE2ETests(unittest.TestCase):
    def event(self, replay_store=None, delivery_id="delivery-42"):
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "body": "### Project URL\n\nhttps://github.com/example-org/radar-demo",
                "user": {"login": "contributor"},
                "labels": [],
                "created_at": "2026-09-04T00:00:00Z",
            },
            "repository": {"id": 987654321},
            "sender": {"login": "contributor"},
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        return GitHubWebhookVerifier(
            b"secret", expected_repository_id=987654321, replay_store=replay_store
        ).verify_issue_event(
            body, signature, event_name="issues", delivery_id=delivery_id
        )

    def test_prepare_merge_reconcile_is_idempotent_and_publishes_observation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            projects = ProjectStore(root)
            observations = ObservationStore(root)
            service = AdmissionService(GitHubProvider(FakeClient()), projects)
            workflow = AdmissionWorkflow(
                service,
                AuthorizationPolicy(trusted_users={"contributor"}),
                AdmissionTransactionStore(root),
                guard=AdmissionGuard(
                    AuthorizationPolicy(trusted_users={"contributor"}),
                    DurableRateBudgetController(
                        root,
                        RateBudgetPolicy(max_requests=1, max_budget_units=1),
                    ),
                ),
            )
            replay_store = DurableReplayStore(root)
            preparation = workflow.prepare(self.event(replay_store))
            self.assertEqual(preparation.transaction.status, "pr_open")
            self.assertEqual(preparation.plan.files[0][0], "data/projects/radar-demo.yaml")
            retry = workflow.prepare(self.event(replay_store, "delivery-43"))
            self.assertEqual(retry.pull_request.number, preparation.pull_request.number)
            with self.assertRaises(MergeReconciliationError):
                workflow.reconcile_merge(
                    preparation,
                    MergedPullRequest(
                        number=preparation.pull_request.number,
                        head_branch=preparation.pull_request.head_branch,
                        merged=False,
                        merge_commit_sha=None,
                        merged_by=None,
                    ),
                )
            path = workflow.reconcile_merge(
                preparation,
                MergedPullRequest(
                    number=preparation.pull_request.number,
                    head_branch=preparation.pull_request.head_branch,
                    merged=True,
                    merge_commit_sha="abc123",
                    merged_by="maintainer",
                    project=Project.from_dict(
                        {
                            **preparation.candidate.project.to_dict(),
                            "display_name": "Reviewed Radar Demo",
                        }
                    ),
                ),
            )
            self.assertTrue(path.is_file())
            self.assertEqual(len(projects.all()), 1)
            self.assertEqual(projects.load("radar-demo").display_name, "Reviewed Radar Demo")
            self.assertEqual(workflow.reconcile_merge(
                preparation,
                MergedPullRequest(
                    number=preparation.pull_request.number,
                    head_branch=preparation.pull_request.head_branch,
                    merged=True,
                    merge_commit_sha="abc123",
                    merged_by="maintainer",
                ),
            ), path)
            self.assertEqual(workflow.reconcile_merge_by_key(
                preparation.transaction.idempotency_key,
                MergedPullRequest(
                    number=preparation.pull_request.number,
                    head_branch=preparation.pull_request.head_branch,
                    merged=True,
                    merge_commit_sha="abc123",
                    merged_by="maintainer",
                ),
            ), path)

            collector = CollectionService(GitHubProvider(FakeClient()), projects, observations)
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            self.assertEqual(collector.collect_all(run_id="run-1", scheduled_at=now), 1)
            readme = render_readme(projects.all(), observations)
            observation_path = observations.month_files()[0]
            publisher = ObservationOnlyPublisher(root)
            plan = publisher.plan(
                [
                    PublisherArtifact(
                        path="README.md", content=readme, kind="readme"
                    ),
                    PublisherArtifact(
                        path="data/observations/github/2026-09.jsonl",
                        content=observation_path.read_text(encoding="utf-8"),
                        kind="observation",
                    ),
                ]
            )
            self.assertEqual(plan.paths, ("README.md", "data/observations/github/2026-09.jsonl"))
            self.assertNotIn("data/projects", plan.paths)

    def test_pr_creation_retry_reuses_creating_transaction(self):
        class FailingOnceClient:
            def __init__(self):
                self.calls = 0
                self.delegate = DeterministicAdmissionPRClient()

            def find_by_branch(self, branch_name):
                return self.delegate.find_by_branch(branch_name)

            def open_or_update(self, plan, *, existing=None):
                self.calls += 1
                if self.calls == 1:
                    self.delegate.open_or_update(plan, existing=existing)
                    raise RuntimeError("simulated provider interruption")
                return self.delegate.open_or_update(plan, existing=existing)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = AdmissionService(GitHubProvider(FakeClient()), ProjectStore(root))
            transactions = AdmissionTransactionStore(root)
            client = FailingOnceClient()
            workflow = AdmissionWorkflow(
                service,
                AuthorizationPolicy(trusted_users={"contributor"}),
                transactions,
                pr_client=client,
            )
            with self.assertRaises(RuntimeError):
                workflow.prepare(self.event())
            transaction = transactions.get("github:987654321:issue-42")
            self.assertEqual(transaction.status, "failed")
            self.assertIn("simulated provider interruption", transaction.last_error)
            preparation = workflow.prepare(self.event(delivery_id="delivery-43"))
            self.assertEqual(preparation.transaction.status, "pr_open")
            self.assertEqual(client.calls, 1)

    def test_transaction_identity_cannot_be_rebound(self):
        from dataclasses import replace

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = AdmissionTransactionStore(root)
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            transaction = AdmissionTransaction(
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
                status="pending",
                created_at=now,
                updated_at=now,
            )
            store.ensure(transaction)
            with self.assertRaises(TransactionConflictError):
                store.ensure(replace(transaction, requester="mallory"))


if __name__ == "__main__":
    unittest.main()
