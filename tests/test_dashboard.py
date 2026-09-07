"""Regression coverage for collection boundaries and exported privacy
settings."""

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from mergeprint import build, collect


def item(number=1):
    return {
        "number": number,
        "created_at": "2026-01-01T12:00:00Z",
        "closed_at": "2026-01-05T12:00:00Z",
        "pull_request": {"merged_at": "2026-01-05T12:00:00Z"},
        "repository_url": "https://api.github.com/repos/fixture/public",
        "title": "Must never be exported",
        "body": "Private content",
    }


def response(items, total=None):
    return json.dumps(
        {
            "total_count": len(items) if total is None else total,
            "incomplete_results": False,
            "items": items,
        }
    )


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"account": "fixture", "days": 31}))
        self.output = self.root / "page.html"
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def build(self, config, extra=()):
        self.config.write_text(json.dumps(config))
        raw = {
            "account": "fixture",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "prs": [
                "1\t2026-01-01T12:00:00Z\t2026-01-05T12:00:00Z\t"
                "2026-01-05T12:00:00Z\tfixture/private"
            ],
            "issues": ["2\t2026-01-03T12:00:00Z\t\t\tfixture/issues-only"],
            "private": ["fixture/private"],
            "loc": {},
        }
        path = self.root / "raw.json"
        path.write_text(json.dumps(raw))
        build.main(
            [
                "--raw",
                str(path),
                "--config",
                str(self.config),
                "--out",
                str(self.output),
                *extra,
            ]
        )
        page = self.output.read_text()
        return page, json.loads(
            page.split("const D = ")[1].split(";\nconst fmt")[0]
        )

    def test_explicit_config_applies_public_only_and_exclusions(self):
        page, data = self.build(
            {"public_only": True, "exclude_repos": ["fixture/issues-*"]}
        )
        self.assertEqual(data["repos"], [])
        self.assertNotIn("fixture/private", page)
        self.assertEqual(data["issues"], [])

    def test_issue_only_repositories_remain_filterable(self):
        _, data = self.build({"public_only": True})
        self.assertEqual(data["repos"], ["fixture/issues-only"])
        self.assertEqual(data["issues"], [["2026-01-03T12:00:00Z", 0]])
        self.assertFalse(data["backlogComplete"])

    def test_anonymization_removes_names_and_marks_export(self):
        page, data = self.build({}, ["--anonymize-repos"])
        self.assertTrue(data["anonymized"])
        self.assertNotIn("fixture/private", page)
        self.assertNotIn("fixture/issues-only", page)

    def test_demo_seo_is_opt_in(self):
        normal, _ = self.build({})
        demo, _ = self.build({}, ["--demo"])

        self.assertNotIn('rel="canonical"', normal)
        self.assertNotIn("OPEN-SOURCE GITHUB ANALYTICS", normal)
        self.assertIn(
            '<link rel="canonical" '
            'href="https://kirilklein.github.io/mergeprint/">',
            demo,
        )
        self.assertIn('<script type="application/ld+json">', demo)
        self.assertIn("OPEN-SOURCE GITHUB ANALYTICS", demo)

    def test_demo_sitemap_is_valid(self):
        sitemap = Path(__file__).parents[1] / "docs" / "sitemap.xml"
        root = ET.parse(sitemap).getroot()
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        self.assertEqual(
            [node.text for node in root.findall("s:url/s:loc", namespace)],
            ["https://kirilklein.github.io/mergeprint/"],
        )

    def test_event_cannot_close_inline_script(self):
        label = '</script><script>alert("fixture")</script>'
        page, data = self.build({"events": [["2026-01-01", label]]})
        self.assertEqual(data["settings"]["events"][0][1], label)
        self.assertEqual(page.count("<script>"), 1)

    def test_explicit_missing_config_fails(self):
        with self.assertRaises(FileNotFoundError):
            build.main(["--config", str(self.root / "missing.json")])

    @patch.object(collect.time, "sleep")
    def test_permanent_search_failure_is_not_retried(self, sleep):
        with patch.object(
            collect, "gh", side_effect=RuntimeError("HTTP 401")
        ) as gh:
            with self.assertRaisesRegex(RuntimeError, "401"):
                collect.search("is:pr")
        self.assertEqual(gh.call_count, 1)
        sleep.assert_not_called()

    @patch.object(collect.time, "sleep")
    def test_transient_failures_have_a_retry_limit(self, sleep):
        with patch.object(
            collect, "gh", side_effect=RuntimeError("HTTP 503")
        ) as gh:
            with self.assertRaisesRegex(RuntimeError, "503"):
                collect.search("is:pr")
        self.assertEqual(gh.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(collect.time, "sleep")
    def test_dense_query_is_split_into_disjoint_days(self, sleep):
        with patch.object(
            collect,
            "gh",
            side_effect=[
                response([], 1001),
                response([item(1)]),
                response([item(2)]),
            ],
        ) as gh:
            rows = collect.search(
                "is:pr", dt.date(2026, 1, 1), dt.date(2026, 1, 2)
            )
        self.assertEqual(len(rows), 2)
        self.assertIn(
            "closed:2026-01-01..2026-01-01",
            " ".join(gh.call_args_list[1].args),
        )
        self.assertIn(
            "closed:2026-01-02..2026-01-02",
            " ".join(gh.call_args_list[2].args),
        )
        self.assertNotIn("Must never", "".join(rows))

    @patch.object(collect.time, "sleep")
    def test_exact_search_cap_never_requests_page_eleven(self, sleep):
        with patch.object(
            collect, "gh", return_value=response([item()] * 100, 1000)
        ) as gh:
            self.assertEqual(len(collect.search("is:pr")), 1000)
        self.assertEqual(gh.call_count, 10)

    @patch.object(collect.time, "sleep")
    def test_incomplete_search_fails_instead_of_exporting(self, sleep):
        with patch.object(
            collect,
            "gh",
            return_value=json.dumps({"incomplete_results": True}),
        ):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                collect.search("is:pr")

    @patch.object(collect.time, "sleep")
    def test_collector_honours_config_and_fetches_later_closures(self, sleep):
        self.config.write_text(
            json.dumps(
                {
                    "account": "fixture",
                    "days": 31,
                    "public_only": True,
                    "loc_repos": ["fixture/private"],
                }
            )
        )
        row = (
            "1\t2026-01-01T12:00:00Z\t2026-02-05T12:00:00Z\t"
            "2026-02-05T12:00:00Z\tfixture/public"
        )

        def gh(*args):
            if args[:2] == ("api", "repos/fixture/private"):
                return "true"
            if args[0] == "api":
                return "false"
            return "[]"

        raw_path = self.root / "raw.json"
        with (
            patch.object(
                collect, "search", side_effect=[[row], [], []]
            ) as search,
            patch.object(collect, "gh", side_effect=gh) as fetch,
        ):
            collect.main(
                [
                    "--config",
                    str(self.config),
                    "--end",
                    "2026-01-31",
                    "--out",
                    str(raw_path),
                ]
            )
        queries = [call.args[0] for call in search.call_args_list]
        self.assertTrue(
            all("author:fixture" in q and "is:public" in q for q in queries)
        )
        self.assertIn("is:open", queries[1])
        self.assertGreater(
            search.call_args_list[0].args[2], dt.date(2026, 1, 31)
        )
        self.assertFalse(
            any(
                "fixture/private" in call.args
                for call in fetch.call_args_list
                if call.args[0] == "pr"
            )
        )
        raw = json.loads(raw_path.read_text())
        self.assertEqual(raw["start"], "2026-01-01")
        self.assertEqual(raw["prs"], [row])
        self.assertTrue(raw["backlog_complete"])
        self.assertNotIn("fixture/private", raw_path.read_text())


if __name__ == "__main__":
    unittest.main()
