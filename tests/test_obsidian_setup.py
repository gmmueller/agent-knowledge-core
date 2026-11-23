"""Independent vault setup, settings preservation and directory-link safety."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import obsidian_setup as setup

TOOLS = Path(__file__).resolve().parents[1] / "tools"


class ObsidianSetup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vault-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.brain = self.root / "example core"
        brainlib.write_text(self.brain / "brain.md", "---\nkind: topic\ndisplay_name: Example Core\nskill:\n  short_description: Advice with citations\n---\n")
        brainlib.write_text(self.root / "library/publisher/raw/text.md", "Real source text")

    def run_setup(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", "-I", str(TOOLS / "obsidian_setup.py"),
                               *map(str, args)], capture_output=True, text=True, encoding="utf-8")

    def test_settings_written_and_idempotent(self):
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        app = self.brain / ".obsidian/app.json"
        graph = self.brain / ".obsidian/graph.json"
        self.assertEqual(json.loads(app.read_text(encoding="utf-8")), setup.APP)
        settings = json.loads(graph.read_text(encoding="utf-8"))
        self.assertEqual(len(settings["colorGroups"]), 12)
        self.assertIn('path:"wiki/tools/"', [g["query"] for g in settings["colorGroups"]])
        self.assertIn('path:"wiki/"', settings["search"])
        self.assertIn('-path:"raw/"', settings["search"])
        self.assertIn('-path:"library/"', settings["search"])
        before = app.read_bytes(), graph.read_bytes()
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((app.read_bytes(), graph.read_bytes()), before)

    def test_merge_keeps_user_values_and_reset_rewrites(self):
        custom_group = {"query": 'path:"wiki/rules/"', "color": {"a": 0.5, "rgb": 123}}
        brainlib.write_text(self.brain / ".obsidian/app.json", json.dumps({"theme": "dark", "userIgnoreFilters": ["drafts/"]}))
        brainlib.write_text(self.brain / ".obsidian/graph.json", json.dumps({"search": "custom", "scale": 2, "colorGroups": [custom_group]}))
        with contextlib.redirect_stdout(io.StringIO()):
            setup.setup(self.brain)
        app = json.loads((self.brain / ".obsidian/app.json").read_text(encoding="utf-8"))
        graph = json.loads((self.brain / ".obsidian/graph.json").read_text(encoding="utf-8"))
        self.assertEqual(app["theme"], "dark")
        self.assertIn("drafts/", app["userIgnoreFilters"])
        self.assertEqual(graph["search"], "custom")
        self.assertEqual(graph["scale"], 2)
        self.assertEqual(graph["colorGroups"][0], custom_group)
        result = self.run_setup("--brain", self.brain, "--reset")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.brain / ".obsidian/app.json").read_text(encoding="utf-8")), setup.APP)
        self.assertEqual(json.loads((self.brain / ".obsidian/graph.json").read_text(encoding="utf-8")), setup.GRAPH)

    def test_library_link_resolves_and_brain_walk_ignores_it(self):
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        link = self.brain / "library"
        self.assertTrue(brainlib.is_directory_link(link))
        self.assertEqual(link.resolve(), self.root / "library")
        self.assertEqual((link / "publisher/raw/text.md").read_text(encoding="utf-8"), "Real source text")
        self.assertFalse(any("library" in p.relative_to(self.brain).parts for p in brainlib.iter_files(self.brain)))
        self.assertFalse(list(brainlib.wiki_pages(self.brain)))

    def test_library_refuses_real_folder(self):
        folder = self.brain / "library"
        folder.mkdir()
        brainlib.write_text(folder / "keep.md", "Do not touch")
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 2)
        self.assertIn("real library folder", result.stderr)
        self.assertEqual((folder / "keep.md").read_text(encoding="utf-8"), "Do not touch")
        self.assertFalse((self.brain / ".obsidian").exists())

    def test_broken_link_is_not_replaced(self):
        other = self.root / "other"
        other.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            setup.link_library(self.brain)
        link = self.brain / "library"
        # Rename the real target: the existing link must now be refused, never recreated.
        (self.root / "library").rename(other / "library")
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(brainlib.is_directory_link(link))

    def test_wrong_target_is_refused(self):
        other = self.root / "other-library"
        other.mkdir()
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(brainlib, "library_dir", return_value=other):
            setup.link_library(self.brain)
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 2)
        self.assertIn("points elsewhere", result.stderr)
        self.assertEqual((self.brain / "library").resolve(), other)

    def test_gitignore_appended_once_and_notes_preserved(self):
        brainlib.write_text(self.brain / ".gitignore", "custom-entry")
        brainlib.write_text(self.brain / "notes/README.md", "My own notes\n")
        for _ in range(2):
            result = self.run_setup("--brain", self.brain)
            self.assertEqual(result.returncode, 0, result.stderr)
        lines = (self.brain / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["custom-entry", "/library", "/.obsidian/workspace*.json"])
        self.assertEqual((self.brain / "notes/README.md").read_text(encoding="utf-8"), "My own notes\n")

    def test_all_hub_has_only_independent_vault_links(self):
        second = self.root / "another-core"
        brainlib.write_text(second / "brain.md", "---\ndisplay_name: Another Core\nkind: persona\nskill: {short_description: Another subject}\n---\n")
        result = self.run_setup("--workspace", self.root, "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reminder", result.stdout)
        hub = (self.root / ".cores-hub/Knowledge cores.md").read_text(encoding="utf-8")
        self.assertIn("Each core is independent.", hub)
        self.assertIn("Advice with citations", hub)
        self.assertIn("Another subject", hub)
        self.assertNotIn("[[", hub)
        self.assertNotIn("wiki/", hub)
        for brain in (self.brain, second):
            uri = setup.open_uri(brain)
            self.assertIn(uri, hub)
            self.assertEqual(parse_qs(urlparse(uri).query)["path"], [str(brain)])
        self.assertFalse((self.root / ".gitignore").exists())
        for _ in range(2):
            result = self.run_setup("--workspace", self.root, "--all", "--gitignore-hub")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / ".gitignore").read_text(encoding="utf-8"), "/.cores-hub/\n")
        self.assertFalse((second / "library").exists())

    def test_bad_json_is_not_overwritten(self):
        brainlib.write_text(self.brain / ".obsidian/app.json", "broken{")
        result = self.run_setup("--brain", self.brain)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.brain / ".obsidian/app.json").read_text(encoding="utf-8"), "broken{")


if __name__ == "__main__":
    unittest.main()
