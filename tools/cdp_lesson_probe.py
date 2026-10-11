"""Read-only probe of one lesson: embeds, attachments and requests."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, cdp

import argparse
import json
import re

from playwright.sync_api import sync_playwright

INTERESTING = re.compile(r"wistia|vimeo|mux|kajabi-cdn|hls|\.m3u8|\.vtt|\.srt|caption|transcript|/api/|\.json", re.I)
NOISE = re.compile(r"facebook|tiktok|pinimg|pinterest|licdn|ads-twitter|google|hubspot|hs-banner|hscollected|mouseflow|rokt|useproof|mccdn", re.I)

def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--port", type=int)
    ap.add_argument("url")
    args = ap.parse_args()
    _, config = configure(args)
    endpoint = cdp(config, args.port)
    URL = args.url
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        page = browser.contexts[0].new_page()
        reqs = []
        page.on("request", lambda r: reqs.append(f"{r.method} {r.resource_type} {r.url[:220]}"))
        try:
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(3000)
            info = page.evaluate(
                """() => {
                  const q = s => [...document.querySelectorAll(s)];
                  return {
                    title: document.title,
                    h1: q('h1,h2').map(e => e.innerText.trim()).slice(0,5),
                    iframes: q('iframe').map(f => f.src).filter(Boolean),
                    video: q('video,source').map(v => v.src || v.currentSrc).filter(Boolean),
                    wistia: q('[class*=wistia_async_],[data-wistia-id]').map(e => e.className || e.dataset.wistiaId),
                    dataattrs: q('[data-video-id],[data-media-id],[data-hashed-id],[data-wistia-id]').map(e => e.outerHTML.slice(0,250)),
                    downloads: q('a[href]').filter(a => /download|\\.pdf|attachment|amazonaws|kajabi-storefronts/i.test(a.href)).map(a => ({href: a.href.slice(0,200), text: a.innerText.trim().slice(0,60)})),
                    bodyText: (document.querySelector('.kjb-post-content, .post-body, .panel-body, main') || document.body).innerText.slice(0,1500),
                    kjbVars: Object.keys(window).filter(k => /kajabi|wistia|Kjb|mux/i.test(k)),
                  };
                }"""
            )
            info["requests"] = [r for r in reqs if INTERESTING.search(r) and not NOISE.search(r)]
            print(json.dumps(info, indent=1, ensure_ascii=False))
        finally:
            page.close()


if __name__ == "__main__":
    main()
