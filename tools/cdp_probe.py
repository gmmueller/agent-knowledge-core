"""Read-only probe of the configured course library."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, cdp, site

import argparse
import json

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--port", type=int)
    ap.add_argument("url", nargs="?")
    args = ap.parse_args()
    _, config = configure(args)
    endpoint = cdp(config, args.port)
    URL = args.url or site(config) + "/library"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.goto(URL, wait_until="networkidle")
            info = page.evaluate(
                """() => {
                  const links = [...document.querySelectorAll('a[href]')]
                    .map(a => ({href: a.href, text: (a.innerText||'').trim().slice(0,80)}))
                    .filter(l => l.href.includes(location.host));
                  const scripts = [...document.scripts].map(s => s.src).filter(Boolean);
                  const iframes = [...document.querySelectorAll('iframe')].map(f => f.src);
                  const videoish = [...document.querySelectorAll('[class*=wistia],[data-wistia-id],[id*=wistia],video,[class*=kjb-video],[data-video-id]')]
                    .map(e => e.outerHTML.slice(0,300));
                  return {title: document.title, url: location.href, links, scripts, iframes, videoish};
                }"""
            )
            print(json.dumps(info, indent=1))
        finally:
            page.close()


if __name__ == "__main__":
    main()
