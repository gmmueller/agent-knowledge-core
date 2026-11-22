"""Synthetic coverage for local usage and ingest-wave reports."""
import contextlib
import io
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import brainlib
import token_report
import wave_report
import wiki_edits


class TokenTools(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="token-tools-")
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.claude = self.root / "claude"
        self.codex = self.root / "codex"

    def write(self, path, text):
        brainlib.write_text(path, text)

    def jsonl(self, path, rows):
        self.write(path, "\n".join(json.dumps(r) for r in rows) + "\n")

    def run_tool(self, name, *args):
        p = subprocess.run([sys.executable, "-X", "utf8", "-I", str(TOOLS / name), *map(str, args)], capture_output=True)
        return p.returncode, p.stdout.decode("utf-8", errors="replace"), p.stderr.decode("utf-8", errors="replace")

    def usage_fixture(self):
        slug = re.sub(r"[^a-zA-Z0-9]", "-", str(self.workspace)).upper()
        project = self.claude / "projects" / slug
        def user(text, **extra):
            return dict(type="user", message=dict(content=text), **extra)
        def assistant(identity):
            return dict(type="assistant", timestamp="2026-11-02T12:00:00Z", message=dict(id=identity, model="demo-model", usage=dict(input_tokens=100, cache_read_input_tokens=200, cache_creation_input_tokens=40, output_tokens=10)))
        self.jsonl(project / "main.jsonl", [user("hello"), assistant("one"), assistant("one"),
                   user("Delegated task: demo"), user([dict(type="tool_result", content="ignore")]), assistant("two"),
                   user("Reminder: demo"), user("hello", isMeta=True), assistant("three"),
                   user("hello\nreminder"), assistant("four")])
        self.jsonl(project / "main" / "subagents" / "agent.jsonl", [user("<task-notification>demo"), assistant("sub")])
        def session(cwd):
            return [dict(type="session_meta", payload=dict(cwd=str(cwd), timestamp="2026-11-03T00:00:00Z")),
                    dict(type="turn_context", payload=dict(model="demo-codex")),
                    *[dict(type="event_msg", payload=dict(type="token_count", info=dict(total_token_usage=dict(input_tokens=n, cached_input_tokens=20, output_tokens=10), last_token_usage=dict(input_tokens=n)))) for n in (100, 300)]]
        self.jsonl(self.codex / "sessions" / "rollout-one.jsonl", session(self.workspace / "demo-brain"))
        self.jsonl(self.codex / "sessions" / "rollout-outside.jsonl", session(self.root / "workspace-other"))
        return project

    def report(self, *extra):
        code, out, err = self.run_tool("token_report.py", "--workspace", self.workspace, "--claude-dir", self.claude,
                                       "--codex-dir", self.codex, "--json", *extra)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_transcripts_dedupe_totals_triggers_and_cwd(self):
        self.usage_fixture()
        data = self.report()
        self.assertEqual(len(data["sessions"]), 3)
        self.assertEqual(data["totals"]["input_tokens"], 780)
        self.assertEqual(data["totals"]["cache_read_tokens"], 1020)
        self.assertEqual(data["totals"]["cache_write_tokens"], 200)
        self.assertEqual(data["totals"]["output_tokens"], 60)
        self.assertEqual(data["totals"]["input_equivalent"], 1432)
        self.assertEqual(data["trigger_shares"], dict(user=.4, worker=.4, scheduled=.2))
        main = next(r for r in data["sessions"] if r["source"] == "claude")
        self.assertEqual(main["turns"], 4)
        self.assertEqual(main["max_context"], 340)
        codex = next(r for r in data["sessions"] if r["source"] == "codex")
        self.assertEqual(codex["mean_context"], 200)
        self.assertEqual(self.report("--since", "2026-11-03")["total_sessions"], 1)
        self.assertEqual(self.report("--top", "1")["totals"], data["totals"])

    def test_t3_snapshots_and_missing_tables(self):
        path = self.root / "state.sqlite"
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.executescript("CREATE TABLE orchestration_v2_projection_provider_turns(thread_id, started_at, payload_json); CREATE TABLE orchestration_v2_projection_threads(thread_id, project_id, title); CREATE TABLE projection_projects(project_id, workspace_root);")
            db.execute("INSERT INTO projection_projects VALUES (?, ?)", ("project", str(self.workspace)))
            db.execute("INSERT INTO orchestration_v2_projection_threads VALUES ('thread', 'project', 'Demo')")
            for n in (100, 300):
                db.execute("INSERT INTO orchestration_v2_projection_provider_turns VALUES (?, ?, ?)", ("thread", "2026-11-04", json.dumps(dict(model="demo", tokenUsage=dict(usedTokens=n, inputTokens=n, outputTokens=10)))))
        data = self.report("--t3-db", path)
        self.assertEqual(data["sessions"], [])
        r = data["t3_threads"][0]
        self.assertEqual((r["session"], r["turns"], r["max_context"], r["mean_context"]), ("Demo", 2, 300, 200))
        self.assertEqual(data["totals"]["input_equivalent"], 0)
        self.assertIn("snapshots", data["notes"][0])
        empty = self.root / "empty.sqlite"
        sqlite3.connect(empty).close()
        self.assertIn("T3 unavailable", self.report("--t3-db", empty)["notes"][0])

    def brain_fixture(self):
        brain = self.workspace / "demo-brain"
        self.write(brain / "brain.md", "---\nkind: persona\n---\n# Demo\n")
        self.write(brain / "raw/one.md", "Demo source\n")
        self.write(brain / "wiki/sources/one.md", "---\ntype: source\nsources: [raw/one.md]\nupdated: 2026-01-01\nmodule: Demo\nlesson: One\nduration: 90\nurl: https://example.org\n---\n# One\n\n## Key claims\n- **Inference:** Demo.\n")
        self.write(brain / "ingest/staging/a.yaml", "concepts: []\n")
        self.write(brain / "ingest/staging/b.yaml", "concepts: []\ncomment: expert?s\n")
        self.write(brain / "batches.yaml", "a:\n  words: 10\n  items:\n    - id: one\n      raw: ./raw/one\nb:\n  items:\n    - item: absent\n      raw: raw/absent.md\n")
        self.write(brain / "waves.yaml", "# Demo\nfirst:\n  a:\n    worker: demo\n    items:\n      - item: one\n        raw: raw/one.md\nsecond:\n  b:\n    items:\n      - item: absent\n        raw: raw/absent.md\n")
        return brain

    def test_wave_flat_and_waves_real_checker(self):
        brain = self.brain_fixture()
        for name in ("batches.yaml", "waves.yaml"):
            code, out, err = self.run_tool("wave_report.py", "--brain", brain, "--batches", name)
            self.assertEqual(code, 1, err)
            self.assertIn("a: ok (1 pages, staging ok)", out)
            self.assertIn("missing: raw/absent.md", out)
            self.assertIn("ingest/staging/b.yaml:2: possible corruption", out)
            self.assertIn("wave: 1/2 batches ok", out)
        code, out, err = self.run_tool("wave_report.py", "--brain", brain, "--batches", "waves.yaml", "--wave", "first")
        self.assertEqual(code, 0, out + err)
        self.assertIn("wave: 1/1 batches ok", out)

    def test_wave_bad_staging_protection_and_truncation(self):
        brain = self.brain_fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            wiki_edits.record(brain, init=True)
        page = brain / "wiki/sources/one.md"
        self.write(page, page.read_text(encoding="utf-8") + "Human edit\n")
        wiki_edits.begin(brain)
        _, out, _ = self.run_tool("wave_report.py", "--brain", brain, "--batches", "batches.yaml")
        self.assertNotIn("protected page changed", out)  # the human edit predates the pass
        self.write(page, page.read_text(encoding="utf-8") + "Worker edit\n")
        self.write(brain / "ingest/staging/a.yaml", "[invalid")
        code, out, err = self.run_tool("wave_report.py", "--brain", brain, "--batches", "batches.yaml")
        self.assertEqual(code, 1, err)
        self.assertEqual(out.count("protected page changed during the pass: wiki/sources/one.md"), 1)
        self.assertIn("staging:", out)
        _, out, _ = self.run_tool("wave_report.py", "--brain", brain, "--batches", "batches.yaml", "--max-lines", "4")
        self.assertEqual(len(out.splitlines()), 4)
        self.assertIn("more lines", out)
        self.assertTrue(out.splitlines()[-1].startswith("wave:"))

    def test_reference_normalization(self):
        self.assertTrue(wave_report.aliases("./library/demo/raw/one.md") & wave_report.aliases("raw\\one"))


if __name__ == "__main__":
    unittest.main()
