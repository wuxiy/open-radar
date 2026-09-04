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
from .admission_controls import ReplayStore


IssueAction = Literal["opened", "reopened", "labeled", "edited"]
_SUPPORTED_ACTIONS: frozenset[str] = frozenset({"opened", "reopened", "labeled", "edited"})


class WebhookVerificationError(ValueError):
    """Raised when a webhook envelope cannot be trusted or parsed."""


class WebhookReplayError(WebhookVerificationError):
    """Raised when a verified delivery id has already been consumed."""


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
            and len(self._snapshot) == 7
            and self._snapshot[:5]
            == (
                self.request,
                self.action,
                self.sender,
                self.label_name,
                self.delivery_id,
            )
            and isinstance(self._snapshot[5], str)
            and (self._snapshot[6] is None or isinstance(self._snapshot[6], str))
        )

    @property
    def payload_sha256(self) -> str:
        return str(self._snapshot[5])

    @property
    def replay_managed(self) -> bool:
        """Whether this event was claimed by a durable replay store."""
        return (
            isinstance(self._verifier, GitHubWebhookVerifier)
            and self._verifier._replay_store is not None
        )

    def complete_replay(self, *, idempotency_key: str | None = None) -> bool:
        if not self.is_verified():
            raise WebhookVerificationError("event is not a live verified event")
        return self._verifier._complete_replay(self, idempotency_key=idempotency_key)

    def fail_replay(self, *, reason: str | None = None) -> bool:
        if not self.is_verified():
            raise WebhookVerificationError("event is not a live verified event")
        return self._verifier._fail_replay(self, reason=reason)


class GitHubWebhookVerifier:
    """Verify GitHub's HMAC-SHA256 signature and accepted Issue event shape."""

    def __init__(
        self,
        secret: bytes | str,
        *,
        expected_repository_id: int,
        max_body_bytes: int = 1_048_576,
        replay_store: ReplayStore | None = None,
        allow_untracked_replay: bool = False,
    ) -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not isinstance(secret, bytes) or not secret:
            raise ValueError("webhook secret must be non-empty bytes or text")
        if isinstance(expected_repository_id, bool) or not isinstance(expected_repository_id, int) or expected_repository_id <= 0:
            raise ValueError("expected_repository_id must be a positive integer")
        if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        if not isinstance(allow_untracked_replay, bool):
            raise ValueError("allow_untracked_replay must be boolean")
        if replay_store is None and not allow_untracked_replay:
            raise ValueError(
                "a durable replay_store is required; set allow_untracked_replay=True only for offline verification"
            )
        if replay_store is not None:
            missing = [
                name
                for name in ("claim", "complete", "fail")
                if not callable(getattr(replay_store, name, None))
            ]
            if missing:
                raise ValueError(
                    f"replay_store is missing required methods: {', '.join(missing)}"
                )
        self._secret = secret
        self._expected_repository_id = expected_repository_id
        self._max_body_bytes = max_body_bytes
        self._replay_store = replay_store
        self._verified_events: dict[int, weakref.ReferenceType[VerifiedIssueEvent]] = {}

    def _register(self, event: VerifiedIssueEvent) -> None:
        self._verified_events[id(event)] = weakref.ref(event)

    def _is_registered(self, event: VerifiedIssueEvent) -> bool:
        reference = self._verified_events.get(id(event))
        return reference is not None and reference() is event

    def _complete_replay(
        self, event: VerifiedIssueEvent, *, idempotency_key: str | None = None
    ) -> bool:
        if self._replay_store is None:
            return True
        complete = getattr(self._replay_store, "complete", None)
        if not callable(complete):
            return True
        claim_token = event._snapshot[6] if isinstance(event._snapshot[6], str) else None
        return complete(
            event.delivery_id,
            claim_token=claim_token,
            idempotency_key=idempotency_key,
        )

    def _fail_replay(self, event: VerifiedIssueEvent, *, reason: str | None = None) -> bool:
        if self._replay_store is None:
            return True
        fail = getattr(self._replay_store, "fail", None)
        if not callable(fail):
            return True
        claim_token = event._snapshot[6] if isinstance(event._snapshot[6], str) else None
        return fail(
            event.delivery_id, claim_token=claim_token, reason=reason
        )

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
        normalized_delivery_id = delivery_id.strip()
        payload_sha256 = hashlib.sha256(body).hexdigest()
        claimed = True
        if self._replay_store is not None:
            claimed = self._replay_store.claim(
                normalized_delivery_id,
                payload_sha256=payload_sha256,
            )
        if not claimed:
            raise WebhookReplayError(
                f"GitHub webhook delivery has already been consumed: {normalized_delivery_id}"
            )
        claim_token = None
        if self._replay_store is not None:
            get_claim_token = getattr(self._replay_store, "get_claim_token", None)
            if callable(get_claim_token):
                claim_token = get_claim_token(normalized_delivery_id)
        event = VerifiedIssueEvent(
            request=request,
            action=action,
            sender=sender_login.strip(),
            label_name=label_name.strip() if isinstance(label_name, str) else None,
            delivery_id=normalized_delivery_id,
            _verifier=self,
            _snapshot=(
                request,
                action,
                sender_login.strip(),
                label_name.strip() if isinstance(label_name, str) else None,
                normalized_delivery_id,
                payload_sha256,
                claim_token,
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
