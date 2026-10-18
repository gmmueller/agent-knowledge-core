"""Catalogue public web sources and capture immutable paragraph/transcript raw files.

Examples after --workspace <workspace>: list AUTHOR --rss URL; fetch AUTHOR --urls URL; fetch AUTHOR --catalogue.
Run with python -I tools/web_to_raw.py --workspace <workspace> --self-test.
"""
import argparse
import datetime as dt
import email.utils
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib
import library_raw as lr
import trafilatura
import yaml
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
STAMP = r"\d{1,3}:\d{2}(?::\d{2})?"
LABEL = re.compile(rf"^\s*(?:\[?({STAMP})\]?\s*)?([A-Z][\w.'’ -]{{1,60}}?)(?:\s*\[?({STAMP})\]?)?\s*:\s*(.*)$")


class NeedsBrowser(Exception):
    pass


class Client:
    def __init__(self, browser=False):
        self.last = 0
        self.browser = browser
        self._pw = self._ctx = None

    def _browser_get(self, url):
        """Render with headless system Chrome (JS-built or bot-blocked pages); returns (html, final_url)."""
        if self._ctx is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            b = self._pw.chromium.launch(channel="chrome", headless=True)
            self._ctx = b.new_context(user_agent=UA, locale="en-US")
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            return page.content(), page.url
        finally:
            page.close()

    def get(self, url):
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("public HTTP(S) URL required")
        if self.browser:
            time.sleep(max(0, 1 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            return self._browser_get(url)
        for attempt in range(4):
            time.sleep(max(0, 1 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                    data = r.read()
                    if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                        data = gzip.decompress(data)
                    text = data.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
                    if re.search(r"<title[^>]*>\s*(?:just a moment|access denied|attention required)", text, re.I):
                        raise NeedsBrowser("bot block")
                    return text, r.url
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise NeedsBrowser(f"HTTP {e.code}") from e
                if e.code != 429 or attempt == 3:
                    raise
                retry = e.headers.get("Retry-After", "1")
                try:
                    delay = float(retry)
                except ValueError:
                    delay = (email.utils.parsedate_to_datetime(retry) - dt.datetime.now(dt.timezone.utc)).total_seconds()
                time.sleep(max(1, delay))


def log(publisher, message):
    path = lr.pub_dir(publisher) / "crawl-log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- {dt.datetime.now().isoformat(timespec='seconds')} {message}\n")
    print(message, flush=True)


def date(value):
    value = str(value or "")
    match = re.match(r"\d{4}-\d{2}-\d{2}", value)
    if match:
        return match[0]
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (ValueError, TypeError):
        return ""


def config(publisher):
    if lr.slugify(publisher) != publisher:
        raise ValueError("publisher must be an ASCII kebab-case slug")
    path = lr.pub_dir(publisher) / "sources.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"publisher": publisher, "sources": []}


def source_id(cfg, url):
    host = urllib.parse.urlsplit(url).netloc
    return next((s["id"] for s in cfg.get("sources", []) if urllib.parse.urlsplit(s.get("url", "")).netloc == host), "")


def row(cfg, url, title="", published="", description="", kind="post"):
    title = title or urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]) or url
    return dict(id=("pod-" if kind == "podcast" else "web-") + lr.slugify(title), kind=kind,
                title=title, published=date(published), url=url, description=lr.clean_field(description)[:500], source=source_id(cfg, url))


def metadata(html, url):
    soup = BeautifulSoup(html, "html.parser")
    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"]
        return ""
    title = meta("og:title") or (soup.h1.get_text(" ", strip=True) if soup.h1 else soup.title.get_text(" ", strip=True) if soup.title else "")
    published = meta("article:published_time", "date", "datePublished")
    if not published:
        for script in soup.select('script[type="application/ld+json"]'):
            match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', script.get_text())
            if match:
                published = match[1]
                break
    if not published:
        tag = soup.find("time", datetime=True)
        published = tag["datetime"] if tag else ""
    return title, date(published), meta("description", "og:description")


def paragraphs(html, url):
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select('nav, footer, aside, [role="navigation"], [role="contentinfo"]'):
        node.decompose()
    article = soup.find('article')
    if article and len(article.get_text(' ', strip=True).split()) >= 100:
        soup = BeautifulSoup('<html><body>' + str(article) + '</body></html>', 'html.parser')
    for p in soup.find_all('p'):
        separators = ''.join(str(x) for x in p.contents if isinstance(x, str)).strip()
        if p.find('a') and separators and not separators.strip(' >›/|\n\t'):
            p.decompose()
    codes = {}
    for i, heading in enumerate(soup.select('h1,h2,h3,h4,h5,h6')):
        text = heading.get_text(' ', strip=True)
        key = f'LIBRARYHEADING{i}END {text}'
        codes[key] = '## ' + text
        placeholder = soup.new_tag('p')
        placeholder.string = key
        heading.replace_with(placeholder)
    for i, pre in enumerate(soup.select("pre")):
        key = f"LIBRARYCODEBLOCK{i}END"
        code = pre.find("code") or pre
        classes = " ".join(code.get("class", []) + pre.get("class", []))
        language = re.search(r"(?:language-|lang-)([\w+-]+)", classes)
        text = code.get_text().strip("\n")
        fence = "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", text)), default=3))
        codes[key] = f"{fence}{language[1] if language else ''}\n{text}\n{fence}"
        placeholder = soup.new_tag("p")
        placeholder.string = key
        pre.replace_with(placeholder)
    extracted = trafilatura.extract(str(soup), url=url, output_format="xml", include_comments=False,
                                    include_tables=True, include_formatting=True, favor_recall=True)
    if not extracted:
        raise ValueError("no main content extracted")
    tree = ET.fromstring(extracted)
    main = tree.find("main")
    out = []
    def walk(node):
        if node.tag in ("head", "p", "item", "code", "cell"):
            text = lr.clean_field("".join(node.itertext()))
            if text in codes:
                out.append(codes[text])
            elif text:
                out.append(("## " if node.tag == "head" else "- " if node.tag == "item" else "") + text)
        else:
            for child in node:
                walk(child)
    if main is not None:
        walk(main)
    if not out:
        raise ValueError("no paragraph blocks extracted")
    return out


