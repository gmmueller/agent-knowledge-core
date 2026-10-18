"""Fetch Skool page data as JSON via Next.js `_next/data`, from inside the logged-in tab.

Usage: tools/.venv/Scripts/python -I tools/skool_next.py --brain <brain> <path> <out.json> [--port <port>] [--query k=v ...]
  <path> is the site path without the domain, e.g. my-community/classroom/course-code
Read-only: reuses (or opens) one skool.com tab and calls fetch() there, so it sends the
user's own session. Never types or clicks. Write output under .secrets/scratch/.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure

import argparse
import json
import os

from playwright.sync_api import sync_playwright

from skool_session import next_data

def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("path")
    ap.add_argument("out")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--query", nargs="*", default=[])
    args = ap.parse_args()
    brain, config = configure(args)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        query = dict(kv.split("=", 1) for kv in args.query)
        data = next_data(browser, args.path, query, brain=brain)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        print(f"{args.path}\tkeys={list((data.get('pageProps') or {}).keys())[:12]}")


if __name__ == "__main__":
    main()
