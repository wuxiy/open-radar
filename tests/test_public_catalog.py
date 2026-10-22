from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from open_radar.domain import ObservationRecord, Project
from open_radar.public_catalog import (
    render_public_catalog,
    render_public_not_found,
    write_public_site,
)


class PublicCatalogTests(unittest.TestCase):
    def _project(self, **overrides):
        data = {
            "schema_version": 1,
            "id": "private-project",
            "display_name": "Private <project>",
            "aliases": [],
            "repositories": [
                {
                    "provider": "github",
                    "repository_id": 42,
                    "owner": "example org",
                    "repo": "project/name",
                    "role": "primary",
                }
            ],
            "primary_category": "ai",
            "tags": ["agent"],
            "discovery_sources": [
                {
                    "type": "manual",
                    "url": "https://private.example/secret",
                    "discovered_at": "2026-09-10T00:00:00Z",
                }
            ],
            "research_stage": "watching",
            "decision": "undecided",
            "tracking": "weekly",
            "personal_notes": "private note must not be published",
        }
        data.update(overrides)
        return Project.from_dict(data)

    def _observation(self):
        return ObservationRecord.from_dict(
            {
                "schema_version": 1,
                "record_type": "observation",
                "event_id": "observation-42",
                "collection_key": "github:42:2026-09-10T00:00:00Z",
                "run_id": "run-42",
                "project_id": "private-project",
                "provider": "github",
                "repository_id": 42,
                "scheduled_at": "2026-09-10T00:00:00Z",
                "observed_at": "2026-09-10T00:00:00Z",
                "recorded_at": "2026-09-10T00:00:00Z",
                "collector_version": "test",
                "source": "github-api",
                "metrics": {"stars": 42},
                "facts": {"license_spdx": "Apache-2.0"},
                "unavailable": {},
            }
        )

    def test_public_catalog_escapes_html_and_excludes_private_fields(self):
        rendered = render_public_catalog([self._project()], [self._observation()])
        self.assertIn("Private &lt;project&gt;", rendered)
        self.assertNotIn("Private <project>", rendered)
        self.assertIn("https://github.com/example%20org/project%2Fname", rendered)
        self.assertIn(">42<", rendered)
        self.assertNotIn("private note must not be published", rendered)
        self.assertNotIn("https://private.example/secret", rendered)
        self.assertNotIn("Apache-2.0", rendered)
        self.assertNotIn("undecided", rendered)

    def test_public_catalog_reports_absent_observation_without_exposing_more_data(self):
        rendered = render_public_catalog([self._project()], [])
        self.assertIn("Not observed", rendered)
        self.assertIn("N/A", rendered)

    def test_zero_stars_remains_known_in_public_markup(self):
        observation = self._observation().to_dict()
        observation["metrics"]["stars"] = 0
        rendered = render_public_catalog(
            [self._project()], [ObservationRecord.from_dict(observation)]
        )
        self.assertIn('data-stars="0"', rendered)
        self.assertIn('aria-label="Stars：0"', rendered)
        self.assertNotIn("N/A", rendered)

    def test_empty_catalog_has_a_readable_empty_state_without_script(self):
        rendered = render_public_catalog([], [])
        self.assertIn("共 0 个项目", rendered)
        self.assertIn("目录尚未收录项目", rendered)
        self.assertIn('<div class="empty" id="empty-state">', rendered)
        self.assertNotIn('<article class="project', rendered)

    def test_evaluated_and_disabled_tracking_have_explicit_labels(self):
        rendered = render_public_catalog(
            [self._project(research_stage="evaluated", tracking="off")], []
        )
        self.assertIn('title="evaluated">已评估', rendered)
        self.assertIn('title="off">停止跟踪', rendered)

    def test_overview_uses_date_precision_for_mixed_precision_observations(self):
        observations = []
        projects = []
        for index, observed in enumerate(
            ["2026-10-22T01:00:00Z", "2026-10-22T01:00:00.500000Z"]
        ):
            project_id = f"mixed-{index}"
            projects.append(self._project(id=project_id))
            data = self._observation().to_dict()
            data.update(
                project_id=project_id,
                event_id=f"mixed-observation-{index}",
                collection_key=f"github:42:{observed}",
                scheduled_at=observed,
                observed_at=observed,
                recorded_at=observed,
            )
            observations.append(ObservationRecord.from_dict(data))
        rendered = render_public_catalog(projects, observations)
        self.assertIn(
            'class="overview-note">最近观测日期 <time class="mono" '
            'datetime="2026-10-22">2026-10-22</time> UTC',
            rendered,
        )
        self.assertIn('datetime="2026-10-22T01:00:00.500000Z"', rendered)

    def test_public_site_writes_only_entry_points_and_requires_force_to_replace(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "public"
            index, not_found = write_public_site(
                destination,
                catalog=render_public_catalog([self._project()], [self._observation()]),
                not_found=render_public_not_found(),
            )
            self.assertEqual(index.name, "index.html")
            self.assertEqual(not_found.name, "404.html")
            self.assertTrue(index.is_file())
            self.assertTrue(not_found.is_file())
            self.assertEqual({path.name for path in destination.iterdir()}, {"index.html", "404.html"})
            with self.assertRaises(FileExistsError):
                write_public_site(destination, catalog="replacement", not_found="replacement")
            index, _ = write_public_site(
                destination, catalog="replacement", not_found="replacement", force=True
            )
            self.assertEqual(index.read_text(encoding="utf-8"), "replacement")

    def test_public_site_refuses_preexisting_non_entry_point_file_even_when_forced(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "public"
            destination.mkdir()
            private_file = destination / "data.json"
            private_file.write_text("must not be published", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_public_site(destination, catalog="catalog", not_found="not found", force=True)
            self.assertEqual(private_file.read_text(encoding="utf-8"), "must not be published")

    def test_not_found_uses_the_configured_pages_base_path(self):
        self.assertIn('href="/"', render_public_not_found(base_path="/"))
        self.assertIn('href="/open-radar/"', render_public_not_found(base_path="/open-radar"))
        with self.assertRaises(ValueError):
            render_public_not_found(base_path="https://example.test/")


if __name__ == "__main__":
    unittest.main()
