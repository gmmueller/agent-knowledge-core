"""Offline Skool parsing and configuration checks; no browser or network access.

Run: python -X utf8 -I tests/test_skool_tools.py --scratch <private-scratch-dir>
"""
import argparse
import contextlib
import datetime as dt
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import mux_captions
import skool_attachments
import skool_classroom_crawl
import skool_classroom_map
import skool_feed_index
import skool_session
import skool_text
import skool_thread_crawl

SCRATCH = None


def text(value, **extra):
    return {"type": "text", "text": value, **extra}


def paragraph(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


def render(*nodes, as_list=False):
    doc = list(nodes) if as_list else {"type": "doc", "content": list(nodes)}
    return skool_text.desc_to_markdown("[v2]" + json.dumps(doc))


class RichText(unittest.TestCase):
    def test_plain_empty_and_unicode(self):
        for value in (None, "", "  "):
            self.assertEqual(skool_text.desc_to_markdown(value), "")
        self.assertEqual(skool_text.desc_to_markdown("  Already **Markdown**.  "), "Already **Markdown**.")
        self.assertEqual(render(paragraph(text("Café · α – 🧠"))), "Café · α – 🧠")

    def test_marks_links_and_unknown_marks(self):
        self.assertEqual(render(paragraph(text("learn", marks=[{"type": "bold"}, {"type": "italic"}]))), "***learn***")
        self.assertEqual(render(paragraph(text("code", marks=[{"type": "code"}]))), "`code`")
        self.assertEqual(render(paragraph(text("docs", marks=[{"type": "link", "attrs": {"href": "https://example.com/docs"}}]))), "[docs](https://example.com/docs)")
        self.assertEqual(render(paragraph(text("plain", marks=[{"type": "unknown"}]))), "plain")

    def test_inline_breaks_mentions_images_and_wrappers(self):
        nodes = [text("one"), {"type": "hardBreak"}, {"type": "mention", "attrs": {"label": "Expert"}},
                 {"type": "image", "attrs": {"alt": "diagram", "src": "small.png", "originalSrc": "full.png"}},
                 {"type": "span", "content": [text("wrapped")]}]
        self.assertEqual(render(paragraph(*nodes)), "one\n@Expert![diagram](full.png)wrapped")
        self.assertEqual(render({"type": "image", "attrs": {"src": "image.png"}}), "![](image.png)")

    def test_headings_blocks_and_list_form(self):
        nodes = [{"type": "heading", "attrs": {"level": 3}, "content": [text("Title")]},
                 paragraph(text("Body")), {"type": "horizontalRule"},
                 {"type": "blockquote", "content": [paragraph(text("Quote"))]},
                 {"type": "codeBlock", "content": [text("x = 1\ny = 2")]}, paragraph()]
        expected = "### Title\n\nBody\n\n---\n\n> Quote\n\n```\nx = 1\ny = 2\n```"
        self.assertEqual(render(*nodes), expected)
        self.assertEqual(render(*nodes, as_list=True), expected)

    def test_nested_lists_and_unknown_blocks(self):
        nested = {"type": "bulletList", "content": [{"type": "listItem", "content": [paragraph(text("Inner"))]}]}
        items = [{"type": "listItem", "content": [paragraph(text("First")), nested]},
                 {"type": "listItem", "content": [paragraph(text("Second"))]}]
        self.assertEqual(render({"type": "orderedList", "content": items}), "1. First\n  - Inner\n2. Second")
        self.assertEqual(render({"type": "custom", "content": [paragraph(text("Keep me"))]}), "Keep me")
        self.assertEqual(render({"type": "unknown"}), "")

    def test_malformed_rich_text_is_not_silently_lost(self):
        with self.assertRaises(json.JSONDecodeError):
            skool_text.desc_to_markdown("[v2]{broken")

    def test_lesson_hash_uses_body_video_and_resources(self):
        meta = {"desc": "body", "videoLink": "video", "resources": "[]", "title": "Title"}
        self.assertEqual(skool_text.lesson_hash(meta), hashlib.sha1(b"bodyvideo[]").hexdigest())
        for key in ("desc", "videoLink", "resources"):
            self.assertNotEqual(skool_text.lesson_hash(meta), skool_text.lesson_hash({**meta, key: "changed"}))
        self.assertEqual(skool_text.lesson_hash(meta), skool_text.lesson_hash({**meta, "title": "New title"}))
        self.assertEqual(skool_text.lesson_hash({}), hashlib.sha1(b"").hexdigest())


class ConfigurationAndCaptions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skool-tools-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.brain = Path(self.temp.name).resolve() / "my-course"
        brainlib.write_text(self.brain / "brain.md", "# My course\n")
        brainlib.write_text(self.brain / "crawl.yaml", "platform: skool\nsite: https://www.skool.com/my-community\ncdp_port: 9333\nprofile: chrome-my-community\nscratch: my-cache\nsource_prefix: mc\n")

    def test_configured_session_and_cache(self):
        args = argparse.Namespace(brain=str(self.brain), group=None, port=None)
        brain, config = skool_session.configure(args)
        self.assertEqual((brain, args.group, args.port, config["profile"]), (self.brain.resolve(), "my-community", 9333, "chrome-my-community"))
        self.assertEqual(skool_session.scratch_dir(brain, "modules"), self.brain.parent / ".secrets/scratch/my-cache/modules")
        self.assertEqual(skool_session.source_prefix(brain), "mc")
        args.group, args.port = "alternate", 9444
        self.assertEqual(skool_session.configure(args)[1]["site"], "https://www.skool.com/alternate")
        self.assertEqual(args.port, 9444)
        args.port = 70000
        with self.assertRaises(SystemExit):
            skool_session.configure(args)

    def test_paths_accept_legacy_names_but_stay_in_raw(self):
        expected = self.brain / "raw/community/post.md"
        self.assertEqual(skool_session.raw_path(self.brain, "old-name/raw/community/post.md"), expected)
        self.assertEqual(skool_session.raw_path(self.brain, "raw/community/post.md"), expected)
        with self.assertRaises(ValueError):
            skool_session.raw_path(self.brain, "raw/../../outside.md")
        brainlib.write_text(self.brain / "crawl.yaml", "platform: skool\nsite: https://www.skool.com/my-community\nscratch: ../outside\n")
        with self.assertRaises(SystemExit):
            skool_session.scratch_dir(self.brain)

    def test_new_tab_uses_this_brains_community_with_fake_browser(self):
        page = Mock()
        context = Mock(pages=[])
        context.new_page.return_value = page
        self.assertIs(skool_session.skool_page(Mock(contexts=[context]), self.brain), page)
        page.goto.assert_called_once_with("https://www.skool.com/my-community", wait_until="load")

    def test_source_registry_keeps_existing_ids_and_allocates_after_maximum(self):
        ids = {"course-a/first": "mc-course-a-001", "course-a/later": "mc-course-a-003"}
        self.assertEqual(skool_classroom_map.assign_id(ids, "course-a", "first", "mc"), "mc-course-a-001")
        self.assertEqual(skool_classroom_map.assign_id(ids, "course-a", "inserted", "mc"), "mc-course-a-004")
        self.assertEqual(skool_classroom_map.assign_id(ids, "course-b", "first", "mc"), "mc-course-b-001")

    def test_next_data_redirect_preserves_brain_and_route_parameters(self):
        page = Mock(url="https://www.skool.com/my-community")
        page.evaluate.side_effect = ["build-a", {"status": 200, "text": json.dumps({"pageProps": {"__N_REDIRECT": "/my-community/classroom/course-a?md=lesson-a"}})},
                                     "build-a", {"status": 200, "text": json.dumps({"pageProps": {"self": {"id": "user-a"}, "course": {}}})}]
        browser = Mock(contexts=[Mock(pages=[page])])
        with patch.object(skool_session, "_throttle"):
            result = skool_session.next_data(browser, "my-community/classroom/course-a", brain=self.brain)
        self.assertIn("self", result["pageProps"])
        self.assertEqual(page.evaluate.call_args.args[1], ["https://www.skool.com/_next/data/build-a/my-community/classroom/course-a.json",
                                                         {"group": "my-community", "course": "course-a", "md": "lesson-a"}])

    def test_api_errors_are_not_retried_as_success(self):
        page = Mock(url="https://www.skool.com/my-community")
        browser = Mock(contexts=[Mock(pages=[page])])
        for status, error in ((401, skool_session.NotLoggedIn), (403, skool_session.RateLimited), (429, skool_session.RateLimited)):
            page.evaluate.return_value = {"status": status, "text": "blocked"}
            with self.subTest(status=status), patch.object(skool_session, "_throttle"), self.assertRaises(error):
                skool_session.api_get(browser, "https://api2.skool.com/example", brain=self.brain)

    def test_mux_vtt_and_cached_captions_never_fetch(self):
        vtt = "WEBVTT\n\n1\n00:00:01.500 --> 00:00:03.000 align:start\n<b>Hello</b>\nworld\n\n00:04.000 --> 00:05.000\nNext\n"
        cues = mux_captions.parse_vtt(vtt)
        self.assertEqual(cues, [{"start": 1.5, "end": 3.0, "text": ["Hello world"]}, {"start": 4.0, "end": 5.0, "text": ["Next"]}])
        cache = self.brain / "media/mux"
        brainlib.write_text(cache / "sample.captions.json", json.dumps(cues))
        with patch.object(mux_captions, "_get", side_effect=AssertionError("network forbidden")):
            self.assertEqual(mux_captions.lines({"id": "sample", "expire": 0}, cache), cues)


class SkoolRefreshChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="skool-refresh-", dir=SCRATCH)
        self.addCleanup(temp.cleanup)
        self.brain = Path(temp.name) / "fixture"
        self.site = "https://www.skool.com/fixture"
        self.write("brain.md", "---\nkind: persona\n---\n")
        self.write("crawl.yaml", f"platform: skool\nsite: {self.site}\ncdp_port: 9333\n")
        self.write("sources.yaml", f"""# keep
sources:
- id: acme-community
  url: {self.site}
  last_crawled: null
- id: acme-classroom
  url: {self.site}/classroom
  last_crawled: null
""")

    def write(self, name, text):
        brainlib.write_text(self.brain / name, text)

    def load(self, name):
        return json.loads((self.brain / name).read_text(encoding="utf-8"))

    def run_crawler(self, module, *args):
        command = [module.__name__, "--brain", str(self.brain), *args]
        output = io.StringIO()
        with patch.object(sys, "argv", command), patch.object(module, "sync_playwright", MagicMock()), contextlib.redirect_stdout(output):
            failed = module.main()
        return bool(failed), output.getvalue()

    def test_feed_keeps_cursor_and_pending_changes_across_retries(self):
        feed = skool_feed_index
        thread = skool_thread_crawl

        def post(pid, activity, words):
            return {"id": pid, "name": pid, "groupId": "fixture-group", "createdAt": "2026-01-01T00:00:00Z",
                    "metadata": {"title": pid, "content": words, "comments": 1, "lastComment": activity}}

        first, second = "first-thread", "second-thread"
        original_posts = [post(first, 100, "original"), post(second, 150, "original")]
        changed_posts = [post(first, 300, "edited"), post(second, 250, "edited")]
        index = [feed.row_from_post(row, self.site) for row in original_posts]
        self.write("state/posts.jsonl", "\n".join(map(json.dumps, index)))
        state = {}
        for row in index:
            path = f"raw/community/2026-01/{row['id']}.md"
            self.write(path, "---\nkind: post\n---\nOld capture.\n")
            state[row["id"]] = {**row, "raw_path": path}
        self.write("state/threads_crawled.json", json.dumps(state))
        cursor_path = "state/feed_cursor.json"
        self.write(cursor_path, json.dumps({"activity_ns": 200, "scan_complete": True, "backfill": {"complete": True}}))

        pages = dict(enumerate(changed_posts + [post("older", 100, "older")], start=1))
        pages_seen = []

        def next_page(browser, group, params, **kwargs):
            number = params["p"]
            pages_seen.append(number)
            return {"pageProps": {"postTrees": [{"post": pages[number]}] if number in pages else []}}

        with patch.object(feed, "next_data", side_effect=next_page):
            with patch.object(feed, "write_index", side_effect=OSError("interrupted index write")):
                with self.assertRaises(OSError):
                    self.run_crawler(feed, "--mode", "refresh", "--max-pages", "1")
            self.assertFalse(self.load(cursor_path)["scan_complete"])
            self.assertEqual(set(self.load(cursor_path)["pending_changes"]), {first})
            self.run_crawler(feed, "--mode", "refresh", "--max-pages", "1")
            self.assertEqual(self.load(cursor_path)["activity_ns"], 200)
            self.assertEqual(set(self.load(cursor_path)["pending_changes"]), {first})
            self.run_crawler(feed, "--mode", "refresh")
        self.assertEqual(pages_seen, [1, 1, 1, 2, 3])
        self.assertEqual(self.load(cursor_path)["activity_ns"], 300)
        self.assertEqual(set(self.load(cursor_path)["pending_changes"]), {first, second, "older"})

        with patch.object(thread, "fetch_comments", side_effect=[([], 1, True), ([], 40, False)]):
            failed, report = self.run_crawler(thread, "--tier", "changed")
        self.assertTrue(failed)
        self.assertIn("comment crawl incomplete", report)
        self.assertEqual(set(self.load(cursor_path)["pending_changes"]), {second, "older"})
        self.assertIsNone(brainlib.load_yaml(self.brain / "sources.yaml")["sources"][0]["last_crawled"])

        with patch.object(thread, "fetch_comments", return_value=([], 1, True)):
            self.assertFalse(self.run_crawler(thread, "--tier", "changed")[0])
        self.assertEqual(set(self.load(cursor_path)["pending_changes"]), {"older"})
        sources = brainlib.load_yaml(self.brain / "sources.yaml")["sources"]
        self.assertEqual(str(sources[0]["last_crawled"]), dt.date.today().isoformat())
        self.assertIsNone(sources[1]["last_crawled"])

    def test_backfill_checkpoint_waits_for_the_index_write(self):
        feed = skool_feed_index
        cursor_path = "state/feed_cursor.json"
        self.write(cursor_path, json.dumps({"backfill": {"complete": False, "next_page": 11}}))
        self.write("state/posts.jsonl", "")

        def next_page(browser, group, params, **kwargs):
            pid = f"post-{params['p']}"
            return {"pageProps": {"postTrees": [{"post": {"id": pid, "name": pid, "groupId": "fixture-group",
                                                          "createdAt": "2026-01-01T00:00:00Z",
                                                          "metadata": {"title": pid, "content": "x", "comments": 0}}}]}}

        with patch.object(feed, "next_data", side_effect=next_page),                 patch.object(feed, "write_index", side_effect=OSError("interrupted index write")):
            with self.assertRaises(OSError):
                self.run_crawler(feed, "--mode", "backfill", "--max-pages", "5")
        self.assertEqual(self.load(cursor_path)["backfill"]["next_page"], 11)
        with patch.object(feed, "next_data", side_effect=next_page):
            self.run_crawler(feed, "--mode", "backfill", "--max-pages", "5")
        self.assertEqual(self.load(cursor_path)["backfill"]["next_page"], 14)

    def outline(self, with_files=False):
        lessons = [dict(id=f"lesson-{i}", source_id=f"acme-00{i}", title=f"Lesson {i}", url=f"{self.site}/classroom/{i}",
                        resources=[{"file_name": "sample.txt"}] if with_files else []) for i in (1, 2)]
        self.write("outline.yaml", json.dumps({"courses": [{"code": "course", "title": "Course", "access": True,
                                                            "sections": [{"lessons": lessons}]}]}))
        return lessons

    def test_classroom_keeps_good_items_and_retries_failed_lesson(self):
        self.outline()
        classroom = skool_classroom_crawl
        module = {"metadata": {"desc": "A lesson."}}
        with patch.object(classroom, "module_meta", side_effect=[ValueError("invalid lesson"), (module, None)]) as fetch:
            self.assertFalse(self.run_crawler(classroom, "--dry-run")[0])
            fetch.assert_not_called()
            failed, report = self.run_crawler(classroom)
        self.assertTrue(failed)
        self.assertIn("acme-001: ERROR ValueError: invalid lesson", report)
        self.assertEqual(set(self.load("state/classroom_crawled.json")), {"acme-002"})
        path = self.brain / "sources.yaml"
        self.assertIsNone(brainlib.load_yaml(path)["sources"][1]["last_crawled"])
        with patch.object(classroom, "module_meta", return_value=(module, None)):
            self.assertFalse(self.run_crawler(classroom)[0])
        self.assertEqual(set(self.load("state/classroom_crawled.json")), {"acme-001", "acme-002"})
        self.assertEqual(str(brainlib.load_yaml(path)["sources"][1]["last_crawled"]), dt.date.today().isoformat())

    def test_classroom_with_files_leaves_the_date_to_the_attachment_crawler(self):
        self.outline(with_files=True)
        classroom = skool_classroom_crawl
        with patch.object(classroom, "module_meta", return_value=({"metadata": {"desc": "A lesson."}}, None)):
            failed, report = self.run_crawler(classroom)
        self.assertFalse(failed)
        self.assertIn("classroom date waits for skool_attachments.py", report)
        self.assertIsNone(brainlib.load_yaml(self.brain / "sources.yaml")["sources"][1]["last_crawled"])

    def test_attachments_keep_good_items_and_retry_failed_download(self):
        lessons = self.outline(with_files=True)
        cache = skool_session.scratch_dir(self.brain, "modules")
        for i, lesson in enumerate(lessons, 1):
            resources = json.dumps([{"file_id": f"file-{i}", "file_name": "sample.txt"}])
            brainlib.write_text(cache / f"{lesson['id']}.json", json.dumps({"module": {"metadata": {"resources": resources}}}))
        self.write("state/classroom_crawled.json", json.dumps({
            lesson["source_id"]: {"raw_path": f"raw/classroom/{i}.md"} for i, lesson in enumerate(lessons, 1)}))
        attachments = skool_attachments
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"Fixture bytes"
        url = "https://example.com/sample.txt"
        with patch.object(attachments, "api_get", side_effect=[ValueError("invalid download"), url]) as download, \
                patch.object(attachments.urllib.request, "urlopen", return_value=response):
            self.assertFalse(self.run_crawler(attachments, "--dry-run")[0])
            download.assert_not_called()
            failed, report = self.run_crawler(attachments)
        self.assertTrue(failed)
        self.assertIn("file-1: ERROR ValueError: invalid download", report)
        self.assertEqual(set(self.load("state/attachments.json")), {"file-2"})
        path = self.brain / "sources.yaml"
        self.assertIsNone(brainlib.load_yaml(path)["sources"][1]["last_crawled"])
        with patch.object(attachments, "api_get", return_value=url), \
                patch.object(attachments.urllib.request, "urlopen", return_value=response):
            self.assertFalse(self.run_crawler(attachments)[0])
        self.assertEqual(set(self.load("state/attachments.json")), {"file-1", "file-2"})
        self.assertEqual(str(brainlib.load_yaml(path)["sources"][1]["last_crawled"]), dt.date.today().isoformat())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scratch", type=Path)
    args, remaining = ap.parse_known_args()
    SCRATCH = args.scratch
    if SCRATCH:
        SCRATCH.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[sys.argv[0], *remaining])
