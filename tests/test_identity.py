import unittest

from open_radar.identity import GitHubRepositoryIdentity, parse_github_url, project_slug


class GitHubIdentityTests(unittest.TestCase):
    def test_parse_public_repository_url(self):
        identity = parse_github_url("https://github.com/Example-Org/Radar-Demo.git")

        self.assertEqual(
            identity,
            GitHubRepositoryIdentity(owner="Example-Org", repo="Radar-Demo"),
        )

    def test_parse_rejects_non_github_and_non_repository_urls(self):
        for url in (
            "https://gitlab.com/example/radar",
            "http://github.com/example/radar",
            "https://github.com/example",
            "https://github.com/example/radar/issues/1",
            "https://github.com:8443/example/radar",
            "https://github.com/example/radar#readme",
            "not-a-url",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    parse_github_url(url)

    def test_project_slug_is_stable_and_safe_for_paths(self):
        self.assertEqual(project_slug("Radar Demo"), "radar-demo")
        self.assertEqual(project_slug("__OpenHands__"), "openhands")
        self.assertEqual(project_slug("A/B"), "a-b")

        with self.assertRaises(ValueError):
            project_slug("---")


if __name__ == "__main__":
    unittest.main()