def render_paragraphs(blocks):
    # Shared render_paragraphs collapses whitespace; fenced code needs its original newlines.
    return "\n\n".join(f"**[¶{i}]** {p if p.startswith('```') else p.strip()}" for i, p in enumerate(blocks, 1) if p.strip()) + "\n"


def transcript(html):
    soup = BeautifulSoup(html, "html.parser")
    turns = soup.select('.ep-turn')
    if turns:
        lines = []
        for turn in turns:
            who, words = turn.select_one('.ep-turn__who'), turn.select_one('.ep-turn__text')
            if who and words:
                name = who.find('span')
                stamp = who.find('button')
                if name:
                    speaker = name.get_text(strip=True)
                    parts = words.find_all('p') or [words]
                    spoken = [p.get_text(' ', strip=True) for p in parts]
                    # The live page ends with a repeated speaker and an escaped broken HTML tag.
                    spoken = [p for p in spoken if p != speaker and not p.startswith('<div')]
                    lines.append(dict(speaker=speaker, stamp=stamp.get_text(strip=True) if stamp else None,
                                      text=' '.join(spoken)))
        if lines:
            return lines
    region = soup.select_one('[id*="transcript"]')
    region = region or soup.select_one('article') or soup
    # Support both inline Name: labels and separate speaker/timestamp controls.
    text = region.get_text("\n", strip=True)
    lines, current = [], None
    pending_speaker, pending_time = None, None
    for part in text.splitlines():
        part = part.strip()
        match = LABEL.match(part)
        if match:
            stamp, name, stamp2, words = match.groups()
            stamp = stamp or stamp2
            current = {"speaker": name.strip(), "stamp": stamp, "text": words}
            lines.append(current)
        elif re.fullmatch(STAMP, part) and pending_speaker:
            pending_time = part
        elif re.fullmatch(r"[A-Z][a-zA-Z.'’]+(?: [A-Z][a-zA-Z.'’]+){1,3}", part):
            pending_speaker, pending_time = part, None
        elif pending_speaker:
            current = {"speaker": pending_speaker, "stamp": pending_time, "text": part}
            lines.append(current)
            pending_speaker, pending_time = None, None
        elif current and part not in ("Read the full transcript", "Close transcript"):
            current["text"] += " " + part
    lines = [x for x in lines if x["text"]]
    if not lines:
        raise ValueError("no speaker-labelled transcript found")
    return lines


