"""Durable admission transaction records and monotonic state transitions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

from .domain import ensure_utc, iso_utc
from .identity import parse_github_url


TRANSACTION_STATUSES = frozenset(
    {"pending", "authorized", "pr_creating", "pr_open", "merged", "admitted", "rejected", "failed"}
)
_TRANSACTION_KEYS = {
    "schema_version",
    "idempotency_key",
    "request_id",
    "intake_repository_id",
    "issue_number",
    "project_id",
    "repository_provider",
    "repository_id",
    "project_url",
    "requester",
    "branch_name",
    "status",
    "created_at",
    "updated_at",
    "pr_number",
    "pr_url",
    "merge_commit_sha",
    "merged_by",
    "last_error",
}
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AdmissionTransactionError(ValueError):
    """Base class for invalid or conflicting transaction state."""


class TransactionConflictError(AdmissionTransactionError):
    """Raised when an idempotency key is reused for different immutable data."""


class TransactionTransitionError(AdmissionTransactionError):
    """Raised when a state transition would move a transaction backwards."""


def _text(value: Any, name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdmissionTransactionError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length or any(char in value for char in "\r\n\x00"):
        raise AdmissionTransactionError(f"{name} contains invalid characters or is too long")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionTransactionError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AdmissionTransactionError(f"{name} must use UTC")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AdmissionTransaction:
    schema_version: int
    idempotency_key: str
    request_id: str
    intake_repository_id: str
    issue_number: int
    project_id: str
    repository_id: int
    project_url: str
    requester: str
    branch_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    pr_number: int | None = None
    pr_url: str | None = None
    merge_commit_sha: str | None = None
    merged_by: str | None = None
    last_error: str | None = None
    repository_provider: str = "github"

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AdmissionTransactionError("transaction.schema_version must be 1")
        _text(self.idempotency_key, "transaction.idempotency_key")
        _text(self.request_id, "transaction.request_id")
        if not isinstance(self.intake_repository_id, str) or re.fullmatch(
            r"[1-9][0-9]*", self.intake_repository_id
        ) is None:
            raise AdmissionTransactionError("transaction.intake_repository_id must be numeric")
        if isinstance(self.issue_number, bool) or not isinstance(self.issue_number, int) or self.issue_number <= 0:
            raise AdmissionTransactionError("transaction.issue_number must be positive")
        if not isinstance(self.project_id, str) or not _SLUG.fullmatch(self.project_id):
            raise AdmissionTransactionError("transaction.project_id must be a lowercase slug")
        if isinstance(self.repository_id, bool) or not isinstance(self.repository_id, int) or self.repository_id <= 0:
            raise AdmissionTransactionError("transaction.repository_id must be positive")
        _text(self.repository_provider, "transaction.repository_provider")
        if not isinstance(self.project_url, str) or not self.project_url.strip():
            raise AdmissionTransactionError("transaction.project_url is required")
        _text(self.project_url, "transaction.project_url")
        try:
            parse_github_url(self.project_url)
        except ValueError as exc:
            raise AdmissionTransactionError("transaction.project_url must be a GitHub repository URL") from exc
        _text(self.requester, "transaction.requester")
        branch = _text(self.branch_name, "transaction.branch_name")
        if not branch.startswith("admission/") or ".." in branch or "\\" in branch:
            raise AdmissionTransactionError("transaction.branch_name is outside the admission namespace")
        if self.status not in TRANSACTION_STATUSES:
            raise AdmissionTransactionError("transaction.status is not supported")
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.updated_at < self.created_at:
            raise AdmissionTransactionError("transaction.updated_at cannot precede created_at")
        if self.pr_number is not None and (
            isinstance(self.pr_number, bool) or not isinstance(self.pr_number, int) or self.pr_number <= 0
        ):
            raise AdmissionTransactionError("transaction.pr_number must be positive or null")
        for name, value in (
            ("transaction.pr_url", self.pr_url),
            ("transaction.merge_commit_sha", self.merge_commit_sha),
            ("transaction.merged_by", self.merged_by),
            ("transaction.last_error", self.last_error),
        ):
            if value is not None:
                _text(value, name, max_length=2048 if name.endswith("pr_url") else 512)
                if name == "transaction.pr_url" and not value.startswith("https://"):
                    raise AdmissionTransactionError("transaction.pr_url must use HTTPS")
        if self.status in {"merged", "admitted"} and (
            not self.merge_commit_sha or not self.merged_by
        ):
            raise AdmissionTransactionError(
                f"transaction.{self.status} requires merge_commit_sha and merged_by"
            )
        if self.status in {"merged", "admitted"} and self.merged_by:
            if self.merged_by.strip().lower().endswith("[bot]"):
                raise AdmissionTransactionError(
                    "automated merger identities cannot be recorded as human merges"
                )
        if self.status in {"pr_open", "merged", "admitted"} and (
            self.pr_number is None or self.pr_url is None
        ):
            raise AdmissionTransactionError(
                f"transaction.{self.status} requires a recorded pull request"
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdmissionTransaction":
        if not isinstance(data, Mapping):
            raise AdmissionTransactionError("transaction must be an object")
        unknown = sorted(set(data) - _TRANSACTION_KEYS)
        if unknown:
            raise AdmissionTransactionError(f"transaction contains unknown fields: {', '.join(unknown)}")
        return cls(
            schema_version=data.get("schema_version"),
            idempotency_key=data.get("idempotency_key"),
            request_id=data.get("request_id"),
            intake_repository_id=data.get("intake_repository_id"),
            issue_number=data.get("issue_number"),
            project_id=data.get("project_id"),
            repository_id=data.get("repository_id"),
            repository_provider=data.get("repository_provider", "github"),
            project_url=data.get("project_url"),
            requester=data.get("requester"),
            branch_name=data.get("branch_name"),
            status=data.get("status"),
            created_at=_timestamp(data.get("created_at"), "transaction.created_at"),
            updated_at=_timestamp(data.get("updated_at"), "transaction.updated_at"),
            pr_number=data.get("pr_number"),
            pr_url=data.get("pr_url"),
            merge_commit_sha=data.get("merge_commit_sha"),
            merged_by=data.get("merged_by"),
            last_error=data.get("last_error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "request_id": self.request_id,
            "intake_repository_id": self.intake_repository_id,
            "issue_number": self.issue_number,
            "project_id": self.project_id,
            "repository_id": self.repository_id,
            "repository_provider": self.repository_provider,
            "project_url": self.project_url,
            "requester": self.requester,
            "branch_name": self.branch_name,
            "status": self.status,
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "merge_commit_sha": self.merge_commit_sha,
            "merged_by": self.merged_by,
            "last_error": self.last_error,
        }


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"pending", "authorized", "rejected", "failed"}),
    "authorized": frozenset({"authorized", "pr_creating", "rejected", "failed"}),
    "pr_creating": frozenset({"pr_creating", "pr_open", "rejected", "failed"}),
    "pr_open": frozenset({"pr_open", "merged", "rejected", "failed"}),
    "merged": frozenset({"merged", "admitted"}),
    "admitted": frozenset({"admitted"}),
    "rejected": frozenset({"rejected"}),
    "failed": frozenset({"failed", "authorized", "pr_creating", "pr_open"}),
}


class AdmissionTransactionStore:
    """Append-only transaction journal with idempotent current-state lookup."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "runs" / "admission-transactions"
        self.lock_path = self.directory / ".write.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    @contextmanager
    def _read_locked(self) -> Iterator[None]:
        """Take a shared lock without creating a lock file during reads."""
        if not self.lock_path.exists():
            yield
            return
        lock_file = self.lock_path.open("r", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def _records(self) -> list[AdmissionTransaction]:
        records: list[AdmissionTransaction] = []
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                raise AdmissionTransactionError(f"{path}: unreadable transaction log") from exc
            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(AdmissionTransaction.from_dict(json.loads(line)))
                except (json.JSONDecodeError, AdmissionTransactionError) as exc:
                    raise AdmissionTransactionError(f"{path}:{line_number}: invalid transaction") from exc
        return records

    @staticmethod
    def _current(records: list[AdmissionTransaction]) -> dict[str, AdmissionTransaction]:
        current: dict[str, AdmissionTransaction] = {}
        for record in records:
            previous = current.get(record.idempotency_key)
            if previous is None or (record.updated_at, record.created_at) >= (
                previous.updated_at,
                previous.created_at,
            ):
                current[record.idempotency_key] = record
        return current

    def get(self, idempotency_key: str) -> AdmissionTransaction | None:
        key = _text(idempotency_key, "idempotency_key")
        with self._read_locked():
            return self._current(self._records()).get(key)

    def all(self) -> list[AdmissionTransaction]:
        with self._read_locked():
            return sorted(
                self._current(self._records()).values(), key=lambda item: item.idempotency_key
            )

    def ensure(self, transaction: AdmissionTransaction) -> AdmissionTransaction:
        with self._locked():
            current = self._current(self._records()).get(transaction.idempotency_key)
            if current is not None:
                if not self._same_identity(current, transaction):
                    raise TransactionConflictError(
                        f"idempotency key is already bound to another admission: {transaction.idempotency_key}"
                    )
                return current
            self._append(transaction)
            return transaction

    def transition(
        self,
        idempotency_key: str,
        status: str,
        *,
        now: datetime | None = None,
        **changes: Any,
    ) -> AdmissionTransaction:
        key = _text(idempotency_key, "idempotency_key")
        with self._locked():
            current = self._current(self._records()).get(key)
            if current is None:
                raise FileNotFoundError(f"admission transaction not found: {key}")
            if status not in TRANSACTION_STATUSES:
                raise AdmissionTransactionError(f"unsupported transaction status: {status}")
            if status not in _ALLOWED_TRANSITIONS[current.status]:
                raise TransactionTransitionError(
                    f"cannot transition admission {key} from {current.status} to {status}"
                )
            immutable = {
                name: getattr(current, name)
                for name in (
                    "schema_version",
                    "idempotency_key",
                    "request_id",
                    "intake_repository_id",
                    "issue_number",
                    "project_id",
                    "repository_id",
                    "repository_provider",
                    "project_url",
                    "requester",
                    "branch_name",
                    "created_at",
                )
            }
            unknown = set(changes) - {
                "pr_number",
                "pr_url",
                "merge_commit_sha",
                "merged_by",
                "last_error",
            }
            if unknown:
                raise AdmissionTransactionError(f"transaction update contains unknown fields: {', '.join(sorted(unknown))}")
            updated_at = _utc_now(now)
            if updated_at < current.updated_at:
                raise TransactionTransitionError("transaction.updated_at cannot move backwards")
            updated = replace(
                current,
                **immutable,
                status=status,
                updated_at=updated_at,
                **changes,
            )
            if current.status in {"merged", "admitted"}:
                for name in ("merge_commit_sha", "merged_by"):
                    if getattr(updated, name) != getattr(current, name):
                        raise TransactionConflictError(
                            f"merged transaction fact {name} cannot be changed"
                        )
            if updated == current:
                return current
            self._append(updated)
            return updated

    def _append(self, transaction: AdmissionTransaction) -> None:
        path = self.directory / f"{transaction.updated_at:%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(transaction.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )

    @staticmethod
    def _same_identity(left: AdmissionTransaction, right: AdmissionTransaction) -> bool:
        return all(
            getattr(left, name) == getattr(right, name)
            for name in (
                "idempotency_key",
                "request_id",
                "intake_repository_id",
                "issue_number",
                "project_id",
                "repository_id",
                "repository_provider",
                "project_url",
                "requester",
                "branch_name",
            )
        )


def _utc_now(value: datetime | None) -> datetime:
    return ensure_utc(value or datetime.now(timezone.utc))
