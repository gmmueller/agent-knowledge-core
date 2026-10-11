"""Configuration and workspace-safe paths shared by source adapters."""
from pathlib import Path

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
    if not isinstance(value, int) or not 1 <= value <= 65535:
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


def map_cache(brain):
    return brainlib.secrets_dir(brain, "scratch", brain.name) / "kajabi-map.json"


def cache_key(value):
    if not value or Path(value).name != value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("cache key must be a filename without directories")
    return value
