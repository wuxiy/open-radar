"""Durable replay, rate, and budget controls for admission entry points."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Iterator, Protocol

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


class ReplayStore(Protocol):
    def claim(self, delivery_id: str, *, received_at: datetime | None = None) -> bool: ...


class DurableReplayStore:
    """Append-only delivery ledger shared by verifier processes.

    Only the delivery id and timestamp are stored.  The payload and signature are
    deliberately not retained, so the ledger is safe to keep with run metadata.
    """

    def __init__(self, root_or_path: Path) -> None:
        value = Path(root_or_path)
        self.path = (
            value
            if value.suffix == ".jsonl"
            else value / "data" / "runs" / "webhook-deliveries.jsonl"
        )
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")

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

    def _delivery_ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        result: set[str] = set()
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"replay ledger line {line_number} is not JSON") from exc
            if not isinstance(record, dict) or record.get("schema_version") != 1:
                raise ValueError(f"replay ledger line {line_number} has an invalid schema")
            delivery_id = record.get("delivery_id")
            if not isinstance(delivery_id, str) or not delivery_id.strip():
                raise ValueError(f"replay ledger line {line_number} has an invalid delivery_id")
            result.add(delivery_id)
        return result

    def claim(self, delivery_id: str, *, received_at: datetime | None = None) -> bool:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        timestamp = iso_utc(_utc_now(received_at))
        with self._locked():
            if delivery_id in self._delivery_ids():
                return False
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "delivery_id": delivery_id,
                            "received_at": timestamp,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            return True

    def contains(self, delivery_id: str) -> bool:
        delivery_id = _safe_key(delivery_id, "delivery_id")
        with self._locked():
            return delivery_id in self._delivery_ids()


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
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
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
    """Combine verified-event authorization with an optional durable budget gate."""

    def __init__(
        self,
        policy: AuthorizationPolicy,
        rate_budget: DurableRateBudgetController | None = None,
    ) -> None:
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
                reservation_key=event.request.idempotency_key,
            )
        return decision


# Short aliases keep the public seam discoverable while retaining the durable
# implementation name in tracebacks and documentation.
ReplayLedger = DurableReplayStore
RateBudgetController = DurableRateBudgetController
