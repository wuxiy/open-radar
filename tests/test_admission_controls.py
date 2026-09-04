import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_radar.admission_controls import (
    AdmissionGuard,
    DurableRateBudgetController,
    DurableReplayStore,
    RateBudgetPolicy,
    RateBudgetExceeded,
)
from open_radar.github_webhook import GitHubWebhookVerifier, WebhookReplayError, WebhookVerificationError
from open_radar.admission_request import AuthorizationPolicy


PAYLOAD = {
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


class AdmissionControlsTests(unittest.TestCase):
    def signed(self, payload=PAYLOAD):
        body = json.dumps(payload, separators=(",", ":")).encode()
        return body, "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    def test_replay_ledger_survives_verifier_restart(self):
        with TemporaryDirectory() as directory:
            store = DurableReplayStore(Path(directory))
            body, signature = self.signed()
            verifier = GitHubWebhookVerifier(
                b"secret", expected_repository_id=987654321, replay_store=store
            )
            verifier.verify_issue_event(body, signature, event_name="issues", delivery_id="d-1")
            with self.assertRaises(WebhookReplayError):
                GitHubWebhookVerifier(
                    b"secret", expected_repository_id=987654321, replay_store=DurableReplayStore(Path(directory))
                ).verify_issue_event(body, signature, event_name="issues", delivery_id="d-1")

    def test_replay_payload_binding_cannot_be_dropped_on_retry(self):
        with TemporaryDirectory() as directory:
            store = DurableReplayStore(Path(directory))
            self.assertTrue(store.claim("d-bind", payload_sha256="a" * 64))
            with self.assertRaises(ValueError):
                store.claim("d-bind")

    def test_admission_guard_requires_durable_budget_by_default(self):
        with self.assertRaises(ValueError):
            AdmissionGuard(AuthorizationPolicy(trusted_users={"alice"}))

    def test_invalid_payload_does_not_consume_delivery(self):
        with TemporaryDirectory() as directory:
            store = DurableReplayStore(Path(directory))
            body, signature = self.signed({**PAYLOAD, "action": "deleted"})
            verifier = GitHubWebhookVerifier(b"secret", expected_repository_id=987654321, replay_store=store)
            with self.assertRaises(WebhookVerificationError):
                verifier.verify_issue_event(body, signature, event_name="issues", delivery_id="d-2")
            body, signature = self.signed()
            verifier.verify_issue_event(body, signature, event_name="issues", delivery_id="d-2")

    def test_replay_delivery_can_be_completed_or_released(self):
        with TemporaryDirectory() as directory:
            store = DurableReplayStore(Path(directory))
            self.assertTrue(store.claim("d-3"))
            self.assertFalse(store.claim("d-3"))
            self.assertTrue(store.fail("d-3", reason="transaction rolled back"))
            self.assertTrue(store.claim("d-3"))
            self.assertTrue(store.complete("d-3", idempotency_key="issue-3"))
            self.assertTrue(store.complete("d-3", idempotency_key="issue-3"))
            self.assertFalse(store.claim("d-3"))
            self.assertEqual(store.get("d-3").status, "completed")
            self.assertEqual(store.get("d-3").idempotency_key, "issue-3")

    def test_stale_processing_claim_can_be_recovered(self):
        with TemporaryDirectory() as directory:
            store = DurableReplayStore(Path(directory), processing_timeout_seconds=5)
            old = datetime(2026, 9, 4, tzinfo=timezone.utc)
            self.assertTrue(store.claim("d-4", received_at=old))
            self.assertTrue(
                store.claim("d-4", received_at=old + timedelta(seconds=6))
            )

    def test_stale_worker_cannot_complete_a_reclaimed_delivery(self):
        with TemporaryDirectory() as directory:
            first = DurableReplayStore(Path(directory), processing_timeout_seconds=5)
            second = DurableReplayStore(Path(directory), processing_timeout_seconds=5)
            old = datetime(2026, 9, 4, tzinfo=timezone.utc)
            self.assertTrue(first.claim("d-5", received_at=old))
            self.assertTrue(second.claim("d-5", received_at=old + timedelta(seconds=6)))
            self.assertFalse(first.complete("d-5", idempotency_key="stale"))
            self.assertTrue(second.complete("d-5", idempotency_key="fresh"))

    def test_rate_and_budget_are_durable_and_idempotent(self):
        with TemporaryDirectory() as directory:
            controller = DurableRateBudgetController(
                Path(directory), RateBudgetPolicy(max_requests=2, max_budget_units=3, window_seconds=60)
            )
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            first = controller.reserve("alice", "99", units=2, reservation_key="issue-1", at=now)
            self.assertFalse(first.replayed)
            replay = DurableRateBudgetController(
                Path(directory), RateBudgetPolicy(max_requests=2, max_budget_units=3, window_seconds=60)
            ).reserve("alice", "99", units=2, reservation_key="issue-1", at=now + timedelta(seconds=1))
            self.assertTrue(replay.replayed)
            with self.assertRaises(RateBudgetExceeded):
                controller.reserve("alice", "99", units=2, reservation_key="issue-2", at=now + timedelta(seconds=2))
            later = controller.reserve("alice", "99", units=3, reservation_key="issue-3", at=now + timedelta(seconds=61))
            self.assertTrue(later.allowed)


if __name__ == "__main__":
    unittest.main()
