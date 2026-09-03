"""GitHub repository access and provider-to-domain mapping."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .domain import ObservationRecord
from .identity import GitHubRepositoryIdentity, parse_github_url


class GitHubProviderError(RuntimeError):
    """Raised when GitHub cannot provide a valid repository response."""


class GitHubClient(Protocol):
    def get_repository(self, owner: str, repo: str) -> Mapping[str, Any]: ...


class GitHubApiClient:
    """Small read-only GitHub API client used by the collection workflow."""

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 15.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        self._token = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds

    def get_repository(self, owner: str, repo: str) -> Mapping[str, Any]:
        path = f"{quote(owner, safe='')}/{quote(repo, safe='')}"
        request = Request(
            f"https://api.github.com/repos/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "open-radar/0.1",
            },
            method="GET",
        )
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        for attempt in range(self._max_retries + 1):
            try:
                with urlopen(request, timeout=self._timeout) as response:
                    payload = json.load(response)
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self._max_retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        delay = float(retry_after) if retry_after is not None else 0.0
                    except (TypeError, ValueError):
                        delay = 0.0
                    delay = min(max(delay, self._backoff_seconds * (2**attempt)), 60.0)
                    time.sleep(delay)
                    continue
                raise GitHubProviderError(f"GitHub API request failed for {owner}/{repo}") from exc
            except URLError as exc:
                retryable = isinstance(
                    exc.reason,
                    (
                        TimeoutError,
                        socket.timeout,
                        ConnectionError,
                    ),
                )
                if retryable and attempt < self._max_retries:
                    time.sleep(self._backoff_seconds * (2**attempt))
                    continue
                raise GitHubProviderError(f"GitHub API request failed for {owner}/{repo}") from exc
            except (TimeoutError, ConnectionError) as exc:
                if attempt < self._max_retries:
                    time.sleep(self._backoff_seconds * (2**attempt))
                    continue
                raise GitHubProviderError(f"GitHub API request failed for {owner}/{repo}") from exc
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise GitHubProviderError(f"GitHub API returned invalid JSON for {owner}/{repo}") from exc
            break
        if not isinstance(payload, Mapping):
            raise GitHubProviderError(f"GitHub API returned an invalid object for {owner}/{repo}")
        return payload


@dataclass(frozen=True)
class RepositoryMetadata:
    repository_id: int
    name: str
    full_name: str
    html_url: str
    description: str | None
    stars: int | None
    forks: int | None
    archived: bool | None
    language: str | None
    topics: tuple[str, ...] | None
    license_spdx: str | None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "RepositoryMetadata":
        if not isinstance(payload, Mapping):
            raise ValueError("GitHub repository payload must be an object")

        repository_id = payload.get("id")
        if isinstance(repository_id, bool) or not isinstance(repository_id, int) or repository_id <= 0:
            raise ValueError("GitHub repository id must be a positive integer")

        def required_string(key: str) -> str:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"GitHub repository field {key!r} must be a non-empty string")
            return value

        def optional_string(key: str) -> str | None:
            value = payload.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(f"GitHub repository field {key!r} must be a string or null")
            return value

        def optional_nonnegative_int(key: str) -> int | None:
            value = payload.get(key)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"GitHub repository field {key!r} must be a non-negative integer")
            return value

        archived = payload.get("archived")
        if archived is not None and not isinstance(archived, bool):
            raise ValueError("GitHub repository field 'archived' must be boolean or null")

        topics_value = payload.get("topics")
        if topics_value is not None and (not isinstance(topics_value, list) or any(
            not isinstance(topic, str) or not topic.strip() for topic in topics_value
        )):
            raise ValueError("GitHub repository field 'topics' must be a list of strings")

        license_value = payload.get("license")
        license_spdx: str | None
        if license_value is None:
            license_spdx = None
        elif isinstance(license_value, Mapping):
            license_spdx = license_value.get("spdx_id")
            if license_spdx is not None and (
                not isinstance(license_spdx, str) or not license_spdx.strip()
            ):
                raise ValueError("GitHub license spdx_id must be a string or null")
        else:
            raise ValueError("GitHub repository field 'license' must be an object or null")

        return cls(
            repository_id=repository_id,
            name=required_string("name"),
            full_name=required_string("full_name"),
            html_url=required_string("html_url"),
            description=optional_string("description"),
            stars=optional_nonnegative_int("stargazers_count"),
            forks=optional_nonnegative_int("forks_count"),
            archived=archived,
            language=optional_string("language"),
            topics=tuple(topics_value) if topics_value is not None else None,
            license_spdx=license_spdx,
        )


class GitHubProvider:
    """Provider seam: identity resolution, fetching, and observation mapping."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def resolve(self, url: str) -> GitHubRepositoryIdentity:
        return parse_github_url(url)

    def fetch_repository(self, identity: GitHubRepositoryIdentity) -> RepositoryMetadata:
        payload = self._client.get_repository(identity.owner, identity.repo)
        return RepositoryMetadata.from_api(payload)

    def to_observation(
        self,
        project_id: str,
        metadata: RepositoryMetadata,
        *,
        run_id: str,
        scheduled_at,
        observed_at,
        recorded_at,
    ) -> ObservationRecord:
        facts = {
            "archived": metadata.archived,
            "language": metadata.language,
            "license_spdx": metadata.license_spdx,
            "topics": list(metadata.topics) if metadata.topics is not None else None,
            "stars": metadata.stars,
            "forks": metadata.forks,
        }
        unavailable = {
            key: "not_reported" for key, value in facts.items() if value is None
        }
        return ObservationRecord.from_dict(
            {
                "schema_version": 1,
                "record_type": "observation",
                "event_id": f"github-{metadata.repository_id}-{scheduled_at.isoformat()}",
                "collection_key": f"github:{metadata.repository_id}:{scheduled_at.isoformat()}",
                "run_id": run_id,
                "project_id": project_id,
                "provider": "github",
                "repository_id": metadata.repository_id,
                "scheduled_at": scheduled_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "collector_version": "open-radar-github/0.1",
                "source": "github-api",
                "metrics": {
                    key: value
                    for key, value in (("stars", metadata.stars), ("forks", metadata.forks))
                    if value is not None
                },
                "facts": facts,
                "unavailable": unavailable,
            }
        )
