"""Durable, idempotent storage for compact command run manifests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterator


class RunManifestStore:
    """Append one manifest per run ID while serializing writers."""

    _KINDS = {
        "ingest",
        "collect",
        "detect-changes",
        "propose-analysis",
        "score",
        "report",
        "generate",
        "validate",
    }
    _STATUSES = {"started", "succeeded", "partial", "pending", "failed"}
    _FIELDS = {
        "schema_version",
        "run_id",
        "kind",
        "started_at",
        "finished_at",
        "status",
        "counts",
        "errors",
        "metadata",
    }

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.directory = self.root / "data" / "runs"
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
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    @staticmethod
    def _canonical(value: dict[str, object]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _existing_manifests(self) -> dict[str, str]:
        manifests: dict[str, str] = {}
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError(f"run manifest {path} is unreadable") from exc
            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"run manifest {path}:{line_number} is not JSON") from exc
                if not isinstance(value, dict) or not isinstance(value.get("run_id"), str):
                    raise ValueError(f"run manifest {path}:{line_number} has no run_id")
                manifests.setdefault(value["run_id"], self._canonical(value))
        return manifests

    def append(self, manifest: dict[str, object]) -> bool:
        """Append a manifest, returning false when its run ID already exists."""
        if not isinstance(manifest, dict):
            raise ValueError("run manifest must be an object")
        unknown = [key for key in manifest if not isinstance(key, str) or key not in self._FIELDS]
        if unknown:
            raise ValueError(
                "run manifest contains unknown fields: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        if manifest.get("schema_version") != 1:
            raise ValueError("run manifest schema_version must be 1")
        run_id = manifest.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run manifest run_id must be a non-empty string")
        if manifest.get("kind") not in self._KINDS:
            raise ValueError("run manifest kind is not supported")
        if manifest.get("status") not in self._STATUSES:
            raise ValueError("run manifest status is not supported")
        counts = manifest.get("counts")
        if not isinstance(counts, dict):
            raise ValueError("run manifest counts must be an object")
        if any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in counts.items()
        ):
            raise ValueError("run manifest counts must contain non-negative integers")
        errors = manifest.get("errors")
        if errors is not None and (
            not isinstance(errors, list)
            or any(not isinstance(error, str) for error in errors)
        ):
            raise ValueError("run manifest errors must be an array of strings")
        metadata = manifest.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("run manifest metadata must be an object")
        timestamps: dict[str, datetime] = {}
        for name in ("started_at", "finished_at"):
            if name == "finished_at" and name not in manifest:
                continue
            value = manifest.get(name)
            if not isinstance(value, str):
                raise ValueError(f"run manifest {name} must be a string")
            if not value.endswith("Z"):
                raise ValueError(f"run manifest {name} must use UTC Z notation")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"run manifest {name} must be ISO-8601") from exc
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise ValueError(f"run manifest {name} must use UTC")
            timestamps[name] = parsed
        parsed = timestamps["started_at"]
        canonical = self._canonical(manifest)
        with self._locked():
            existing = self._existing_manifests()
            previous = existing.get(run_id)
            if previous is not None:
                # Invocation timestamps are generated afresh for a retry; the
                # run ID still binds all substantive outcome fields.
                comparable_previous = json.loads(previous)
                comparable_previous.pop("started_at", None)
                comparable_previous.pop("finished_at", None)
                comparable_current = dict(manifest)
                comparable_current.pop("started_at", None)
                comparable_current.pop("finished_at", None)
                if self._canonical(comparable_previous) != self._canonical(comparable_current):
                    raise ValueError(f"run_id already exists with different manifest: {run_id}")
                return False
            destination = self.directory / f"{parsed:%Y-%m}.jsonl"
            with destination.open("a", encoding="utf-8") as stream:
                stream.write(canonical + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return True
