"""Topic rule status across staging, bundles and wiki pages."""
import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import brainlib
import wiki_edits


class RuleStatus(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="rule-status-")
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.brain = self.root / "topic"
        self.settings()

    def settings(self, **config):
        brainlib.write_text(self.brain / "brain.md", "---\n" + yaml.safe_dump(dict(kind="topic", **config)) + "---\n")

    def tool(self, name, *args):
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", str(TOOLS / name), "--brain", str(self.brain), *args],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def page(self, slug, status="bench", extra="", body=""):
        page = self.brain / "wiki" / "rules" / f"{slug}.md"
        brainlib.write_text(page, f"---\ntype: rule\nstatus: {status}\n{extra}---\n# Rule\n{body}")
        return page

    def source(self, speaker, identity, publisher="acme", **metadata):
        raw = f"library/{publisher}/raw/{identity}"
        brainlib.write_text(self.root / (raw + ".md"), f"---\npublisher: {publisher}\nsource_id: {identity}\n---\nExample.\n")
        return dict(speaker=speaker, text="Example.", cite=dict(raw=raw, at="1:00"), **metadata)

    def rule(self, slug, points, quotes=None):
        stage = self.brain / "ingest" / "staging" / f"{slug}.yaml"
        brainlib.write_text(stage, yaml.safe_dump(dict(concepts=[dict(slug=slug, type="rule", points=points, quotes=quotes or [])])))

    def bundle(self, slug):
        return brainlib.load_yaml(self.brain / "ingest" / "bundles" / f"{slug}.yaml")

    def test_merge_and_audit_use_the_configured_independence_threshold(self):
        slug = "rule-repeat"
        self.rule(slug, [self.source("Visitor", identity) for identity in ("one", "two", "three")])
        page = self.page(slug)
        self.tool("merge_topic.py", "bundles")
        self.assertEqual(self.bundle(slug)["status"], "active")
        self.assertIn("bench -> active", self.tool("rule_status.py", "--write"))
        self.assertEqual(brainlib.read_frontmatter(page)["status"], "active")

        self.settings(rule_status="voices")
        self.tool("merge_topic.py", "bundles")
        self.assertEqual(self.bundle(slug)["status"], "bench")
        self.assertIn("active -> bench", self.tool("rule_status.py"))
        self.assertEqual(brainlib.read_frontmatter(page)["status"], "active")

    def test_aliases_and_hosts_have_the_same_effect_in_both_tools(self):
        self.settings(rule_status="voices", experts=["Ada", "Bea"], expert_aliases={"Ada and coauthors": "Ada", "Host": "Bea"},
                      voice_aliases={"Ada": "Platform", "Staff": "Platform"}, hosts=["Host"])
        evidence = [self.source(speaker, item) for speaker, item in
                    [("Ada and coauthors", "one"), ("Ada", "two"), ("Staff", "three"), ("Host", "four")]]
        self.rule("rule-one-voice", evidence)
        self.rule("rule-two-experts", evidence + [self.source("Bea", "five")])
        self.page("rule-one-voice", "active")
        self.page("rule-two-experts")
        self.tool("merge_topic.py", "bundles")
        self.assertEqual(self.bundle("rule-one-voice")["status"], "bench")
        self.assertEqual(self.bundle("rule-two-experts")["status"], "consensus")
        audit = self.tool("rule_status.py")
        self.assertIn("active -> bench  (Platform)", audit)
        self.assertIn("bench -> consensus  (Bea, Platform)", audit)

    def test_stance_round_trips_and_blocks_automatic_consensus(self):
        self.settings(experts=["Ada", "Bea", "Cam"], expert_aliases={"Guest": "Bea"})
        ada = self.source("Ada", "one")
        bea = self.source("Guest", "two", publisher="bravo", stance="opposes")
        cam = self.source("Cam", "three", publisher="charlie", stance="nuances")
        self.rule("rule-one-supporter", [ada, cam], [bea])
        self.rule("rule-two-supporters", [ada, {**cam, "stance": "supports"}], [bea])
        one = self.page("rule-one-supporter", "consensus")
        two = self.page("rule-two-supporters", "consensus")
        for tool, args in [("merge_topic.py", ("bundles",)), ("rule_status.py", ("--write",))]:
            output = self.tool(tool, *args)
            for slug in ("rule-one-supporter", "rule-two-supporters"):
                self.assertIn(f"{slug}: contested candidate (opposition from Bea)", output)
        first = self.bundle("rule-one-supporter")
        self.assertEqual(first["quotes"][0]["stance"], "opposes")
        self.assertEqual(first["points"][1]["stance"], "nuances")
        self.assertEqual(first["experts"], ["Ada"])
        self.assertEqual(first["status"], "bench")
        self.assertEqual(self.bundle("rule-two-supporters")["status"], "active")
        self.assertEqual(brainlib.read_frontmatter(one)["status"], "bench")
        self.assertEqual(brainlib.read_frontmatter(two)["status"], "active")

    def test_wiki_locks_and_contested_status_survive_both_tools(self):
        self.settings(experts=["Ada", "Bea"])
        evidence = [self.source("Ada", "one"), self.source("Bea", "two")]
        locked = self.page("rule-locked", extra="status_locked: true # editorial decision\n")
        contested = self.page("rule-contested", "contested")
        for page in (locked, contested):
            self.rule(page.stem, evidence)
        self.tool("merge_topic.py", "bundles")
        self.assertEqual(self.bundle(locked.stem)["status"], "bench")
        self.assertEqual(self.bundle(contested.stem)["status"], "contested")
        self.assertNotIn(" -> ", self.tool("rule_status.py", "--write"))
        self.assertEqual(brainlib.read_frontmatter(locked)["status"], "bench")
        self.assertEqual(brainlib.read_frontmatter(contested)["status"], "contested")

    def test_audit_updates_agent_pages_during_open_pass(self):
        self.settings(experts=["Ada", "Bea"])
        quote = '> "Example." - {} ([[{}]] @ 1:00)\n'
        body = "".join(quote.format(s, self.source(s, item)["cite"]["raw"])
                       for s, item in [("Ada", "one"), ("Bea", "two")])
        self.page("rule-human")
        self.page("rule-agent")
        with contextlib.redirect_stdout(io.StringIO()):
            wiki_edits.record(self.brain, init=True)
            human = self.page("rule-human", body=body + "Human edit.\n")
            self.assertEqual(wiki_edits.begin(self.brain), ["rules/rule-human.md"])
        agent = self.page("rule-agent", "'bench' # keep comment", body=body)
        self.assertEqual(self.tool("rule_status.py").count("bench -> consensus"), 2)
        self.assertIn("status: 'bench' # keep comment", agent.read_text(encoding="utf-8"))
        self.tool("rule_status.py", "--write")
        self.assertIn("status: consensus # keep comment", agent.read_text(encoding="utf-8"))
        self.assertEqual(brainlib.read_frontmatter(human)["status"], "bench")


if __name__ == "__main__":
    unittest.main()
