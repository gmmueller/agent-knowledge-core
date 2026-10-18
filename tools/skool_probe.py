"""Read-only probe of a Skool page: dump __NEXT_DATA__ and the XHR/fetch calls it makes.

Usage: tools/.venv/Scripts/python -I tools/skool_probe.py --brain <brain> <url> <out.json> [--port <port>]
Opens one extra tab in the logged-in Chrome, then closes it. Never types or clicks.
Write output under .secrets/scratch/ (gitignored): it contains community content.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure

import argparse
import json

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    brain, config = configure(args)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        page = browser.contexts[0].new_page()
        calls = []
        page.on("request", lambda r: calls.append(f"{r.method} {r.url}") if r.resource_type in ("xhr", "fetch") else None)
        try:
            page.goto(args.url, wait_until="load")
            page.wait_for_timeout(4000)
            nd = page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); return s ? JSON.parse(s.textContent) : null; }")
            out = {"url": page.url, "title": page.title(), "api_calls": calls, "next_data": nd}
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1, ensure_ascii=False)
            print(f"{page.url}\t{page.title()}\tcalls={len(calls)}\tnext_data={'yes' if nd else 'no'}")
        finally:
            page.close()


if __name__ == "__main__":
    main()