def appearances(publisher, item_id, speakers, host):
    path = lr.LIBRARY / "people.yaml"
    # Re-read at the last possible moment: other importers may also add people.
    people = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}
    for name in speakers:
        person = people.setdefault(lr.slugify(name), {"name": name, "aliases": [], "appearances": []})
        entries = person.setdefault("appearances", [])
        item = f"{publisher}/{item_id}"
        if not any(x.get("item") == item for x in entries):
            entries.append({"item": item, "role": "host" if name == host else "guest"})
    path.write_text(yaml.safe_dump(people, allow_unicode=True, sort_keys=False), encoding="utf-8")


def listings(args, cfg, client):
    rows, seen = [], set()
    url = args.sitemap or args.rss or args.index or args.datasette
    queue = [url]
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        html, final = client.get(url)
        if args.datasette:
            data = json.loads(html)
            for values in data.get("rows", []):
                r = values if isinstance(values, dict) else dict(zip(data["columns"], values))
                target = r.get("url") or r.get("link")
                if not target and "/simonwillisonblog/blog_entry" in final and r.get("slug") and r.get("created"):
                    created = dt.datetime.fromisoformat(r["created"])
                    target = f"https://simonwillison.net/{created.year}/{created.strftime('%b')}/{created.day}/{r['slug']}/"
                if target:
                    rows.append(row(cfg, target, r.get("title", ""), r.get("created") or r.get("published"), r.get("summary") or r.get("description", ""), args.kind))
            nxt = data.get("next_url") or data.get("next")
            if nxt:
                if str(nxt).startswith(("http", "/", "?")):
                    next_url = urllib.parse.urljoin(final, nxt)
                    # Datasette sometimes advertises http links behind an HTTPS proxy.
                    if final.startswith("https:") and next_url.startswith("http:"):
                        next_url = "https:" + next_url[5:]
                    queue.append(next_url)
                else:
                    parts = urllib.parse.urlsplit(final)
                    query = dict(urllib.parse.parse_qsl(parts.query))
                    query["_next"] = nxt
                    queue.append(urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))))
        elif args.index:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select("a[href]"):
                target = urllib.parse.urljoin(final, a["href"]).split("#")[0]
                if re.search(args.link_match, target):
                    rows.append(row(cfg, target, a.get_text(" ", strip=True), kind=args.kind))
            nxt = soup.select_one(args.next_selector) if args.next_selector else soup.select_one('a[rel~="next"]')
            if nxt and nxt.get("href"):
                queue.append(urllib.parse.urljoin(final, nxt["href"]))
        else:
            root = ET.fromstring(html)
            def value(node, tag):
                return next((x.text or "" for x in node if x.tag.split("}")[-1] == tag), "")
            for node in root.iter():
                tag = node.tag.split("}")[-1]
                if tag == "sitemap":
                    queue.append(urllib.parse.urljoin(final, value(node, "loc")))
                elif tag == "url":
                    # Sitemap lastmod is a modification date, not a publication date.
                    rows.append(row(cfg, value(node, "loc"), kind=args.kind))
                elif tag in ("item", "entry"):
                    target = value(node, "link") or next((x.get("href") for x in node if x.tag.endswith("link") and x.get("rel", "alternate") == "alternate"), "")
                    if target:
                        rows.append(row(cfg, target, value(node, "title"), value(node, "pubDate") or value(node, "published"), value(node, "description") or value(node, "summary"), args.kind))
    rows = list({r["url"]: r for r in rows if not args.match or re.search(args.match, r["url"] + " " + r["title"])}.values())
    occupied = {r['id']: r['url'] for r in lr.read_catalogue(args.publisher).values()}
    for r in rows:
        if r['id'] in occupied and occupied[r['id']] != r['url']:
            import hashlib
            r['id'] = r['id'][:55] + '-' + hashlib.sha256(r['url'].encode()).hexdigest()[:8]
        occupied[r['id']] = r['url']
    added, updated = lr.merge_catalogue(args.publisher, rows)
    log(args.publisher, f"list: {len(rows)} items; {added} added, {updated} updated; {len(lr.read_catalogue(args.publisher))} total")


