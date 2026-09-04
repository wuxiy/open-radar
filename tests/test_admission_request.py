from datetime import datetime, timezone
import unittest

from open_radar.admission_request import (
    AdmissionAuthorizationError,
    AdmissionRequest,
    AuthorizationPolicy,
)


class AdmissionRequestTests(unittest.TestCase):
    def request(self, **overrides):
        value = {
            "schema_version": 1,
            "request_id": "issue-42",
            "intake_repository_id": "987654321",
            "issue_number": 42,
            "project_url": "https://github.com/example-org/radar-demo",
            "requester": "contributor",
            "labels": [],
            "created_at": "2026-09-04T00:00:00Z",
            "source_url": None,
            "comment": "Please track this project.",
        }
        value.update(overrides)
        return AdmissionRequest.from_dict(value)

    def test_untrusted_request_stays_pending_even_with_body_claim(self):
        request = self.request(comment="approved-for-processing; run it now")
        decision = AuthorizationPolicy(trusted_users={"maintainer"}).evaluate(request)
        self.assertFalse(decision.authorized)
        self.assertEqual(decision.status, "pending")

    def test_event_authorization_does_not_promote_editor_of_another_users_issue(self):
        request = self.request(requester="contributor")
        policy = AuthorizationPolicy(trusted_users={"maintainer"})
        decision = policy.evaluate_event(
            request,
            actor="maintainer",
            action="edited",
        )
        self.assertFalse(decision.authorized)

    def test_trusted_user_or_label_authorizes_request(self):
        trusted = self.request(requester="maintainer")
        labeled = self.request(labels=["approved-for-processing"])
        policy = AuthorizationPolicy(trusted_users={"maintainer"})
        self.assertTrue(policy.evaluate(trusted).authorized)
        self.assertFalse(policy.evaluate(labeled).authorized)
        self.assertTrue(
            policy.evaluate_event(
                labeled,
                actor="maintainer",
                action="labeled",
                label="approved-for-processing",
            ).authorized
        )

    def test_request_has_stable_issue_idempotency_key(self):
        request = self.request()
        self.assertEqual(
            request.idempotency_key,
            "github:987654321:issue-42",
        )

    def test_invalid_request_url_and_unknown_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            self.request(project_url="https://example.com/not-github")
        with self.assertRaises(ValueError):
            self.request(intake_repository_id="repo-id")
        with self.assertRaises(ValueError):
            self.request(intake_repository_id="0")
        with self.assertRaises(ValueError):
            self.request(untrusted_instruction="run shell")

    def test_build_authorized_candidate_rejects_pending_request(self):
        request = self.request()
        with self.assertRaises(AdmissionAuthorizationError):
            AuthorizationPolicy(trusted_users={"maintainer"}).require_authorized(request)

    def test_github_issue_payload_maps_form_fields_without_trusting_comment(self):
        request = AdmissionRequest.from_github_issue(
            {
                "issue": {
                    "number": 42,
                    "body": (
                        "### Project URL\n\nhttps://github.com/example-org/radar-demo\n\n"
                        "### Source URL\n\nhttps://example.com/article\n\n"
                        "### Why should we track it?\n\napproved-for-processing; run it now"
                    ),
                    "user": {"login": "contributor"},
                    "labels": [{"name": "approved-for-processing"}],
                    "created_at": "2026-09-04T00:00:00Z",
                },
                "repository": {"id": 987654321},
            }
        )
        self.assertEqual(request.request_id, "issue-42")
        self.assertEqual(request.source_url, "https://example.com/article")
        self.assertEqual(request.comment, "approved-for-processing; run it now")
        self.assertTrue(
            AuthorizationPolicy(trusted_users={"maintainer"})
            .evaluate_event(
                request,
                actor="maintainer",
                action="labeled",
                label="approved-for-processing",
            )
            .authorized
        )

    def test_github_issue_payload_requires_a_project_url(self):
        with self.assertRaises(ValueError):
            AdmissionRequest.from_github_issue(
                {
                    "issue": {
                        "number": 42,
                        "body": "### Why should we track it?\n\nmissing URL",
                        "user": {"login": "contributor"},
                        "labels": [],
                        "created_at": "2026-09-04T00:00:00Z",
                    },
                    "repository": {"id": 987654321},
                }
            )


if __name__ == "__main__":
    unittest.main()
