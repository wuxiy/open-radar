"""Durable replay, rate, and budget controls for admission entry points."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Iterator, Protocol
import uuid

from .admission_request import (
    AdmissionAuthorizationError,
    AdmissionRequest,
    AuthorizationDecision,
    AuthorizationPolicy,
)
from .domain import ensure_utc, iso_utc


def _safe_key(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > 256 or any(char in value for char in "\r\n\x00"):
        raise ValueError(f"{name} contains invalid characters or is too long")
    return value


def _utc_now(value: datetime | None) -> datetime:
    return ensure_utc(value or datetime.now(timezone.utc))


@dataclass(frozen=True)
class ReplayRecord:
    delivery_id: str
    status: str
    claimed_at: datetime
    payload_sha256: str | None = None
    completed_at: datetime | None = None
    idempotency_key: str | None = None
    last_error: str | None = None
    claim_token: str | None = None


class ReplayStore(Protocol):
    def claim(
        self,
        delivery_id: str,
        *,
        payload_sha256: str | None = None,
        received_at: datetime | None = None,
    ) -> bool: ...

    def complete(
        self,
        delivery_id: str,
        *,
        claim_token: str | None = None,
        idempotency_key: str | None = None,
        completed_at: datetime | None = None,
    ) -> bool: ...

    def fail(
        self,
        delivery_id: str,
        *,
        claim_token: str | None = None,
        reason: str | None = None,
        failed_at: datetime | None = None,
    ) -> bool: ...


class DurableReplayStore:
    """Append-only delivery ledger with recoverable processing state.

    The verifier records ``processing`` before business work starts.  The
    workflow records ``completed`` only after its durable transaction is ready,
    or ``failed`` when the transaction can be retried.  Payload bytes and
    signatures are never retained; the optional digest only prevents delivery
    id rebinding.
    """

    def __init__(self, root_or_path: Path, *, processing_timeout_seconds: int = 300) -> None:
        if (
            isinstance(processing_timeout_seconds, bool)
            or not isinstance(processing_timeout_seconds, int)
            or processing_timeout_seconds <= 0
        ):
            raise ValueError("processing_timeout_seconds must be a positive integer")
        value = Path(root_or_path)
        self.path = (
            value
            if value.suffix == ".jsonl"
            else value / "data" / "runs" / "webhook-deliveries.jsonl"
        )
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.processing_timeout = timedelta(seconds=processing_timeout_seconds)
        self._claim_tokens: dict[str, str] = {}

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def _records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        result: list[dict[str, object]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"replay ledger {self.path} is unreadable") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"replay ledger line {line_number} is not JSON") from exc
            if not isinstance(record, dict) or record.get("schema_version") not in (1, 2):
                raise ValueError(f"replay ledger line {line_number} has an invalid schema")
            delivery_id = record.get("delivery_id")
            if not isinstance(delivery_id, str) or not delivery_id.strip():
                raise ValueError(f"replay ledger line {line_number} has an invalid delivery_id")
            if record.get("schema_version") == 1:
                # Version 1 entries were claimed before completion existed.  Treat
                # them as completed so upgrading cannot accidentally replay them.
                record = {
                    "schema_version": 2,
                    "delivery_id": delivery_id,
                    "status": "completed",
                    "claimed_at": record.get("received_at"),
                    "completed_at": record.get("received_at"),
                }
            status = record.get("status")
            if status not in {"processing", "completed", "failed"}:
                raise ValueError(f"replay ledger line {line_number} has an invalid status")
            claimed_at = record.get("claimed_at")
            try:
                datetime.fromisoformat(str(claimed_at).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"replay ledger line {line_number} has an invalid claimed_at") from exc
            payload_sha256 = record.get("payload_sha256")
            if payload_sha256 is not None and (
                not isinstance(payload_sha256, str) or len(payload_sha256) != 64
            ):
                raise ValueError(f"replay ledger line {line_number} has an invalid payload_sha256")
            claim_token = record.get("claim_token")
            if claim_token is not None and (
                not isinstance(claim_token, str) or not claim_token.strip()
            ):
                raise ValueError(f"replay ledger line {line_number} has an invalid claim_token")
            result.append(record)
        return result

    def _latest(self) -> dict[str, dict[str, object]]:
        latest: dict[str, dict[str, object]] = {}
        for record in self._records():
            latest[str(record["delivery_id"])] = record
        return latest

    def _append(self, record: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )

    @staticmethod
    def _validate_digest(payload_sha256: str | None) -> str | None:
        if payload_sha256 is None:
            return None
        if not isinstance(payload_sha256, str) or len(payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a SHA-256 hex digest")
        try:
            int(payload_sha256, 16)
        except ValueError as exc:
            raise ValueError("payload_sha256 must be a SHA-256 hex digest") from exc
        return payload_sha256.lower()

    def claim(
        self,
        delivery_id: str,
        *,
        payload_sha256: str | None = None,
        received_at: datetime | None = None,
    ) -> bool:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        payload_sha256 = self._validate_digest(payload_sha256)
        claim_token = uuid.uuid4().hex
        now = _utc_now(received_at)
        with self._locked():
            current = self._latest().get(delivery_id)
            if current is not None:
                known_digest = current.get("payload_sha256")
                if known_digest is not None and payload_sha256 != known_digest:
                    raise ValueError("delivery_id was previously used for a different payload")
                status = current.get("status")
                if status == "completed":
                    return False
                if status == "processing":
                    claimed_at = datetime.fromisoformat(
                        str(current["claimed_at"]).replace("Z", "+00:00")
                    )
                    if now - ensure_utc(claimed_at) <= self.processing_timeout:
                        return False
                # A failed or stale processing record is reclaimable.
            self._append(
                {
                    "schema_version": 2,
                    "delivery_id": delivery_id,
                    "status": "processing",
                    "claimed_at": iso_utc(now),
                    "payload_sha256": payload_sha256,
                    "claim_token": claim_token,
                }
            )
            self._claim_tokens[delivery_id] = claim_token
            return True

    def get_claim_token(self, delivery_id: str) -> str | None:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        with self._locked():
            current = self._latest().get(delivery_id)
            if current is None or current.get("status") != "processing":
                return None
            token = current.get("claim_token")
            return str(token) if token is not None else None

    def complete(
        self,
        delivery_id: str,
        *,
        claim_token: str | None = None,
        idempotency_key: str | None = None,
        completed_at: datetime | None = None,
    ) -> bool:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        claim_token = claim_token or self._claim_tokens.get(delivery_id)
        if claim_token is not None:
            claim_token = _safe_key(claim_token, "claim_token")
        idempotency_key = (
            _safe_key(idempotency_key, "idempotency_key") if idempotency_key is not None else None
        )
        now = _utc_now(completed_at)
        with self._locked():
            current = self._latest().get(delivery_id)
            if current is None:
                return False
            if current.get("status") == "completed":
                recorded_key = current.get("idempotency_key")
                if (
                    idempotency_key is not None
                    and recorded_key is not None
                    and recorded_key != idempotency_key
                ):
                    return False
                return True
            if current.get("status") != "processing":
                return False
            current_token = current.get("claim_token")
            if current_token is not None and claim_token != current_token:
                return False
            self._append(
                {
                    "schema_version": 2,
                    "delivery_id": delivery_id,
                    "status": "completed",
                    "claimed_at": current.get("claimed_at"),
                    "completed_at": iso_utc(now),
                    "payload_sha256": current.get("payload_sha256"),
                    "idempotency_key": idempotency_key,
                    "claim_token": current_token,
                }
            )
            return True

    def fail(
        self,
        delivery_id: str,
        *,
        claim_token: str | None = None,
        reason: str | None = None,
        failed_at: datetime | None = None,
    ) -> bool:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        claim_token = claim_token or self._claim_tokens.get(delivery_id)
        if claim_token is not None:
            claim_token = _safe_key(claim_token, "claim_token")
        reason = _safe_key(reason, "reason") if reason is not None else None
        now = _utc_now(failed_at)
        with self._locked():
            current = self._latest().get(delivery_id)
            if current is None or current.get("status") == "completed":
                return False
            current_token = current.get("claim_token")
            if current_token is not None and claim_token != current_token:
                return False
            if current.get("status") == "failed" and current.get("last_error") == reason:
                return True
            self._append(
                {
                    "schema_version": 2,
                    "delivery_id": delivery_id,
                    "status": "failed",
                    "claimed_at": current.get("claimed_at"),
                    "failed_at": iso_utc(now),
                    "payload_sha256": current.get("payload_sha256"),
                    "last_error": reason,
                    "claim_token": current_token,
                }
            )
            return True

    def contains(self, delivery_id: str) -> bool:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        with self._locked():
            return delivery_id in self._latest()

    def get(self, delivery_id: str) -> ReplayRecord | None:
        """Return the latest state for observability and recovery tooling."""
        delivery_id = _safe_key(delivery_id, "delivery_id")
        with self._locked():
            record = self._latest().get(delivery_id)
            if record is None:
                return None
            claimed_at = datetime.fromisoformat(
                str(record["claimed_at"]).replace("Z", "+00:00")
            )
            completed_at_value = record.get("completed_at")
            completed_at = (
                datetime.fromisoformat(str(completed_at_value).replace("Z", "+00:00"))
                if completed_at_value is not None
                else None
            )
            return ReplayRecord(
                delivery_id=delivery_id,
                status=str(record["status"]),
                claimed_at=ensure_utc(claimed_at),
                payload_sha256=(
                    str(record["payload_sha256"])
                    if record.get("payload_sha256") is not None
                    else None
                ),
                completed_at=ensure_utc(completed_at) if completed_at is not None else None,
                idempotency_key=(
                    str(record["idempotency_key"])
                    if record.get("idempotency_key") is not None
                    else None
                ),
                last_error=(
                    str(record["last_error"])
                    if record.get("last_error") is not None
                    else None
                ),
                claim_token=(
                    str(record["claim_token"])
                    if record.get("claim_token") is not None
                    else None
                ),
            )


@dataclass(frozen=True)
class RateBudgetPolicy:
    """Limits for one actor/repository window."""

    max_requests: int
    max_budget_units: int
    window_seconds: int = 3600

    def __post_init__(self) -> None:
        for name, value in (
            ("max_requests", self.max_requests),
            ("max_budget_units", self.max_budget_units),
            ("window_seconds", self.window_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class RateBudgetDecision:
    allowed: bool
    reason: str
    request_count: int
    budget_used: int
    window_started_at: datetime
    replayed: bool = False


class RateBudgetExceeded(PermissionError):
    def __init__(self, decision: RateBudgetDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason)


class DurableRateBudgetController:
    """Persist accepted reservations and decisions under a process lock."""

    def __init__(self, root_or_path: Path, policy: RateBudgetPolicy) -> None:
        value = Path(root_or_path)
        self.path = (
            value
            if value.suffix == ".jsonl"
            else value / "data" / "runs" / "admission-usage.jsonl"
        )
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.policy = policy

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def _records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        records: list[dict[str, object]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"usage ledger {self.path} is unreadable") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"usage ledger line {line_number} is not JSON") from exc
            if not isinstance(record, dict) or record.get("schema_version") != 1:
                raise ValueError(f"usage ledger line {line_number} has an invalid schema")
            if not isinstance(record.get("actor"), str) or not isinstance(
                record.get("intake_repository_id"), str
            ):
                raise ValueError(f"usage ledger line {line_number} has an invalid scope")
            units = record.get("units")
            if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
                raise ValueError(f"usage ledger line {line_number} has invalid units")
            if not isinstance(record.get("allowed"), bool):
                raise ValueError(f"usage ledger line {line_number} has invalid allowed flag")
            reservation_key = record.get("reservation_key")
            if reservation_key is not None and not isinstance(reservation_key, str):
                raise ValueError(f"usage ledger line {line_number} has invalid reservation_key")
            if not isinstance(record.get("reason"), str) or not record["reason"].strip():
                raise ValueError(f"usage ledger line {line_number} has invalid reason")
            reserved_at = record.get("reserved_at")
            try:
                parsed = datetime.fromisoformat(str(reserved_at).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    f"usage ledger line {line_number} has an invalid reserved_at"
                ) from exc
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise ValueError(
                    f"usage ledger line {line_number} reserved_at must use UTC"
                )
            records.append(record)
        return records

    def try_reserve(
        self,
        actor: str,
        intake_repository_id: str,
        *,
        units: int = 1,
        reservation_key: str | None = None,
        at: datetime | None = None,
    ) -> RateBudgetDecision:
        actor = _safe_key(actor, "actor")
        intake_repository_id = _safe_key(intake_repository_id, "intake_repository_id")
        if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
            raise ValueError("units must be a positive integer")
        if units > self.policy.max_budget_units:
            raise ValueError("units cannot exceed max_budget_units")
        reservation_key = (
            _safe_key(reservation_key, "reservation_key") if reservation_key is not None else None
        )
        now = _utc_now(at)
        window_started = now - timedelta(seconds=self.policy.window_seconds)
        with self._locked():
            records = self._records()
            if reservation_key is not None:
                for record in reversed(records):
                    if (
                        record.get("reservation_key") == reservation_key
                        and record.get("actor") == actor
                        and record.get("intake_repository_id") == intake_repository_id
                        and record.get("allowed") is True
                    ):
                        return RateBudgetDecision(
                            allowed=True,
                            reason="already reserved",
                            request_count=0,
                            budget_used=0,
                            window_started_at=window_started,
                            replayed=True,
                        )
            active: list[dict[str, object]] = []
            for record in records:
                if record.get("allowed") is not True:
                    continue
                timestamp = record.get("reserved_at")
                try:
                    parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("usage ledger contains an invalid reserved_at")
                if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                    raise ValueError("usage ledger reserved_at must use UTC")
                if parsed >= window_started:
                    active.append(record)
            same_scope = [
                record
                for record in active
                if record.get("actor") == actor
                and record.get("intake_repository_id") == intake_repository_id
            ]
            request_count = len(same_scope)
            budget_used = sum(
                int(record.get("units", 0))
                for record in same_scope
                if isinstance(record.get("units"), int)
            )
            reason: str | None = None
            if request_count >= self.policy.max_requests:
                reason = "admission rate limit exceeded"
            elif budget_used + units > self.policy.max_budget_units:
                reason = "admission budget exceeded"
            allowed = reason is None
            decision = RateBudgetDecision(
                allowed=allowed,
                reason=reason or "reserved",
                request_count=request_count + int(allowed),
                budget_used=budget_used + (units if allowed else 0),
                window_started_at=window_started,
            )
            record = {
                "schema_version": 1,
                "actor": actor,
                "intake_repository_id": intake_repository_id,
                "units": units,
                "reservation_key": reservation_key,
                "reserved_at": iso_utc(now),
                "allowed": allowed,
                "reason": decision.reason,
            }
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
            return decision

    def reserve(self, *args, **kwargs) -> RateBudgetDecision:
        decision = self.try_reserve(*args, **kwargs)
        if not decision.allowed:
            raise RateBudgetExceeded(decision)
        return decision


class AdmissionGuard:
    """Combine verified authorization with a durable rate/budget reservation."""

    def __init__(
        self,
        policy: AuthorizationPolicy,
        rate_budget: DurableRateBudgetController | None = None,
        *,
        allow_unbounded: bool = False,
    ) -> None:
        if not isinstance(allow_unbounded, bool):
            raise ValueError("allow_unbounded must be boolean")
        if rate_budget is None and not allow_unbounded:
            raise ValueError(
                "a durable rate_budget is required; set allow_unbounded=True only for offline tests"
            )
        self.policy = policy
        self.rate_budget = rate_budget

    def authorize_request(self, request: AdmissionRequest) -> AuthorizationDecision:
        decision = self.policy.require_authorized(request)
        if self.rate_budget is not None:
            self.rate_budget.reserve(
                request.requester,
                request.intake_repository_id,
                reservation_key=request.idempotency_key,
            )
        return decision

    def authorize_event(self, event) -> AuthorizationDecision:
        from .github_webhook import VerifiedIssueEvent

        if not isinstance(event, VerifiedIssueEvent):
            raise AdmissionAuthorizationError(
                "admission events must be VerifiedIssueEvent instances"
            )
        if not event.is_verified():
            raise AdmissionAuthorizationError(
                "admission events must pass GitHub webhook verification"
            )
        decision = self.policy.require_authorized_event(
            event.request,
            actor=event.sender,
            action=event.action,
            label=event.label_name,
        )
        if self.rate_budget is not None:
            self.rate_budget.reserve(
                event.sender,
                event.request.intake_repository_id,
                # A delivery id is the replay unit.  The Issue idempotency key
                # may legitimately receive distinct lifecycle events.
                reservation_key=f"delivery:{event.delivery_id}",
            )
        return decision


# Short aliases keep the public seam discoverable while retaining the durable
# implementation name in tracebacks and documentation.
ReplayLedger = DurableReplayStore
RateBudgetController = DurableRateBudgetController
