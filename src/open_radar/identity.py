"""External repository identity and local project ID helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


@dataclass(frozen=True)
class GitHubRepositoryIdentity:
    owner: str
    repo: str

    provider: str = "github"


def parse_github_url(url: str) -> GitHubRepositoryIdentity:
    """Parse one public GitHub repository URL without following it."""

    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("project URL must use https://github.com")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("project URL contains an invalid port") from exc
    if parsed.username or parsed.password or parsed.query or parsed.fragment or port is not None:
        raise ValueError("project URL cannot contain credentials, query, fragment, or port")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ValueError("project URL must point to a repository")

    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or any(char in owner + repo for char in '<>\\\\"'):
        raise ValueError("project URL contains an invalid repository name")
    return GitHubRepositoryIdentity(owner=owner, repo=repo)


def project_slug(name: str) -> str:
    """Create a readable, path-safe slug; callers handle collisions."""

    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("project name cannot produce an empty slug")
    return slug
