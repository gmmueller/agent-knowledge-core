"""Offline library helpers. Run with python -I tests/test_library_tools.py --scratch <directory>."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import library_raw as lr
import library_yt as yt
import raw_guard
import web_to_raw as web

SCRATCH = None


class LibraryTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="library-tools-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "library").mkdir()
        lr.init(self.root)

    def source_file(self, kind="docs", extra=""):
        path = lr.pub_dir("acme") / "sources.yaml"
        brainlib.write_text(path, "# source comment\nsources:\n- id: acme-source\n"
                            f"  type: {kind}\n  url: https://example.com\n  last_crawled: null\n{extra}")
        return path

    def fetch(self, client, *urls, **overrides):
        options = dict(publisher="acme", items=None, catalogue=False, urls=urls, limit=None, match=None,
                       transcript=False, recapture=False, recheck=False, kind="doc")
        args = SimpleNamespace(**(options | overrides))
        with contextlib.redirect_stdout(io.StringIO()):
            return web.fetch(args, web.config("acme"), client)

    def test_youtube_partial_tabs_leave_source_due(self):
        path = self.source_file("youtube-channel", "  tabs: [videos, shorts]\n")
        page = json.dumps({"entries": [{"id": "video-a"}]})
        with patch.object(yt, "ytdlp", side_effect=[page, RuntimeError("fixture unavailable")]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(yt.catalogue("acme", web.config("acme"), 0))
        self.assertIn("FAILED acme-source shorts", output.getvalue())
        self.assertIsNone(brainlib.load_yaml(path)["sources"][0]["last_crawled"])
        self.assertIn("yt-video-a", lr.read_catalogue("acme"))
        with patch.object(yt, "ytdlp", return_value=page), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(yt.catalogue("acme", web.config("acme"), 0))
        self.assertEqual(str(brainlib.load_yaml(path)["sources"][0]["last_crawled"]), dt.date.today().isoformat())
        self.assertIn("# source comment", path.read_text(encoding="utf-8"))

    def test_youtube_add_stamps_selected_source_only_on_complete_success(self):
        path = self.source_file("youtube-selected")
        meta = {"id": "abcdefghijk", "title": "Picked Video", "upload_date": "20260512", "duration": 300}
        lr.merge_catalogue("acme", [{"id": "yt-abcdefghijk", "source": "channel"}])
        with patch.object(yt, "metadata", side_effect=[meta, RuntimeError("network")]), \
                patch.object(sys, "argv", ["library_yt.py", "--workspace", str(self.root), "add", "acme",
                                           "--source", "acme-source", "abcdefghijk", "bcdefghijkl"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exited:
                yt.main()
        self.assertEqual(exited.exception.code, 1)
        self.assertIsNone(brainlib.load_yaml(path)["sources"][0]["last_crawled"])
        with patch.object(yt, "metadata", return_value=meta), \
                patch.object(sys, "argv", ["library_yt.py", "--workspace", str(self.root), "add", "acme",
                                           "--source", "acme-source", "abcdefghijk"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exited:
                yt.main()
        self.assertEqual(exited.exception.code, 0)
        self.assertEqual(str(brainlib.load_yaml(path)["sources"][0]["last_crawled"]), dt.date.today().isoformat())
        self.assertEqual(lr.read_catalogue("acme")["yt-abcdefghijk"]["source"], "acme-source")

    def test_youtube_channel_scan_preserves_routing_and_refreshes_metadata(self):
        self.source_file("youtube-channel")
        item = "yt-abcdefghijk"
        lr.merge_catalogue("acme", [{"id": item, "source": "interviews", "kind": "stream", "title": "Old title",
                                     "url": "https://youtu.be/abcdefghijk", "views": 100},
                                    {"id": "yt-bcdefghijkl"}])
        # The manually routed item needs enrichment. The other item has metadata cached from a prior fetch.
        entries = [{"id": "abcdefghijk", "title": "Flat title"}, {"id": "bcdefghijkl", "view_count": 200}]
        cached = {"id": "bcdefghijkl", "title": "Cached title", "upload_date": "20260501", "view_count": 100}
        brainlib.write_text(lr.pub_dir("acme") / "media/meta/bcdefghijkl.json", json.dumps(cached))
        details = {"id": "abcdefghijk", "title": "New title", "upload_date": "20260512",
                   "duration": 300, "view_count": 500, "description": "New description"}
        with patch.object(yt, "ytdlp", return_value=json.dumps({"entries": entries})), \
                patch.object(yt, "metadata", return_value=details) as enrich, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(yt.catalogue("acme", web.config("acme"), 1))
        enrich.assert_called_once_with("acme", "abcdefghijk")
        rows = lr.read_catalogue("acme")
        self.assertEqual((rows[item]["source"], rows[item]["kind"], rows[item]["url"]),
                         ("interviews", "stream", "https://youtu.be/abcdefghijk"))
        self.assertEqual((rows[item]["title"], rows[item]["published"], rows[item]["duration_s"],
                          rows[item]["views"], rows[item]["description"]),
                         ("New title", "2026-05-12", "300", "500", "New description"))
        self.assertEqual((rows["yt-bcdefghijkl"]["source"], rows["yt-bcdefghijkl"]["views"]), ("acme-source", "200"))

    def test_youtube_fetch_repairs_unrecorded_capture_without_refetch_or_rewrite(self):
        self.source_file("youtube-selected", "  format: solo\ndefault_speaker: Example Speaker\n")
        item = "yt-abcdefghijk"
        meta = {"id": "abcdefghijk", "title": "Example", "upload_date": "20260512", "duration": 300}
        lr.merge_catalogue("acme", [yt.youtube_row(meta, "acme-source", "video")])
        config = web.config("acme")
        raw = lr.pub_dir("acme") / "raw"
        with patch.object(yt, "metadata", return_value=meta), patch.object(yt, "captions", return_value=("fixture.json", "auto")), \
                patch.object(yt, "json3_lines", return_value=[{"text": ["A capture."], "start": 0, "end": 5}]), \
                patch.object(raw_guard.hashes, "save", side_effect=OSError("hash write interrupted")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(yt.fetch("acme", config, [item]))
        capture, = (raw / "yt").glob("*.md")
        original = capture.read_bytes(), capture.stat().st_mtime_ns
        Path(str(capture) + ".lock").write_text("", encoding="utf-8")  # macOS/Linux leave the writer's lock file
        self.assertEqual(raw_guard.unrecorded(raw), [f"yt/{capture.name}"])

        with patch.object(yt, "metadata") as metadata, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(yt.fetch("acme", config, [item]))
        metadata.assert_not_called()
        self.assertEqual((capture.read_bytes(), capture.stat().st_mtime_ns), original)
        self.assertEqual(raw_guard.unrecorded(raw), [])
        capture.write_text("A changed capture.\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(yt.fetch("acme", config, [item]))
        self.assertEqual(raw_guard.check(raw), {f"yt/{capture.name}": "changed"})

    def test_web_browser_falls_back_to_playwright_chromium_and_closes(self):
        page = Mock()
        page.content.return_value = "<h1>Rendered</h1>"
        page.url = "https://example.com/rendered"
        ctx = Mock()
        ctx.new_page.return_value = page
        browser = Mock()
        browser.new_context.return_value = ctx
        pw = Mock()
        pw.chromium.launch.side_effect = [RuntimeError("chrome channel missing"), browser]
        sync_api = SimpleNamespace(sync_playwright=lambda: SimpleNamespace(start=lambda: pw))
        client = web.Client(browser=True)
        with patch.dict(sys.modules, {"playwright": SimpleNamespace(sync_api=sync_api), "playwright.sync_api": sync_api}):
            html, final = client._browser_get("https://example.com/rendered")
        self.assertEqual((html, final), ("<h1>Rendered</h1>", "https://example.com/rendered"))
        self.assertEqual(pw.chromium.launch.call_count, 2)
        self.assertEqual(pw.chromium.launch.call_args_list[0].kwargs, {"channel": "chrome", "headless": True})
        self.assertEqual(pw.chromium.launch.call_args_list[1].kwargs, {"headless": True})
        page.close.assert_called_once()
        client.close()
        ctx.close.assert_called_once()
        browser.close.assert_called_once()
        pw.stop.assert_called_once()

    def test_web_stamps_only_successful_run(self):
        path = self.source_file()
        good, bad = "https://example.com/good", "https://example.com/bad"
        lr.merge_catalogue("acme", [{"id": f"web-{label}", "url": url, "kind": "doc", "source": "acme-source"}
                                    for label, url in (("good", good), ("bad", bad))])
        client = Mock()
        client.get.side_effect = [("<h1>Good</h1>", good), OSError("unavailable")]
        with patch.object(web, "paragraphs", return_value=["Useful text."]):
            self.assertEqual(self.fetch(client, catalogue=True), 1)
        self.assertIsNone(brainlib.load_yaml(path)["sources"][0]["last_crawled"])
        args = SimpleNamespace(publisher="acme", sitemap=None, rss=None, index="https://example.com",
                               datasette=None, link_match="/good", next_selector=None, match=None, kind="doc")
        client.get.side_effect = None
        client.get.return_value = ('<a href="/good">Good</a>', args.index)
        with contextlib.redirect_stdout(io.StringIO()):
            web.listings(args, web.config("acme"), client)
        self.assertEqual(str(brainlib.load_yaml(path)["sources"][0]["last_crawled"]), dt.date.today().isoformat())

    def test_web_subset_fetches_keep_the_source_due(self):
        path = self.source_file()
        urls = ["https://example.com/first", "https://example.com/second"]
        lr.merge_catalogue("acme", [{"id": f"web-{label}", "url": url, "kind": "doc", "title": label,
                                     "source": "acme-source"} for label, url in zip(("first", "second"), urls)])
        client = Mock()
        client.get.side_effect = lambda url: ("<h1>Fixture</h1>", url)
        for url_args, options, fetched in ((urls[:1], {}, urls[0]), ([], {"items": ["web-first"]}, urls[0]),
                                           ([], {"catalogue": True, "match": "first"}, urls[0]),
                                           ([], {"catalogue": True, "limit": 1}, urls[1])):
            with self.subTest(options=options), patch.object(web, "paragraphs", return_value=["Useful text."]):
                client.get.reset_mock()
                self.assertEqual(self.fetch(client, *url_args, recheck=True, **options), 0)
                client.get.assert_called_once_with(fetched)
                self.assertIsNone(brainlib.load_yaml(path)["sources"][0]["last_crawled"])

    def test_web_full_catalogue_does_not_stamp_sources_served_from_cache(self):
        path = self.source_file(extra="- id: other-source\n  url: https://example.com/other\n  last_crawled: null\n")
        cached_url, new_url = "https://example.com/cached", "https://example.com/other/new"
        client = Mock()
        client.get.side_effect = lambda url: ("<h1>Fixture</h1>", url)
        with patch.object(web, "paragraphs", return_value=["Useful text."]):
            self.assertEqual(self.fetch(client, cached_url), 0)
            lr.merge_catalogue("acme", [{"id": "web-new", "url": new_url, "kind": "doc", "source": "other-source"}])
            client.get.reset_mock()
            self.assertEqual(self.fetch(client, catalogue=True), 0)
            client.get.assert_called_once_with(new_url)
            sources = brainlib.load_yaml(path)["sources"]
            self.assertIsNone(sources[0]["last_crawled"])
            self.assertEqual(str(sources[1]["last_crawled"]), dt.date.today().isoformat())

            path.write_text(path.read_text(encoding="utf-8").replace(dt.date.today().isoformat(), "2020-01-01"), encoding="utf-8")
            client.get.reset_mock()
            self.assertEqual(self.fetch(client, catalogue=True), 0)
            client.get.assert_not_called()
            self.assertEqual(str(brainlib.load_yaml(path)["sources"][1]["last_crawled"]), "2020-01-01")

            self.assertEqual(self.fetch(client, catalogue=True, recheck=True, limit=2), 0)
            self.assertEqual(client.get.call_count, 2)
            self.assertEqual({str(s["last_crawled"]) for s in brainlib.load_yaml(path)["sources"]},
                             {dt.date.today().isoformat()})

    def test_web_retry_repairs_hash_without_creating_another_capture(self):
        self.source_file()
        url = "https://example.com/page"
        client = Mock()
        client.get.return_value = ("<h1>Fixture</h1>", url)
        with patch.object(web, "paragraphs", return_value=["Useful text."]), \
                patch.object(raw_guard.hashes, "save", side_effect=OSError("hash write interrupted")):
            self.assertEqual(self.fetch(client, url), 1)
        raw = lr.pub_dir("acme") / "raw"
        capture, = (raw / "web").glob("*.md")
        original = capture.read_bytes(), capture.stat().st_mtime_ns
        client.get.reset_mock()
        self.assertEqual(self.fetch(client, url), 0)
        client.get.assert_not_called()
        self.assertEqual((capture.read_bytes(), capture.stat().st_mtime_ns), original)
        self.assertEqual(raw_guard.unrecorded(raw), [])

    def test_web_same_title_and_date_preserve_both_urls(self):
        self.source_file()
        urls = ["https://example.com/a", "https://example.com/b"]
        client = Mock()
        html = '<h1>Shared title</h1><meta property="article:published_time" content="2020-05-12">'
        client.get.side_effect = lambda url: (html, url)
        with patch.object(web, "paragraphs", return_value=["Useful text."]):
            self.assertEqual(self.fetch(client, *urls), 0)
            self.assertEqual(self.fetch(client, *reversed(urls)), 0)
        captures = web.latest_captures(lr.pub_dir("acme") / "raw/web")
        self.assertEqual(set(captures), set(urls))
        self.assertEqual(captures[urls[0]][0].stem, "20200512-shared-title")
        self.assertRegex(captures[urls[1]][0].stem, r"20200512-shared-title-[a-f0-9]{12}$")
        self.assertEqual({r["url"]: r["id"] for r in lr.read_catalogue("acme").values()},
                         {url: front["source_id"] for url, (_, front) in captures.items()})
        self.assertEqual(client.get.call_count, 2)

    def test_web_recheck_compares_latest_and_appends_same_day_revisions(self):
        path = self.source_file()
        url = "https://example.com/page"
        client = Mock()
        client.get.return_value = ("<h1>Fixture</h1>", url)
        raw = lr.pub_dir("acme") / "raw/web"
        with patch.object(web, "paragraphs", return_value=["Original text."]) as paragraphs:
            self.assertEqual(self.fetch(client, url), 0)
            original, front = web.latest_captures(raw)[url]
            original_bytes = original.read_bytes()
            self.assertEqual(self.fetch(client, url, recheck=True), 0)
            self.assertEqual(list(raw.glob("*.md")), [original])
            paragraphs.return_value = ["Changed text."]
            self.assertEqual(self.fetch(client, url, recheck=True), 0)
            changed, changed_front = web.latest_captures(raw)[url]
            self.assertEqual(changed_front["supersedes"], original.name)
            self.assertEqual(changed_front["source_id"], front["source_id"])
            self.assertEqual(self.fetch(client, url, recheck=True), 0)
            self.assertEqual(len(list(raw.glob("*.md"))), 2)
            paragraphs.return_value = ["Original text."]
            self.assertEqual(self.fetch(client, url, recheck=True), 0)
        latest, latest_front = web.latest_captures(raw)[url]
        self.assertEqual(latest_front["supersedes"], changed.name)
        self.assertIn("Original text.", latest.read_text(encoding="utf-8"))
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(len(list(raw.glob("*.md"))), 3)
        self.assertEqual(client.get.call_count, 5)
        self.assertIsNone(brainlib.load_yaml(path)["sources"][0]["last_crawled"])

    def test_catalogue_serializes_merges_and_publishes_atomically(self):
        publisher = "acme"
        lr.merge_catalogue(publisher, [{"id": "web-original"}])
        path = lr.pub_dir(publisher) / "catalogue.tsv"
        original = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("fixture interrupted")):
            with self.assertRaises(OSError):
                lr.merge_catalogue(publisher, [{"id": "web-failed"}])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

        read = lr.read_catalogue
        first_read, release, second_started, second_read = Event(), Event(), Event(), Event()

        def hold_first(name):
            snapshot = read(name)
            if not first_read.is_set():
                first_read.set()
                if not release.wait(5):
                    raise RuntimeError("first write was never released")
            else:
                second_read.set()
            return snapshot

        def merge_second():
            second_started.set()
            return lr.merge_catalogue(publisher, [{"id": "web-second"}])

        with patch.object(lr, "read_catalogue", side_effect=hold_first), ThreadPoolExecutor(2) as workers:
            first = workers.submit(lr.merge_catalogue, publisher, [{"id": "web-first"}])
            try:
                self.assertTrue(first_read.wait(5))
                second = workers.submit(merge_second)
                self.assertTrue(second_started.wait(5))
                self.assertFalse(second_read.wait(0.2))
            finally:
                release.set()
            self.assertEqual(first.result(), (1, 0))
            self.assertEqual(second.result(), (1, 0))
        self.assertEqual(set(read(publisher)), {"web-original", "web-first", "web-second"})

    def test_web_people_update_keeps_formatting_and_is_atomic(self):
        path = self.root / "library/people.yaml"
        raw = '# keep this comment\nada:\n  name: "Ada"\n  appearances: []\n'
        brainlib.write_text(path, raw)
        with patch.object(Path, "replace", side_effect=OSError("fixture interrupted")):
            with self.assertRaises(OSError):
                web.appearances("acme", "pod-first", ["Ada"], "Ada")
        self.assertEqual(path.read_text(encoding="utf-8"), raw)
        started, updated = Event(), Event()

        def add_appearance():
            started.set()
            web.appearances("acme", "pod-second", ["Ada", "Bea"], "Ada")
            updated.set()

        with ThreadPoolExecutor(1) as workers:
            with brainlib.file_lock(path):
                task = workers.submit(add_appearance)
                self.assertTrue(started.wait(5))
                self.assertFalse(updated.wait(0.2))
            task.result()
        web.appearances("acme", "pod-first", ["Ada"], "Ada")
        self.assertIn('# keep this comment\nada:\n  name: "Ada"', path.read_text(encoding="utf-8"))
        people = brainlib.load_yaml(path)
        self.assertEqual([row["item"] for row in people["ada"]["appearances"]], ["acme/pod-second", "acme/pod-first"])
        self.assertEqual(people["bea"]["appearances"], [{"item": "acme/pod-second", "role": "guest"}])

    def test_lock_file_left_by_a_killed_process_does_not_block(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalogue.tsv"
            Path(str(path) + ".lock").write_text("left behind by a crashed crawler", encoding="utf-8")
            lock = brainlib.file_lock(path)
            with lock.acquire(timeout=1):
                self.assertTrue(lock.is_locked)

    def test_slugify(self):
        self.assertEqual(lr.slugify("Café: A useful title!"), "cafe-a-useful-title")
        self.assertEqual(lr.slugify("?!"), "untitled")
        self.assertEqual(lr.slugify("one two three", 8), "one-two")

    def test_catalogue_roundtrip_merge_and_order(self):
        publisher = "example-publisher"
        self.assertEqual(lr.read_catalogue(publisher), {})
        rows = [{"id": "web-old", "title": "Older\tpost\nname", "published": "2024-01-01", "views": 12},
                {"id": "web-new", "title": "New post", "published": "2026-01-01"},
                {"id": "web-undated", "title": "No date"}]
        self.assertEqual(lr.merge_catalogue(publisher, rows), (3, 0))
        found = lr.read_catalogue(publisher)
        self.assertEqual(list(found), ["web-new", "web-old", "web-undated"])
        self.assertEqual(found["web-old"]["title"], "Older post name")
        self.assertEqual(found["web-old"]["views"], "12")
        self.assertEqual(lr.merge_catalogue(publisher, [{"id": "web-old", "title": "Updated"}]), (0, 1))
        self.assertEqual(lr.read_catalogue(publisher)["web-old"]["published"], "2024-01-01")
        before = (lr.pub_dir(publisher) / "catalogue.tsv").read_bytes()
        lr.write_catalogue(publisher, lr.read_catalogue(publisher))
        self.assertEqual((lr.pub_dir(publisher) / "catalogue.tsv").read_bytes(), before)

    def test_raw_write_locator_speakers_and_immutability(self):
        path = lr.raw_path("example-publisher", "yt", "2026-01-01", "Useful lesson", "yt-abc123")
        blocks = lr.transcript_blocks([{"start": 0, "end": 5, "text": "First words.", "speaker": "Alex"},
                                       {"start": 5, "end": 8, "text": "Next words.", "speaker": "Jamie"}])
        lr.write_raw(path, {"title": "Useful lesson", "speakers": ["Alex", "Jamie"]}, lr.render_transcript(blocks))
        original = path.read_bytes()
        text = original.decode("utf-8")
        self.assertIn("captured: ", text)
        self.assertIn("**[0:00]** Alex: First words.", text)
        self.assertIn("**[0:05]** Jamie: Next words.", text)
        self.assertNotIn(b"\r\n", original)
        with self.assertRaises(FileExistsError):
            lr.write_raw(path, {}, "Replacement")
        self.assertEqual(path.read_bytes(), original)

    def test_workspace_can_be_rebound(self):
        second = self.root / "another-workspace"
        (second / "library").mkdir(parents=True)
        lr.init(second)
        lr.merge_catalogue("example-publisher", [{"id": "web-other"}])
        self.assertTrue((second / "library/example-publisher/catalogue.tsv").exists())
        self.assertFalse((self.root / "library/example-publisher/catalogue.tsv").exists())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    SCRATCH = args.scratch.resolve()
    if not SCRATCH.is_dir():
        parser.error("--scratch must be an existing private scratch directory")
    unittest.main(argv=[sys.argv[0], *remaining])
