"""Shared helpers for Skool crawlers: attach to the logged-in Chrome and fetch page JSON.

Skool is a Next.js app. Every page's data is available as
  https://www.skool.com/_next/data/<buildId>/<path>.json?<route params>
which we fetch with fetch() inside a skool.com tab, so requests carry the user's own
session and look like normal client-side navigation. No HTML scraping needed.

Rate limits: Skool sits behind CloudFront + AWS WAF. On 2026-10-11 ~280 requests in 6 minutes
(~45/min) got a CloudFront 403 for the whole session. Every request therefore goes through
`_throttle()` (default one request per 5-7 s, plus a 10-min rest every 60), and a 403/429 raises
`RateLimited` so the caller stops, saves its cursor and resumes later, instead of retrying
into the block. Env: SKOOL_MIN_INTERVAL, SKOOL_CHUNK, SKOOL_REST, SKOOL_BUDGET (cap per run).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib

import json
import os
import random
import time
from urllib.parse import urlsplit

BASE = "https://www.skool.com"


def settings(brain):
    """Read this brain's Skool settings without opening a browser or creating a profile."""
    config = brainlib.crawl_config(brain).copy()
    if config.get("platform") != "skool":
        raise SystemExit("set platform: skool in the brain's crawl.yaml")
    site = str(config.get("site") or "").rstrip("/")
    url = urlsplit(site)
    if url.scheme != "https" or url.netloc != "www.skool.com" or len(url.path.strip("/").split("/")) != 1 or not url.path.strip("/") or url.query or url.fragment:
        raise SystemExit("set site: https://www.skool.com/<community> in crawl.yaml")
    config["site"] = site
    config["group"] = url.path.strip("/")
    return config


def configure(args):
    """Resolve --brain and apply optional CLI overrides before any browser connection."""
    brain = brainlib.brain_dir(args.brain)
    config = settings(brain)
    if hasattr(args, "group"):
        args.group = args.group or config["group"]
        if "/" in args.group or "?" in args.group or "#" in args.group:
            raise SystemExit("--group must be a community slug")
        config["site"] = f"{BASE}/{args.group}"
    if hasattr(args, "port"):
        args.port = args.port if args.port is not None else config.get("cdp_port")
        if not isinstance(args.port, int) or isinstance(args.port, bool) or not 1 <= args.port <= 65535:
            raise SystemExit("set cdp_port in crawl.yaml or pass --port (1..65535)")
    return brain, config


def scratch_dir(brain, *parts):
    """Per-brain cache under the private workspace; keep an existing cache name on refresh."""
    name = str(settings(brain).get("scratch") or brain.name)
    if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise SystemExit("crawl.yaml scratch must be a directory name")
    return brainlib.secrets_dir(brain, "scratch", name, *parts)


def source_prefix(brain):
    """Keep this stable after the first crawl: source pages and state use these ids."""
    value = str(settings(brain).get("source_prefix") or brain.name)
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value):
        raise SystemExit("crawl.yaml source_prefix must contain only letters, digits, underscores or hyphens")
    return value


def raw_path(brain, value):
    """Read brain-relative and legacy <brain-name>/raw paths, including in renamed temp copies."""
    path = Path(value)
    if not path.is_absolute():
        if len(path.parts) > 1 and path.parts[1] == "raw":
            path = Path(*path.parts[1:])
        path = brain / path
    path = path.resolve()
    if not path.is_relative_to((brain / "raw").resolve()):
        raise ValueError(f"raw path must stay inside the brain's raw/: {value}")
    return path


class NotLoggedIn(RuntimeError):
    pass


class RateLimited(RuntimeError):
    """CloudFront/WAF block (403/429). Stop the run; wait >= 15 min before one probe request."""


class BudgetExhausted(RuntimeError):
    """This run used its request budget (SKOOL_BUDGET). Save state and resume later."""


MIN_INTERVAL = float(os.environ.get("SKOOL_MIN_INTERVAL", "5.0"))
JITTER = 2.0
CHUNK = int(os.environ.get("SKOOL_CHUNK", "60"))      # after this many requests...
REST = float(os.environ.get("SKOOL_REST", "600"))     # ...rest this many seconds
BUDGET = int(os.environ.get("SKOOL_BUDGET", "0"))     # 0 = unlimited
_last = 0.0
requests_made = 0


def _throttle():
    """Pace requests from any helper: >= MIN_INTERVAL + jitter apart, and a REST pause every CHUNK.

    Second WAF block (2026-10-11) came after ~150 requests in 13 min at ~16/min, so a fixed rate alone
    isn't safe; resting every 60 requests keeps any 5-15 min window well under that.
    """
    global _last, requests_made
    if BUDGET and requests_made >= BUDGET:
        raise BudgetExhausted(f"used {requests_made} requests")
    if CHUNK and requests_made and requests_made % CHUNK == 0:
        print(f"[skool_session] {requests_made} requests; resting {REST:.0f}s", flush=True)
        time.sleep(REST)
    wait = _last + MIN_INTERVAL + random.uniform(0, JITTER) - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    requests_made += 1


