from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


SITE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = SITE_DIR / "public"
SOURCE_DIR = SITE_DIR.parent / "Processed"
sys.path.insert(0, str(SITE_DIR))
import publish
FORBIDDEN = (
    "source.txt",
    "source_file",
    "source_sha256",
    "processed_at",
    "to text",
    ".pdf",
    ".xlsx",
    "chrome_profile",
    "browser_profiles",
)


class GeneratedSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.home = (PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        cls.manifest = json.loads((PUBLIC_DIR / "site-manifest.json").read_text(encoding="utf-8"))
        cls.search = json.loads((PUBLIC_DIR / "search-index.json").read_text(encoding="utf-8"))

    def test_manifest_is_valid(self) -> None:
        self.assertEqual(self.manifest["validation"]["status"], "PASS")
        self.assertEqual(self.manifest["visibility"], "public-sanitized")
        self.assertGreaterEqual(self.manifest["report_count"], 54)
        self.assertGreaterEqual(self.manifest["weekly_count"], 5)
        self.assertTrue(self.manifest["forecast_included"])

    def test_homepage_section_order(self) -> None:
        positions = [
            self.home.index('id="weekly"'),
            self.home.index('id="calls"'),
            self.home.index('id="reports"'),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_homepage_contains_weekly_markets_and_call_tabs(self) -> None:
        for label in ("US IG", "EU", "HY", "US HY", "EUR IG", "EUR HY"):
            self.assertIn(label, self.home)
        self.assertIn("查看歷史 Weekly", self.home)
        self.assertIn("完整 Forecast Tracker", self.home)
        self.assertIn('class="views-table"', self.home)
        self.assertIn("Hyperscaler Issuance", self.home)
        self.assertIn("最新／延續說明", self.home)
        self.assertIn('class="intro-hero"', self.home)
        self.assertIn('class="weekly-full-detail"', self.home)
        self.assertNotIn('<details class="weekly-full-detail" open', self.home)
        self.assertIn('class="call-field-details"', self.home)
        self.assertNotIn('class="call-list"', self.home)
        self.assertNotIn('class="call-grid"', self.home)

    def test_report_pages_include_all_topic_bullets(self) -> None:
        if not (SOURCE_DIR / ".forecast-calls.json").is_file():
            report_pages = list((PUBLIC_DIR / "reports").glob("*/index.html"))
            self.assertEqual(len(report_pages), self.manifest["report_count"])
            for path in report_pages:
                page = path.read_text(encoding="utf-8")
                self.assertIn("<h2>重點摘要</h2>", page)
                self.assertIn("<h2>主題整理</h2>", page)
                topic_section = page.split("<h2>主題整理</h2>", 1)[1].split("</section>", 1)[0]
                self.assertIn("<h3>", topic_section, path.parent.name)
                self.assertIn("<li>", topic_section, path.parent.name)
            return

        reports, _, _, _ = publish.load_content(SOURCE_DIR)
        self.assertEqual(len(reports), self.manifest["report_count"])
        for report in reports:
            page = (PUBLIC_DIR / "reports" / report["slug"] / "index.html").read_text(encoding="utf-8")
            self.assertIn("<h2>重點摘要</h2>", page)
            self.assertIn("<h2>主題整理</h2>", page)
            topic_section = page.split("<h2>主題整理</h2>", 1)[1].split("</section>", 1)[0]
            expected_bullets = len(re.findall(r"(?m)^\s*[-*+]\s+", report["topics"]))
            expected_headings = len(re.findall(r"(?m)^###\s+", report["topics"]))
            self.assertGreater(expected_bullets, 0, report["slug"])
            self.assertEqual(topic_section.count("<li>"), expected_bullets, report["slug"])
            self.assertEqual(topic_section.count("<h3>"), expected_headings, report["slug"])

    def test_search_index_contains_only_public_fields(self) -> None:
        self.assertEqual(len(self.search["reports"]), self.manifest["report_count"])
        self.assertEqual(len(self.search["weekly"]), self.manifest["weekly_count"])
        allowed = {"broker", "title", "date", "assets", "summary", "url"}
        for report in self.search["reports"]:
            self.assertEqual(set(report), allowed)
            self.assertTrue(report["summary"])

    def test_all_expected_pages_exist(self) -> None:
        report_pages = list((PUBLIC_DIR / "reports").glob("*/index.html"))
        weekly_pages = list((PUBLIC_DIR / "weekly").glob("*/index.html"))
        self.assertEqual(len(report_pages), self.manifest["report_count"])
        self.assertEqual(len(weekly_pages), self.manifest["weekly_count"])
        self.assertTrue((PUBLIC_DIR / "weekly" / "index.html").is_file())
        self.assertTrue((PUBLIC_DIR / "forecast" / "index.html").is_file())

    def test_internal_links_resolve(self) -> None:
        for page in PUBLIC_DIR.rglob("*.html"):
            content = page.read_text(encoding="utf-8")
            for raw in re.findall(r'(?:href|src)="([^"]+)"', content):
                target = urlsplit(raw)
                if target.scheme or target.netloc or raw.startswith(("#", "mailto:")):
                    continue
                clean = unquote(target.path)
                resolved = (page.parent / clean).resolve()
                self.assertTrue(
                    resolved.is_file() or (resolved.is_dir() and (resolved / "index.html").is_file()),
                    f"broken link in {page.relative_to(PUBLIC_DIR)}: {raw}",
                )

    def test_public_artifact_has_no_private_markers(self) -> None:
        for path in PUBLIC_DIR.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".html", ".json", ".js", ".css", ".txt"}:
                continue
            content = path.read_text(encoding="utf-8").lower()
            for term in FORBIDDEN:
                self.assertNotIn(term, content, f"{term!r} leaked in {path.relative_to(PUBLIC_DIR)}")

    def test_tracker_rewords_internal_source_storage_note(self) -> None:
        _, _, tracker, _ = publish.load_content(SOURCE_DIR)
        self.assertNotRegex(tracker.lower(), r"to\s*text")
        self.assertIn("舊sector與hyperscaler calls來源缺失", tracker)

    def test_social_metadata_is_scoped(self) -> None:
        self.assertIn("https://larry890122.github.io/ib-knowledge-base/og.png", self.home)
        report_page = next((PUBLIC_DIR / "reports").glob("*/index.html")).read_text(encoding="utf-8")
        self.assertNotIn('property="og:image"', report_page)


if __name__ == "__main__":
    unittest.main()
