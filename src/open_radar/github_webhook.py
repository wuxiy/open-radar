"""Verify GitHub webhook envelopes before mapping Issue data into domain input."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import weakref
from typing import Literal, Mapping

from .admission_request import AdmissionRequest


IssueAction = Literal["opened", "reopened", "labeled", "edited"]
_SUPPORTED_ACTIONS: frozenset[str] = frozenset({"opened", "reopened", "labeled", "edited"})


class WebhookVerificationError(ValueError):
    """Raised when a webhook envelope cannot be trusted or parsed."""


@dataclass(frozen=True)
class VerifiedIssueEvent:
    request: AdmissionRequest
    action: IssueAction
    sender: str
    label_name: str | None
    delivery_id: str
    _verifier: object = field(repr=False, compare=False)
    _snapshot: tuple[object, ...] = field(repr=False, compare=False)

    def is_verified(self) -> bool:
        return (
            isinstance(self._verifier, GitHubWebhookVerifier)
            and self._verifier._is_registered(self)
            and self._snapshot
            == (self.request, self.action, self.sender, self.label_name, self.delivery_id)
        )


class GitHubWebhookVerifier:
    """Verify GitHub's HMAC-SHA256 signature and accepted Issue event shape."""

    def __init__(
        self,
        secret: bytes | str,
        *,
        expected_repository_id: int,
        max_body_bytes: int = 1_048_576,
    ) -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not isinstance(secret, bytes) or not secret:
            raise ValueError("webhook secret must be non-empty bytes or text")
        if isinstance(expected_repository_id, bool) or not isinstance(expected_repository_id, int) or expected_repository_id <= 0:
            raise ValueError("expected_repository_id must be a positive integer")
        if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self._secret = secret
        self._expected_repository_id = expected_repository_id
        self._max_body_bytes = max_body_bytes
        self._verified_events: dict[int, weakref.ReferenceType[VerifiedIssueEvent]] = {}

    def _register(self, event: VerifiedIssueEvent) -> None:
        self._verified_events[id(event)] = weakref.ref(event)

    def _is_registered(self, event: VerifiedIssueEvent) -> bool:
        reference = self._verified_events.get(id(event))
        return reference is not None and reference() is event

    def verify_issue_event(
        self,
        body: bytes,
        signature: str,
        *,
        event_name: str,
        delivery_id: str,
    ) -> VerifiedIssueEvent:
        if event_name != "issues":
            raise WebhookVerificationError("unsupported GitHub webhook event")
        if not isinstance(body, bytes):
            raise WebhookVerificationError("webhook body must be bytes")
        if len(body) > self._max_body_bytes:
            raise WebhookVerificationError("webhook body exceeds size limit")
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not self._valid_signature(signature, expected):
            raise WebhookVerificationError("invalid GitHub webhook signature")
        if not isinstance(delivery_id, str) or not delivery_id.strip():
            raise WebhookVerificationError("delivery_id must be a non-empty string")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError("webhook body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise WebhookVerificationError("webhook payload must be an object")
        repository = payload.get("repository")
        repository_id = repository.get("id") if isinstance(repository, Mapping) else None
        if repository_id != self._expected_repository_id:
            raise WebhookVerificationError("webhook repository does not match configured intake repository")
        action = payload.get("action")
        if not isinstance(action, str) or action not in _SUPPORTED_ACTIONS:
            raise WebhookVerificationError("unsupported GitHub Issue action")
        sender = payload.get("sender")
        sender_login = sender.get("login") if isinstance(sender, Mapping) else None
        if not isinstance(sender_login, str) or not sender_login.strip():
            raise WebhookVerificationError("GitHub webhook sender.login is required")
        label = payload.get("label")
        label_name = label.get("name") if isinstance(label, Mapping) else None
        if action == "labeled" and (not isinstance(label_name, str) or not label_name.strip()):
            raise WebhookVerificationError("labeled Issue event must contain label.name")
        try:
            request = AdmissionRequest.from_github_issue(payload)
        except ValueError as exc:
            raise WebhookVerificationError("invalid GitHub Issue payload") from exc
        event = VerifiedIssueEvent(
            request=request,
            action=action,
            sender=sender_login.strip(),
            label_name=label_name.strip() if isinstance(label_name, str) else None,
            delivery_id=delivery_id.strip(),
            _verifier=self,
            _snapshot=(
                request,
                action,
                sender_login.strip(),
                label_name.strip() if isinstance(label_name, str) else None,
                delivery_id.strip(),
            ),
        )
        self._register(event)
        return event

    @staticmethod
    def _valid_signature(signature: str, expected: str) -> bool:
        if not isinstance(signature, str) or not signature.startswith("sha256="):
            return False
        provided = signature.removeprefix("sha256=")
        if len(provided) != len(expected):
            return False
        if re.fullmatch(r"[0-9a-f]{64}", provided) is None:
            return False
        return hmac.compare_digest(provided, expected)
