import os
import unittest

from open_radar.github_provider import GitHubApiClient, GitHubProvider


@unittest.skipUnless(
    os.environ.get("OPEN_RADAR_RUN_GITHUB_INTEGRATION") == "1",
    "set OPEN_RADAR_RUN_GITHUB_INTEGRATION=1 to enable real GitHub API tests",
)
class GitHubApiIntegrationTests(unittest.TestCase):
    def test_public_repository_can_be_read(self):
        token = os.environ.get("GITHUB_TOKEN")
        provider = GitHubProvider(GitHubApiClient(token=token))
        metadata = provider.fetch_repository(provider.resolve("https://github.com/octocat/Hello-World"))
        self.assertGreater(metadata.repository_id, 0)
        self.assertEqual(metadata.full_name.lower(), "octocat/hello-world")