def fetch(args, cfg, client):
    catalogue = lr.read_catalogue(args.publisher)
    if args.items:
        missing = set(args.items) - catalogue.keys()
        if missing:
            raise ValueError(f"unknown catalogue IDs: {sorted(missing)}")
        selected = [catalogue[x] for x in args.items]
    elif args.catalogue:
        selected = [r for r in catalogue.values() if r["kind"] in ("post", "doc", "podcast") and (not args.match or re.search(args.match, r["url"] + " " + r["title"]))]
    else:
        by_url = {r['url']: r for r in catalogue.values()}
        selected = [by_url.get(u, {"url": u}) for u in args.urls]
    if args.limit is not None:
        selected = selected[:args.limit]
    failures = 0
    captured = set()
    for existing in (lr.pub_dir(args.publisher) / 'raw' / ('pod' if args.transcript else 'web')).glob('*.md'):
        front = yaml.safe_load(existing.read_text(encoding='utf-8').split('---', 2)[1])
        captured.add(front.get('url'))
    for old in selected:
        url = old["url"]
        try:
            if url in captured and not args.recapture:
                log(args.publisher, f"skip captured URL: {url}")
                continue
            html, final = client.get(url)
            title, published, description = metadata(html, final)
            r = row(cfg, url, title or old.get("title", ""), published or old.get("published", ""), description,
                    "podcast" if args.transcript else old.get("kind", args.kind))
            # Keep listed IDs stable when page title metadata is richer than discovery metadata.
            if old.get("id") and not args.transcript:
                r["id"] = old["id"]
            path = lr.raw_path(args.publisher, "pod" if args.transcript else "web", r["published"], r["title"])
            if args.recapture:
                path = path.with_stem(path.stem + '-recapture-' + dt.date.today().strftime('%Y%m%d'))
            if path.exists():
                log(args.publisher, f"skip existing: {path.relative_to(lr.ROOT)}")
                continue
            speakers = [cfg["default_speaker"]] if cfg.get("default_speaker") else []
            if args.transcript:
                lines = transcript(html)
                speakers = list(dict.fromkeys(x["speaker"] for x in lines))
                if all(x['stamp'] for x in lines):
                    def seconds(stamp):
                        total = 0
                        for part in stamp.split(':'):
                            total = total * 60 + int(part)
                        return total
                    timed = [dict(start=seconds(x['stamp']), end=seconds(lines[i + 1]['stamp']) if i + 1 < len(lines) else seconds(x['stamp']), speaker=x['speaker'], text=x['text']) for i, x in enumerate(lines)]
                    body = lr.render_transcript(lr.transcript_blocks(timed))
                else:
                    body = "\n\n".join(f"**[{x['stamp'] or '¶' + str(i)}]** {x['speaker']}: {lr.clean_field(x['text'])}" for i, x in enumerate(lines, 1)) + "\n"
            else:
                body = render_paragraphs(paragraphs(html, final))
            front = dict(source_id=r["id"], publisher=args.publisher, title=r["title"], url=url, kind=r["kind"], published=r["published"],
                         method="transcript-page" if args.transcript else "page-text", speakers=speakers,
                         speaker_method="transcript" if args.transcript else "single")
            if final != url:
                front["fetched_url"] = final
            lr.write_raw(path, front, body)
            captured.add(url)
            lr.merge_catalogue(args.publisher, [r])
            if args.transcript:
                appearances(args.publisher, r["id"], speakers, args.host or cfg.get("host") or cfg.get("default_speaker"))
            log(args.publisher, f"fetched: {path.relative_to(lr.ROOT)}; {len(body.split())} words; speakers={speakers}")
        except NeedsBrowser as e:
            failures += 1
            log(args.publisher, f"needs browser: {url}: {e}")
        except (ValueError, OSError, ET.ParseError) as e:
            failures += 1
            log(args.publisher, f"failed: {url}: {e}")
    return failures