def _check_blocked(status, what, text):
    if status in (403, 429):
        raise RateLimited(f"{status} for {what} (requests this run: {requests_made}): {text[:120]!r}")


def skool_page(browser, brain):
    """Return an open skool.com tab, opening one if needed."""
    ctx = browser.contexts[0]
    for page in ctx.pages:
        if page.url.startswith(BASE):
            return page
    page = ctx.new_page()
    page.goto(settings(brain)["site"], wait_until="load")
    return page


def build_id(page):
    bid = page.evaluate("() => window.__NEXT_DATA__ && window.__NEXT_DATA__.buildId")
    if not bid:
        page.reload(wait_until="load")
        bid = page.evaluate("() => window.__NEXT_DATA__ && window.__NEXT_DATA__.buildId")
    return bid


def next_data(browser, path, query=None, delay=1.0, retries=2, follow_redirects=2, *, brain):
    """GET _next/data JSON for a site path like 'my-course/classroom/course-code'.

    Route params are added automatically for the paths we use; pass extras in `query`.
    Raises NotLoggedIn if the response says we're logged out.
    """
    page = skool_page(browser, brain)
    parts = path.strip("/").split("/")
    q = {"group": parts[0]}
    if len(parts) == 2:
        q["post" if parts[1] not in ("classroom", "calendar", "about", "-") else "_"] = parts[1]
    if len(parts) >= 3 and parts[1] == "classroom":
        q["course"] = parts[2]
    q.pop("_", None)
    q.update(query or {})
    for attempt in range(retries + 1):
        bid = build_id(page)
        url = f"{BASE}/_next/data/{bid}/{path.strip('/')}.json"
        _throttle()
        res = page.evaluate(
            """async ([url, q]) => {
              const r = await fetch(url + '?' + new URLSearchParams(q), {credentials: 'include'});
              return {status: r.status, text: await r.text()};
            }""",
            [url, q],
        )
        if res["status"] == 404 and attempt < retries:
            page.reload(wait_until="load")  # buildId changed after a deploy
            continue
        _check_blocked(res["status"], path, res["text"])
        if res["status"] != 200:
            raise RuntimeError(f"{res['status']} for {path}: {res['text'][:200]}")
        data = json.loads(res["text"])
        pp = data.get("pageProps") or {}
        redirect = pp.get("__N_REDIRECT")
        if redirect:
            if "login" in redirect or follow_redirects <= 0:
                raise NotLoggedIn(f"redirected to {redirect} for {path}")
            # e.g. a course URL redirects to its first lesson (?md=<id>)
            rpath, _, rq = redirect.partition("?")
            extra = dict(kv.split("=", 1) for kv in rq.split("&") if "=" in kv)
            return next_data(browser, rpath, {**(query or {}), **extra}, delay, retries, follow_redirects - 1, brain=brain)
        if not pp.get("self"):
            raise NotLoggedIn(f"no session for {path}")
        return data
    raise RuntimeError(f"failed {path}")


def api_get(browser, url, delay=1.0, retries=2, method="GET", raw=False, *, brain):
    """GET a Skool API URL (e.g. api2.skool.com) with the user's session, from inside the tab.

    Returns parsed JSON. Paced by _throttle(); raises RateLimited on 403/429, NotLoggedIn on 401.
    `delay` is kept for backward compatibility (pacing is global now). `method="POST"` sends an empty
    POST (e.g. /files/<id>/download-url); `raw=True` returns the body text instead of parsed JSON.
    """
    page = skool_page(browser, brain)
    for attempt in range(retries + 1):
        _throttle()
        res = page.evaluate(
            """async ([url, method]) => {
              const r = await fetch(url, {credentials: 'include', method});
              return {status: r.status, text: await r.text()};
            }""",
            [url, method],
        )
        _check_blocked(res["status"], url, res["text"])
        if res["status"] == 401:
            raise NotLoggedIn(f"401 for {url}")
        if res["status"] != 200:
            raise RuntimeError(f"{res['status']} for {url}: {res['text'][:200]}")
        return res["text"] if raw else json.loads(res["text"])
    raise RuntimeError(f"failed {url}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Show this brain's Skool session settings (offline; does not attach to Chrome).")
    brainlib.add_brain_arg(ap)
    args = ap.parse_args()
    config = settings(brainlib.brain_dir(args.brain))
    print(json.dumps({k: config.get(k) for k in ("site", "cdp_port", "profile")}, indent=2))
