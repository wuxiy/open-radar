import hashlib
import hmac
import json
from dataclasses import replace
import unittest

from open_radar.github_webhook import (
    GitHubWebhookVerifier,
    WebhookVerificationError,
)
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


class GitHubWebhookTests(unittest.TestCase):
    def signed(self, payload=PAYLOAD, secret=b"test-secret"):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return body, f"sha256={digest}"

    def test_valid_signature_yields_verified_issue_request(self):
        body, signature = self.signed()
        event = GitHubWebhookVerifier(
            b"test-secret", expected_repository_id=987654321
        ).verify_issue_event(
            body,
            signature,
            event_name="issues",
            delivery_id="delivery-1",
        )
        self.assertEqual(event.request.request_id, "issue-42")
        self.assertEqual(event.request.idempotency_key, "github:987654321:issue-42")
        self.assertEqual(event.delivery_id, "delivery-1")
        self.assertEqual(event.sender, "contributor")
        self.assertIsNone(event.label_name)
        self.assertEqual(event.action, "opened")
        self.assertFalse(replace(event, sender="maintainer").is_verified())

    def test_invalid_signature_never_parses_payload(self):
        body, _ = self.signed()
        with self.assertRaises(WebhookVerificationError):
            GitHubWebhookVerifier(
                b"test-secret", expected_repository_id=987654321
            ).verify_issue_event(
                body,
                "sha256=" + ("0" * 64),
                event_name="issues",
                delivery_id="delivery-1",
            )

    def test_signature_from_another_repository_is_rejected(self):
        body, signature = self.signed()
        with self.assertRaises(WebhookVerificationError):
            GitHubWebhookVerifier(
                b"test-secret", expected_repository_id=123
            ).verify_issue_event(
                body,
                signature,
                event_name="issues",
                delivery_id="delivery-1",
            )

    def test_wrong_event_or_unsupported_action_is_rejected(self):
        body, signature = self.signed()
        verifier = GitHubWebhookVerifier(
            b"test-secret", expected_repository_id=987654321
        )
        with self.assertRaises(WebhookVerificationError):
            verifier.verify_issue_event(
                body,
                signature,
                event_name="pull_request",
                delivery_id="delivery-1",
            )
        labeled_body, labeled_signature = self.signed({**PAYLOAD, "action": "deleted"})
        with self.assertRaises(WebhookVerificationError):
            verifier.verify_issue_event(
                labeled_body,
                labeled_signature,
                event_name="issues",
                delivery_id="delivery-1",
            )
        for malformed_action in (None, [], {}):
            malformed_body, malformed_signature = self.signed(
                {**PAYLOAD, "action": malformed_action}
            )
            with self.assertRaises(WebhookVerificationError):
                verifier.verify_issue_event(
                    malformed_body,
                    malformed_signature,
                    event_name="issues",
                    delivery_id="delivery-1",
                )

    def test_labeled_event_exposes_sender_for_policy_authorization(self):
        payload = {
            **PAYLOAD,
            "action": "labeled",
            "issue": {
                **PAYLOAD["issue"],
                "labels": [{"name": "approved-for-processing"}],
            },
            "label": {"name": "approved-for-processing"},
            "sender": {"login": "maintainer"},
        }
        body, signature = self.signed(payload)
        event = GitHubWebhookVerifier(
            b"test-secret", expected_repository_id=987654321
        ).verify_issue_event(
            body,
            signature,
            event_name="issues",
            delivery_id="delivery-2",
        )
        policy = AuthorizationPolicy(trusted_users={"maintainer"})
        self.assertTrue(
            policy.evaluate_event(
                event.request,
                actor=event.sender,
                action=event.action,
                label=event.label_name,
            ).authorized
        )
        self.assertFalse(
            policy.evaluate_event(
                event.request,
                actor="contributor",
                action=event.action,
                label=event.label_name,
            ).authorized
        )

    def test_malformed_signature_and_payload_are_rejected(self):
        verifier = GitHubWebhookVerifier(
            b"test-secret", expected_repository_id=987654321
        )
        with self.assertRaises(WebhookVerificationError):
            verifier.verify_issue_event(
                b"{}",
                "not-a-signature",
                event_name="issues",
                delivery_id="delivery-1",
            )
        with self.assertRaises(WebhookVerificationError):
            body, signature = self.signed({k: v for k, v in PAYLOAD.items() if k != "sender"})
            verifier.verify_issue_event(
                body,
                signature,
                event_name="issues",
                delivery_id="delivery-1",
            )
        with self.assertRaises(WebhookVerificationError):
            body, signature = self.signed()
            verifier.verify_issue_event(
                body,
                signature,
                event_name="issues",
                delivery_id="",
            )
        with self.assertRaises(WebhookVerificationError):
            body, signature = self.signed()
            GitHubWebhookVerifier(
                b"test-secret", expected_repository_id=987654321, max_body_bytes=1
            ).verify_issue_event(
                body,
                signature,
                event_name="issues",
                delivery_id="delivery-1",
            )
        with self.assertRaises(WebhookVerificationError):
            verifier.verify_issue_event(
                b"{}",
                "sha256=" + ("٠" * 64),
                event_name="issues",
                delivery_id="delivery-1",
            )
        malformed_body = b"not-json"
        malformed_signature = "sha256=" + hmac.new(
            b"test-secret", malformed_body, hashlib.sha256
        ).hexdigest()
        with self.assertRaises(WebhookVerificationError):
            verifier.verify_issue_event(
                malformed_body,
                malformed_signature,
                event_name="issues",
                delivery_id="delivery-1",
            )


if __name__ == "__main__":
    unittest.main()
