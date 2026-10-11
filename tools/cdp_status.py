"""Report open tabs in the configured Chrome session without navigating."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, cdp

import argparse

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--port", type=int)
    args = ap.parse_args()
    _, config = configure(args)
    endpoint = cdp(config, args.port)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        for ctx in browser.contexts:
            for page in ctx.pages:
                print(f"{page.url}\t{page.title()}")
        # Disconnect only; the browser stays open for the user.


if __name__ == "__main__":
    main()
