"""Offline library helpers. Run with python -I tests/test_library_tools.py --scratch <directory>."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import library_raw as lr

SCRATCH = None


class LibraryTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="library-tools-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "library").mkdir()
        lr.init(self.root)

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
