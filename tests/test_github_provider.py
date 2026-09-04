from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from open_radar.github_provider import GitHubProvider, RepositoryMetadata
from open_radar.identity import GitHubRepositoryIdentity


class FakeGitHubClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_repository(self, owner, repo):
        self.calls.append((owner, repo))
        return self.payload


class GitHubProviderTests(unittest.TestCase):
    def test_repository_fixture_is_compatible_with_adapter(self):
        payload = json.loads(
            (Path(__file__).parent / "fixtures" / "github_repository.json").read_text()
        )
        metadata = RepositoryMetadata.from_api(payload)
        self.assertEqual(metadata.full_name, "example-org/radar-demo")

    def test_metadata_adapter_maps_facts_and_metrics(self):
        client = FakeGitHubClient(
            {
                "id": 100000001,
                "name": "radar-demo",
                "full_name": "example-org/radar-demo",
                "html_url": "https://github.com/example-org/radar-demo",
                "description": "A demo",
                "stargazers_count": 42,
                "forks_count": 3,
                "archived": False,
                "language": "Python",
                "topics": ["automation"],
                "license": {"spdx_id": "MIT"},
            }
        )
        provider = GitHubProvider(client)
        identity = GitHubRepositoryIdentity(owner="example-org", repo="radar-demo")

        metadata = provider.fetch_repository(identity)

        self.assertIsInstance(metadata, RepositoryMetadata)
        self.assertEqual(metadata.repository_id, 100000001)
        self.assertEqual(metadata.stars, 42)
        self.assertEqual(metadata.license_spdx, "MIT")
        self.assertEqual(client.calls, [("example-org", "radar-demo")])

    def test_metadata_becomes_a_versioned_observation(self):
        client = FakeGitHubClient(
            {
                "id": 100000001,
                "name": "radar-demo",
                "full_name": "example-org/radar-demo",
                "html_url": "https://github.com/example-org/radar-demo",
                "description": None,
                "stargazers_count": 42,
                "forks_count": 3,
                "archived": False,
                "language": None,
                "topics": [],
                "license": None,
            }
        )
        provider = GitHubProvider(client)
        metadata = provider.fetch_repository(
            GitHubRepositoryIdentity(owner="example-org", repo="radar-demo")
        )
        observation = provider.to_observation(
            project_id="radar-demo",
            metadata=metadata,
            run_id="run-demo-001",
            scheduled_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
            observed_at=datetime(2026, 9, 3, 0, 2, tzinfo=timezone.utc),
            recorded_at=datetime(2026, 9, 3, 0, 3, tzinfo=timezone.utc),
        )

        self.assertEqual(observation.schema_version, 1)
        self.assertEqual(observation.metrics["stars"], 42)
        self.assertEqual(observation.facts["archived"], False)
        self.assertIsNone(observation.facts["license_spdx"])
        self.assertEqual(observation.unavailable["license_spdx"], "not_reported")

    def test_unknown_repository_id_is_rejected(self):
        client = FakeGitHubClient({"id": 0, "name": "bad"})

        with self.assertRaises(ValueError):
            GitHubProvider(client).fetch_repository(
                GitHubRepositoryIdentity(owner="example-org", repo="bad")
            )

    def test_missing_metrics_and_facts_remain_unknown(self):
        metadata = RepositoryMetadata.from_api(
            {
                "id": 100000001,
                "name": "radar-demo",
                "full_name": "example-org/radar-demo",
                "html_url": "https://github.com/example-org/radar-demo",
            }
        )
        provider = GitHubProvider(FakeGitHubClient({}))
        observation = provider.to_observation(
            project_id="radar-demo",
            metadata=metadata,
            run_id="run-demo-001",
            scheduled_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
            observed_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
            recorded_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        self.assertNotIn("stars", observation.metrics)
        self.assertEqual(observation.unavailable["stars"], "not_reported")
        self.assertIsNone(observation.facts["archived"])
        self.assertIsNone(observation.facts["topics"])
        self.assertEqual(observation.unavailable["topics"], "not_reported")

    def test_api_client_uses_read_only_request_and_keeps_token_out_of_url(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"id": 100000001}'

        with patch("open_radar.github_provider.urlopen", return_value=Response()) as request:
            from open_radar.github_provider import GitHubApiClient

            GitHubApiClient(token="secret-token").get_repository("example-org", "radar-demo")
        built_request = request.call_args.args[0]
        self.assertEqual(built_request.method, "GET")
        self.assertEqual(built_request.full_url, "https://api.github.com/repos/example-org/radar-demo")
        self.assertNotIn("secret-token", built_request.full_url)

    def test_api_client_retries_transient_rate_limit(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"id": 100000001}'

        transient = HTTPError("https://api.github.com", 429, "rate limit", {}, None)
        with patch(
            "open_radar.github_provider.urlopen",
            side_effect=[transient, Response()],
        ) as request, patch("open_radar.github_provider.time.sleep") as sleep:
            from open_radar.github_provider import GitHubApiClient

            payload = GitHubApiClient(max_retries=1, backoff_seconds=0.01).get_repository(
                "example-org", "radar-demo"
            )
        self.assertEqual(payload["id"], 100000001)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_api_client_retries_rate_limited_403(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"id": 100000001}'

        transient = HTTPError(
            "https://api.github.com",
            403,
            "rate limit",
            {"X-RateLimit-Remaining": "0", "Retry-After": "1"},
            None,
        )
        with patch(
            "open_radar.github_provider.urlopen",
            side_effect=[transient, Response()],
        ) as request, patch("open_radar.github_provider.time.sleep") as sleep:
            from open_radar.github_provider import GitHubApiClient

            payload = GitHubApiClient(max_retries=1, backoff_seconds=0.01).get_repository(
                "example-org", "radar-demo"
            )
        self.assertEqual(payload["id"], 100000001)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_api_client_does_not_retry_not_found(self):
        not_found = HTTPError("https://api.github.com", 404, "not found", {}, None)
        with patch("open_radar.github_provider.urlopen", side_effect=not_found) as request:
            from open_radar.github_provider import GitHubApiClient, GitHubProviderError

            with self.assertRaises(GitHubProviderError):
                GitHubApiClient(max_retries=3).get_repository("example-org", "missing")
        self.assertEqual(request.call_count, 1)

    def test_api_client_does_not_retry_permanent_url_error(self):
        with patch(
            "open_radar.github_provider.urlopen",
            side_effect=URLError("invalid URL configuration"),
        ) as request, patch("open_radar.github_provider.time.sleep") as sleep:
            from open_radar.github_provider import GitHubApiClient, GitHubProviderError

            with self.assertRaises(GitHubProviderError):
                GitHubApiClient(max_retries=3).get_repository("example-org", "missing")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
