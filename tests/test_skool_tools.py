"""Offline Skool parsing and configuration checks; no browser or network access.

Run: python -X utf8 -I tests/test_skool_tools.py --scratch <private-scratch-dir>
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import mux_captions
import skool_classroom_map
import skool_session
import skool_text

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scratch", type=Path)
    args, remaining = ap.parse_known_args()
    SCRATCH = args.scratch
    if SCRATCH:
        SCRATCH.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[sys.argv[0], *remaining])
