"""Configuration and workspace-safe paths shared by source adapters."""
import datetime as dt
from pathlib import Path
from urllib.parse import urlsplit
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brainlib


def configure(args):
    brain = brainlib.brain_dir(args.brain)
    return brain, brainlib.crawl_config(brain)


def site(config, override=None):
    value = override or config.get("site")
    if not value or not value.startswith(("https://", "http://")):
        raise SystemExit("set site in crawl.yaml or pass --site")
    return value.rstrip("/")


def cdp(config, port=None):
    value = port if port is not None else config.get("cdp_port")
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise SystemExit("set cdp_port in crawl.yaml or pass --port (1..65535)")
    return f"http://127.0.0.1:{value}"


def brain_path(brain, value):
    """Accept brain-relative paths and older workspace-relative brain/media or brain/raw paths."""
    path = Path(value)
    if not path.is_absolute():
        parts = path.parts
        if len(parts) > 1 and parts[1] in {"raw", "media"}:
            path = Path(*parts[1:])
        path = brain / path
    path = path.resolve()
    if not path.is_relative_to(brain.resolve()):
        raise ValueError(f"path must stay inside the brain: {value}")
    return path


def match_source(sources, url):
    """Prefer exact URLs and the most specific path, then a matching host."""
    target = urlsplit(url or "")
    if not target.netloc:
        return ""
    matches = []
    for source in sources:
        for key in ("url", "rss"):
            candidate = urlsplit(source.get(key) or "")
            if target.netloc != candidate.netloc:
                continue
            path = candidate.path.rstrip("/")
            target_path = target.path.rstrip("/")
            if target_path == path and target.query == candidate.query:
                rank = (2, len(path))
            elif target_path.startswith(path + "/"):
                rank = (1, len(path))
            else:
                rank = (0, 0)
            matches.append((rank, source["id"]))
    return max(matches, key=lambda entry: entry[0])[1] if matches else ""


def stamp_sources(folder, updates):
    """Apply updates by source ID without replacing unrelated settings."""
    path = folder / "sources.yaml"
    if not updates or not path.exists():
        return

    def update(data):
        changed = False
        for source in data.get("sources") or []:
            fields = updates.get(source.get("id"), {})
            for key, value in fields.items():
                if str(source.get(key)) != str(value):
                    source[key] = value
                    changed = True
        return changed

    brainlib.edit_yaml(path, update)


def stamp_crawl(folder, ids):
    stamp_sources(folder, {sid: {"last_crawled": dt.date.today().isoformat()} for sid in ids if sid})


def stamp_skool(brain, url):
    path = brain / "sources.yaml"
    sources = (brainlib.load_yaml(path, {}) or {}).get("sources") or []
    match = next((s["id"] for s in sources if str(s.get("url") or "").rstrip("/") == url), None)
    if match:
        stamp_crawl(brain, [match])


def map_cache(brain):
    return brainlib.secrets_dir(brain, "scratch", brain.name) / "kajabi-map.json"


def cache_key(value):
    if not value or Path(value).name != value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("cache key must be a filename without directories")
    return value
