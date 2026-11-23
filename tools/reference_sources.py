"""Authority and supersession metadata for reference topic brains."""
from functools import cache
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brainlib
import library_raw


def enabled(settings):
    return settings.get("kind") == "topic" and settings.get("evidence_model") == "reference"


class ReferenceSources:
    def __init__(self, brain, settings):
        self.brain = brain
        self.library = brainlib.library_dir(brainlib.workspace(brain))
        self.official = set(settings.get("official") or [])
        self.sources = {}
        self.publishers = {}
        for path in [brain / "sources.yaml", *sorted(self.library.glob("*/sources.yaml"))]:
            config = brainlib.load_yaml(path) or {}
            publisher = "" if path.parent == brain else path.parent.name
            self.publishers[publisher] = config.get("display_name")
            for source in config.get("sources") or []:
                self.sources[publisher, str(source["id"])] = source

        self.superseded = set()
        for (publisher, source_id), source in self.sources.items():
            if source.get("supersedes") is None:
                continue
            target = str(source["supersedes"])
            scope, sep, identity = target.partition("/")
            key = (scope, identity) if sep else (publisher, target)
            if key not in self.sources and not sep and re.fullmatch(r"\d{4}-\d{2}-\d{2}", target):
                dated = [k for k, entry in self.sources.items() if k[0] == publisher
                         and str(entry.get("published")) == target]
                if len(dated) == 1:
                    key = dated[0]
                elif len(dated) > 1:
                    raise ValueError(f"{source_id}: ambiguous supersedes date {target}; use a source ID")
                else:
                    raise ValueError(f"{source_id}: no source with published date {target}")
            if key == (publisher, source_id):
                raise ValueError(f"{source_id}: a source cannot supersede itself")
            self.superseded.add(key)

    @cache
    def raw_metadata(self, raw):
        parts = PurePosixPath(raw).parts
        if parts[:1] == ("raw",):
            root, publisher, relative = self.brain / "raw", "", parts[1:]
        elif len(parts) >= 4 and parts[0] == "library" and parts[2] == "raw":
            publisher, relative = parts[1], parts[3:]
            root = self.library / publisher / "raw"
        else:
            return "", {}
        if not relative or ".." in parts or "\\" in raw or ":" in raw:
            return publisher, {}
        path = root.joinpath(*relative)
        path = path.with_name(path.name.removesuffix(".md") + ".md").resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            return publisher, {}
        return publisher, brainlib.read_frontmatter(path)

    @cache
    def catalogue(self, publisher):
        return library_raw.read_catalogue_file(self.library / publisher / "catalogue.tsv")

    def metadata(self, publisher, item, *, raw=None, source=None, speaker=None):
        raw = raw or {}
        key = (publisher, item)
        source_key = (publisher, source)
        entry = {**self.sources.get(source_key, {}), **self.sources.get(key, {})}
        speakers = raw.get("speakers") or []
        if isinstance(speakers, str):
            speakers = [speakers]
        names = {speaker, publisher, self.publishers.get(publisher), raw.get("publisher"), raw.get("title"),
                 entry.get("title")} | set(speakers)
        authority = entry.get("authority") or raw.get("authority")
        if not authority and (raw.get("evidence") == "official" or names & self.official):
            authority = "official"
        return {"authority": authority, "version": entry.get("version") or raw.get("version"),
                "superseded": key in self.superseded or source_key in self.superseded}

    def evidence(self, row):
        raw = row.get("raw")
        publisher, front = self.raw_metadata(raw) if raw else ("", {})
        item = front.get("source_id")
        if not item:
            left, _, right = (row.get("item") or "").partition("/")
            if re.fullmatch(r"[\w-]+", left) and left not in {"library", "raw"} and right and "/" not in right:
                publisher, item = left, right
        item = str(item) if item is not None else ""
        catalogue = self.catalogue(publisher).get(item, {}) if publisher else {}
        return {
            "identity": f"{publisher}/{item}" if publisher and item else item or raw,
            **self.metadata(publisher, item, raw=front, source=catalogue.get("source"), speaker=row.get("speaker")),
        }