def self_test():
    html = '<article><h1>A heading</h1><p>A useful paragraph about testing software and preserving its original content.</p><ul><li>First useful item.</li><li>Second useful item.</li></ul><pre><code class="language-python">if True:\n    print("yes")\n</code></pre><p>Another useful paragraph to conclude this example.</p></article>'
    blocks = paragraphs(html, "https://example.com/test")
    assert "## A heading" in blocks and "- First useful item." in blocks
    assert '```python\nif True:\n    print("yes")\n```' in blocks, blocks
    body = render_paragraphs(blocks)
    assert body == render_paragraphs(paragraphs(html, "https://example.com/test"))
    assert re.findall(r"\*\*\[¶(\d+)\]", body) == [str(i) for i in range(1, len(blocks) + 1)]
    assert transcript('<div id="transcript"><p>Alex Host: Hello.</p><p>Jamie Guest: Hi!</p></div>')[1]["speaker"] == "Jamie Guest"
    assert transcript('<div id="transcript"><b>Alex Host</b><button>0:03</button><p>Hello.</p></div>')[0]["stamp"] == "0:03"
    from unittest.mock import patch
    class FixtureClient:
        def __init__(self, pages):
            self.pages = pages
            self.visited = []
        def get(self, url):
            self.visited.append(url)
            return self.pages[url], url
    def check_listing(mode, pages, expected, **extra):
        args = argparse.Namespace(publisher='fixture', sitemap=None, rss=None, index=None, datasette=None,
                                  link_match='example.com/post', next_selector=None, match=None, kind='post')
        setattr(args, mode, 'https://example.com/start')
        for key, value in extra.items():
            setattr(args, key, value)
        client = FixtureClient(pages)
        with patch.object(lr, 'merge_catalogue', return_value=(expected, 0)) as merge, patch.object(lr, 'read_catalogue', return_value={}), patch(__name__ + '.log'):
            listings(args, {'sources': []}, client)
            assert len(merge.call_args.args[1]) == expected, merge.call_args
        return client
    check_listing('rss', {'https://example.com/start': '<rss><channel><item><title>Post</title><link>https://example.com/post</link><pubDate>Tue, 10 Oct 2023 00:00:00 GMT</pubDate></item></channel></rss>'}, 1)
    check_listing('sitemap', {'https://example.com/start': '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.com/child</loc></sitemap></sitemapindex>', 'https://example.com/child': '<urlset><url><loc>https://example.com/post</loc><lastmod>2026-01-01</lastmod></url></urlset>'}, 1)
    check_listing('index', {'https://example.com/start': '<a href="/post">Post</a><a rel="next" href="/page2">Next</a>', 'https://example.com/page2': '<a href="/post2">Post two</a><a rel="next" href="/start">Start</a>'}, 2)
    check_listing('datasette', {'https://example.com/start': json.dumps({'columns': ['title', 'url'], 'rows': [['Post', 'https://example.com/post']], 'next_url': 'http://example.com/page2'}), 'https://example.com/page2': json.dumps({'rows': [{'title': 'Post two', 'url': 'https://example.com/post2'}]})}, 2)
    print("self-test passed")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(parser)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    listing = sub.add_parser("list")
    listing.add_argument("publisher")
    group = listing.add_mutually_exclusive_group(required=True)
    for option in ("sitemap", "rss", "index", "datasette"):
        group.add_argument("--" + option)
    listing.add_argument("--link-match")
    listing.add_argument("--next-selector")
    fetching = sub.add_parser("fetch")
    fetching.add_argument("publisher")
    group = fetching.add_mutually_exclusive_group(required=True)
    group.add_argument("--urls", nargs="+")
    group.add_argument("--items", nargs="+")
    group.add_argument("--catalogue", action="store_true")
    fetching.add_argument("--limit", type=int)
    fetching.add_argument("--transcript", action="store_true")
    fetching.add_argument("--recapture", action="store_true", help="write a dated new capture, preserving existing raw files")
    fetching.add_argument("--host", help="transcript host name (or set host in sources.yaml)")
    fetching.add_argument("--browser", action="store_true", help="render pages in headless Chrome (JS-built or bot-blocked pages)")
    for command in (listing, fetching):
        command.add_argument("--match")
        command.add_argument("--kind", choices=("post", "doc"), default="post")
    args = parser.parse_args()
    lr.init(args.workspace)
    if args.self_test:
        self_test()
        return
    if not args.command:
        parser.error("choose list or fetch")
    if args.command == "list" and args.index and not args.link_match:
        parser.error("--index requires --link-match")
    cfg, client = config(args.publisher), Client(browser=getattr(args, "browser", False))
    if args.command == "list":
        listings(args, cfg, client)
    else:
        sys.exit(bool(fetch(args, cfg, client)))


if __name__ == "__main__":
    main()
