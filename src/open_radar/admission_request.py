"""Untrusted Issue input and explicit admission authorization policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal, Mapping

from .identity import parse_github_url


REQUEST_KEYS = {
    "schema_version",
    "request_id",
    "intake_repository_id",
    "issue_number",
    "project_url",
    "requester",
    "labels",
    "created_at",
    "source_url",
    "comment",
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class AdmissionAuthorizationError(PermissionError):
    """Raised when an admission request has not passed the authorization gate."""


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("admission request created_at must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("admission request created_at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("admission request created_at must use UTC")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AdmissionRequest:
    schema_version: int
    request_id: str
    intake_repository_id: str
    issue_number: int
    project_url: str
    requester: str
    labels: tuple[str, ...]
    created_at: datetime
    source_url: str | None = None
    comment: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdmissionRequest":
        if not isinstance(data, Mapping):
            raise ValueError("admission request must be an object")
        unknown = sorted(set(data) - REQUEST_KEYS)
        if unknown:
            raise ValueError(f"admission request contains unknown fields: {', '.join(unknown)}")
        if data.get("schema_version") != 1:
            raise ValueError("admission request schema_version must be 1")
        missing = sorted(
            key
            for key in REQUEST_KEYS
            if key not in data
        )
        if missing:
            raise ValueError(f"admission request is missing fields: {', '.join(missing)}")

        request_id = data.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
            raise ValueError("admission request request_id is invalid")
        intake_repository_id = data.get("intake_repository_id")
        if (
            not isinstance(intake_repository_id, str)
            or re.fullmatch(r"[1-9][0-9]*", intake_repository_id.strip()) is None
        ):
            raise ValueError("admission request intake_repository_id is required")
        issue_number = data.get("issue_number")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
            raise ValueError("admission request issue_number must be a positive integer")
        project_url = data.get("project_url")
        if not isinstance(project_url, str) or not project_url.strip():
            raise ValueError("admission request project_url is required")
        parse_github_url(project_url)
        requester = data.get("requester")
        if not isinstance(requester, str) or not requester.strip():
            raise ValueError("admission request requester is required")

        labels = data.get("labels", [])
        if not isinstance(labels, list) or any(
            not isinstance(label, str) or not label.strip() for label in labels
        ):
            raise ValueError("admission request labels must be an array of strings")
        if len(labels) != len(set(labels)):
            raise ValueError("admission request labels must not contain duplicates")

        source_url = data.get("source_url")
        if source_url is not None and (not isinstance(source_url, str) or not source_url.strip()):
            raise ValueError("admission request source_url must be a string or null")
        comment = data.get("comment")
        if comment is not None and not isinstance(comment, str):
            raise ValueError("admission request comment must be a string or null")
        return cls(
            schema_version=1,
            request_id=request_id,
            intake_repository_id=intake_repository_id.strip(),
            issue_number=issue_number,
            project_url=project_url.strip(),
            requester=requester.strip(),
            labels=tuple(labels),
            created_at=_timestamp(data.get("created_at")),
            source_url=source_url.strip() if source_url is not None else None,
            comment=comment,
        )

    @classmethod
    def from_github_issue(cls, payload: Mapping[str, Any]) -> "AdmissionRequest":
        """Map a GitHub Issues webhook payload without executing or interpreting its text."""
        if not isinstance(payload, Mapping) or not isinstance(payload.get("issue"), Mapping):
            raise ValueError("GitHub issue payload must contain an issue object")
        issue = payload["issue"]
        number = issue.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError("GitHub issue number must be a positive integer")
        user = issue.get("user")
        requester = user.get("login") if isinstance(user, Mapping) else None
        if not isinstance(requester, str) or not requester.strip():
            raise ValueError("GitHub issue user.login is required")
        repository = payload.get("repository")
        intake_repository_id = repository.get("id") if isinstance(repository, Mapping) else None
        if (
            isinstance(intake_repository_id, bool)
            or not isinstance(intake_repository_id, int)
            or intake_repository_id <= 0
        ):
            raise ValueError("GitHub issue repository.id must be a positive integer")
        body = issue.get("body") or ""
        if not isinstance(body, str):
            raise ValueError("GitHub issue body must be a string or null")

        def form_value(label: str, *, first_line: bool = False) -> str | None:
            heading = re.search(rf"(?m)^###\s+{re.escape(label)}\s*$", body)
            if heading is None:
                return None
            section_start = heading.end()
            next_heading = re.search(r"(?m)^###\s+", body[section_start:])
            section_end = section_start + next_heading.start() if next_heading else len(body)
            value = body[section_start:section_end].strip()
            if not value:
                return None
            if first_line:
                return value.splitlines()[0].strip()
            return value

        labels_value = issue.get("labels", [])
        if not isinstance(labels_value, list):
            raise ValueError("GitHub issue labels must be an array")
        labels: list[str] = []
        for label in labels_value:
            name = label.get("name") if isinstance(label, Mapping) else None
            if not isinstance(name, str) or not name.strip():
                raise ValueError("GitHub issue labels must contain names")
            labels.append(name.strip())
        return cls.from_dict(
            {
                "schema_version": 1,
                "request_id": f"issue-{number}",
                "intake_repository_id": str(intake_repository_id),
                "issue_number": number,
                "project_url": form_value("Project URL", first_line=True),
                "requester": requester,
                "labels": labels,
                "created_at": issue.get("created_at"),
                "source_url": form_value("Source URL", first_line=True),
                "comment": form_value("Why should we track it?"),
            }
        )

    @property
    def idempotency_key(self) -> str:
        return f"github:{self.intake_repository_id}:issue-{self.issue_number}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "intake_repository_id": self.intake_repository_id,
            "issue_number": self.issue_number,
            "project_url": self.project_url,
            "requester": self.requester,
            "labels": list(self.labels),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "source_url": self.source_url,
            "comment": self.comment,
        }


@dataclass(frozen=True)
class AuthorizationDecision:
    status: Literal["authorized", "pending"]
    reason: Literal[
        "trusted_user",
        "maintainer_label",
        "awaiting_maintainer_authorization",
    ]

    @property
    def authorized(self) -> bool:
        return self.status == "authorized"


class AuthorizationPolicy:
    def __init__(
        self,
        *,
        trusted_users: set[str] | frozenset[str] = frozenset(),
        required_label: str = "approved-for-processing",
    ) -> None:
        if not required_label.strip():
            raise ValueError("required_label cannot be empty")
        self._trusted_users = {user.casefold() for user in trusted_users}
        self._required_label = required_label

    def evaluate(self, request: AdmissionRequest) -> AuthorizationDecision:
        """Authorize the original requester's trusted submission only."""
        if request.requester.casefold() in self._trusted_users:
            return AuthorizationDecision("authorized", "trusted_user")
        return AuthorizationDecision("pending", "awaiting_maintainer_authorization")

    def evaluate_event(
        self,
        request: AdmissionRequest,
        *,
        actor: str,
        action: str,
        label: str | None = None,
    ) -> AuthorizationDecision:
        if not isinstance(actor, str) or not actor.strip():
            return AuthorizationDecision("pending", "awaiting_maintainer_authorization")
        if action == "labeled":
            if label != self._required_label:
                return AuthorizationDecision("pending", "awaiting_maintainer_authorization")
            if actor.casefold() in self._trusted_users:
                return AuthorizationDecision("authorized", "maintainer_label")
            return AuthorizationDecision("pending", "awaiting_maintainer_authorization")
        if action not in {"opened", "reopened", "edited"}:
            return AuthorizationDecision("pending", "awaiting_maintainer_authorization")
        if actor.casefold() == request.requester.casefold() and actor.casefold() in self._trusted_users:
            return AuthorizationDecision("authorized", "trusted_user")
        return AuthorizationDecision("pending", "awaiting_maintainer_authorization")

    def require_authorized(self, request: AdmissionRequest) -> AuthorizationDecision:
        decision = self.evaluate(request)
        if not decision.authorized:
            raise AdmissionAuthorizationError(
                f"admission request {request.request_id} is pending authorization"
            )
        return decision

    def require_authorized_event(
        self,
        request: AdmissionRequest,
        *,
        actor: str,
        action: str,
        label: str | None = None,
    ) -> AuthorizationDecision:
        decision = self.evaluate_event(
            request,
            actor=actor,
            action=action,
            label=label,
        )
        if not decision.authorized:
            raise AdmissionAuthorizationError(
                f"admission request {request.request_id} is pending authorization"
            )
        return decision
