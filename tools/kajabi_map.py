"""Map a Kajabi site into outline.yaml and sources.yaml.

Use --build-only to rebuild from the workspace cache without browser or network access.
Requests are sequential; login redirects, challenges and server errors stop the crawl."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, brain_path, cdp, site, map_cache

import argparse
import datetime
import json
import random
import re
import time
import urllib.error
import urllib.request

import yaml

# ---------------------------------------------------------------- in-page JS

JS_COMMON = r"""
async function getDoc(u) {
  const r = await fetch(u, {credentials: 'include', redirect: 'follow'});
  const t = await r.text();
  return {r, t, d: new DOMParser().parseFromString(t, 'text/html')};
}
const norm = s => (s || '').replace(/[ \s]+/g, ' ').trim();
"""

JS_LISTING = "(() => {" + JS_COMMON + " return " + r"""async (u) => {
  const {r, t, d} = await getDoc(u);
  const out = {status: r.status, final: r.url, len: t.length,
               challenge: /Just a moment|cf-challenge|challenge-platform/i.test(t.slice(0, 6000))};
  out.logged_in = !d.querySelector('input[type=password], form[action*="sign_in"], form[action$="/login"]');
  const hd = d.querySelector('#section-category_body h5, #section-category_body h1, .marquee h1') || d.querySelector('h1');
  out.h1 = hd ? norm(hd.textContent) : null;
  out.crumbs = [...d.querySelectorAll('.breadcrumbs .crumb, #section-breadcrumbs div')].map(c => norm(c.textContent)).filter(Boolean);
  out.post_count_label = (out.crumbs.find(c => /^\d+\s+posts?$/i.test(c)) || null);
  const lab = [...d.querySelectorAll('h6')].map(e => norm(e.textContent)).find(x => /\d+\s+of\s+\d+\s+Lessons/i.test(x));
  out.lessons_label = lab || null;
  const skip = '.breadcrumbs, #section-breadcrumbs, .header, #section-header, .footer, #section-footer, nav';
  const selfCid = (new URL(u).pathname.match(/\/categories\/(\d+)\/?$/) || [])[1];
  out.children = [];
  const seen = new Set();
  d.querySelectorAll('a[href]').forEach(a => {
    if (a.closest(skip)) return;
    const href = new URL(a.getAttribute('href'), u).href.split('#')[0].split('?')[0];
    const path = new URL(href).pathname;
    const isPost = /^\/products\/[^\/]+\/categories\/\d+\/posts\/\d+\/?$/.test(path);
    const mc = path.match(/^\/products\/[^\/]+\/categories\/(\d+)\/?$/);
    if (!isPost && !mc) return;
    if (mc && mc[1] === selfCid) return;
    if (seen.has(href)) return;
    seen.add(href);
    const tEl = a.querySelector('.syllabus__title, h3, h4, h5, .media-body p, p');
    const text = norm(tEl ? tEl.textContent : a.textContent);
    out.children.push({href, title: text.slice(0, 160), cls: a.className,
                       locked: !!a.querySelector('.fa-lock, [class*=lock]')});
  });
  out.pagination = [...d.querySelectorAll('.pag__link, .pagination a, a[rel=next]')]
    .map(a => new URL(a.getAttribute('href'), u).href).filter(h => !/[?&]page=1$/.test(h));
  return out;
}
""" + "; })()"

JS_LESSON = "(() => {" + JS_COMMON + " return " + r"""async (u) => {
  const {r, t, d} = await getDoc(u);
  const out = {status: r.status, final: r.url, len: t.length,
               challenge: /Just a moment|cf-challenge|challenge-platform/i.test(t.slice(0, 6000)),
               logged_in: !d.querySelector('input[type=password], form[action*="sign_in"], form[action$="/login"]')};
  const pcOld = d.querySelector('.post-content');
  const player = d.querySelector('#section-post_player');
  const pbody = d.querySelector('#section-post_body');
  const scopes = pcOld ? [pcOld] : [player, pbody].filter(Boolean);
  if (!scopes.length && d.querySelector('.post')) scopes.push(d.querySelector('.post'));
  out.theme = pcOld ? 'old' : (pbody ? 'new' : 'unknown');
  out.has_post_content = scopes.length > 0;
  const inScope = el => scopes.some(s => s.contains(el));
  const h1 = (scopes.length && scopes[0].querySelector('h1')) || (pbody && pbody.querySelector('h1')) || d.querySelector('h1');
  out.h1 = h1 ? norm(h1.textContent) : null;
  const html = scopes.map(s => s.outerHTML).join('\n');
  const ids = [];
  const add = id => { if (id && !ids.includes(id)) ids.push(id); };
  for (const m of html.matchAll(/wistia_async_([a-z0-9]{6,12})/g)) add(m[1]);
  for (const m of html.matchAll(/wistia\.(?:com|net)\/embed\/(?:iframe|medias)\/([a-z0-9]{6,12})/g)) add(m[1]);
  for (const m of html.matchAll(/data-wistia-id="([a-z0-9]{6,12})"/g)) add(m[1]);
  out.wistia = ids;
  const pageIds = [];
  for (const m of t.matchAll(/wistia_async_([a-z0-9]{6,12})/g)) if (!pageIds.includes(m[1])) pageIds.push(m[1]);
  out.wistia_page = pageIds;
  const other = [];
  scopes.forEach(sc => {
    sc.querySelectorAll('iframe').forEach(f => other.push('iframe:' + (f.getAttribute('src') || f.getAttribute('data-src') || '')));
    sc.querySelectorAll('video,audio').forEach(v => other.push(v.tagName.toLowerCase() + ':' + (v.getAttribute('src') || (v.querySelector('source') || {getAttribute: () => ''}).getAttribute('src') || '')));
    if (sc.querySelector('.kjb-video-responsive') && !ids.length) other.push('kjb-video-without-wistia-id');
  });
  for (const m of html.matchAll(/(?:youtube(?:-nocookie)?\.com\/embed\/|player\.vimeo\.com\/video\/)([A-Za-z0-9_-]+)/g)) other.push('embed:' + m[0]);
  for (const m of html.matchAll(/(?:youtu\.be\/|youtube\.com\/watch\?v=)([A-Za-z0-9_-]{11})/g)) other.push('ytlink:' + m[1]);
  out.other_media = [...new Set(other)];
  const atts = [];
  const seen = new Set();
  const FILE = /\.(pdf|docx?|xlsx?|pptx?|zip|csv|txt|png|jpe?g|gif|mp3|m4a|wav|mp4|mov|m4v|epub|key|numbers|pages)(\?|#|$)/i;
  d.querySelectorAll('a[href]').forEach(a => {
    const raw = a.getAttribute('href') || '';
    if (/\/logout|^#|^mailto:|^javascript:/i.test(raw)) return;
    const href = new URL(raw, u).href;
    const isDl = /\/downloads\//.test(href);
    if (!isDl && !(inScope(a) && FILE.test(href))) return;
    if (seen.has(href)) return;
    seen.add(href);
    atts.push({title: norm(a.textContent), url: href});
  });
  out.attachments = atts;
  const links = [];
  scopes.forEach(sc => sc.querySelectorAll('a[href]').forEach(a => {
    try { const x = new URL(a.getAttribute('href'), u); if (x.host !== new URL(u).host) links.push(x.host); } catch (e) {}
  }));
  out.link_hosts = [...new Set(links)];
  const comments = d.querySelector('#section-post_comments .muted');
  out.comments_label = comments ? norm(comments.textContent) : null;
  const textRoot = pcOld || (pbody && pbody.querySelector('.panel__block'));
  let text_chars = null, text_head = null;
  if (textRoot) {
    const c = textRoot.cloneNode(true);
    c.querySelectorAll('h1,h5.panel__sub-title,script,style,iframe,button,noscript,.kjb-video-responsive,.video,.mark-as-complete,.smart-next,.downloads,a[href*="/downloads/"]').forEach(e => e.remove());
    c.querySelectorAll('a,button').forEach(e => { if (/^(mark as complete|download video|completed)$/i.test(norm(e.textContent))) e.remove(); });
    const tx = norm(c.textContent);
    text_chars = tx.length; text_head = tx.slice(0, 80);
  }
  out.text_chars = text_chars; out.text_head = text_head;
  out.lock_hint = /locked|drip|will be available|not yet available|upgrade to access|purchase to access/i.test(norm(textRoot ? textRoot.textContent : '').slice(0, 2000));
  return out;
}
""" + "; })()"

JS_ANNOUNCE = "(() => {" + JS_COMMON + " return " + r"""async (u) => {
  const {r, t, d} = await getDoc(u);
  const out = {status: r.status, final: r.url, len: t.length};
  const wrap = d.querySelector('.content-wrap') || d.body;
  const c = wrap.cloneNode(true);
  c.querySelectorAll('.header, .modalbg, script, style, .footer').forEach(e => e.remove());
  out.text_chars = norm(c.textContent).length;
  out.text_head = norm(c.textContent).slice(0, 120);
  out.headings = [...c.querySelectorAll('h1,h2,h3,h4')].map(e => norm(e.textContent)).slice(0, 40);
  out.items = c.querySelectorAll('.announcement, .announcements .post, [class*=announcement]').length;
  return out;
}
""" + "; })()"

JS_LIBRARY = "(() => {" + JS_COMMON + " return " + r"""async (u) => {
  const {r, t, d} = await getDoc(u);
  const out = {status: r.status, final: r.url, products: []};
  d.querySelectorAll('a[href*="/products/"]').forEach(a => {
    const href = new URL(a.getAttribute('href'), u).href;
    const m = href.match(/\/products\/([^\/?#]+)\/?$/);
    if (!m) return;
    let e = a, title = null;
    for (let i = 0; i < 6 && e && !title; i++) {
      e = e.parentElement;
      const h = e && e.querySelector('h1,h2,h3,h4,h5,.title,.product-title,[class*=title]');
      if (h && norm(h.textContent)) title = norm(h.textContent);
    }
    out.products.push({slug: m[1], title});
  });
  out.hrefs = [...new Set([...d.querySelectorAll('a[href]')].map(a => a.getAttribute('href')))];
  return out;
}
""" + "; })()"

JS_PRODUCT_LINKS = "(() => {" + JS_COMMON + " return " + r"""async (u) => {
  const {r, t, d} = await getDoc(u);
  return {status: r.status,
          hrefs: [...new Set([...d.querySelectorAll('a[href]')].map(a => a.getAttribute('href')))],
          crumb_product: (d.querySelector('.breadcrumbs .crumb a') || {textContent: null}).textContent};
}
""" + "; })()"

JS_NAV = r"""() => {
  const norm = s => (s || '').replace(/[ \s]+/g, ' ').trim();
  const ids = [];
  document.querySelectorAll('[class*=wistia_async_]').forEach(e => {
    const m = e.className.match(/wistia_async_([a-z0-9]+)/); if (m && !ids.includes(m[1])) ids.push(m[1]);
  });
  const atts = [...new Set([...document.querySelectorAll('a[href*="/downloads/"]')].map(a => a.href + ' | ' + norm(a.textContent)))];
  const h1 = document.querySelector('.post-content h1') || document.querySelector('h1');
  return {url: location.href, wistia: ids, atts, h1: h1 ? norm(h1.textContent) : null,
          media: [...document.querySelectorAll('video,audio')].map(v => v.tagName)};
}"""

# ---------------------------------------------------------------- helpers


class Abort(Exception):
    pass


def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {"cats": {}, "lessons": {}, "wistia": {}, "extra": {}}


def save_cache(c):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)


def polite():
    time.sleep(random.uniform(1.0, 1.5))


def check_resp(info, url):
    bad = None
    if info.get("challenge"):
        bad = "Cloudflare challenge page"
    elif info["status"] in (401, 403, 429) or info["status"] >= 500:
        bad = f"HTTP {info['status']}"
    elif re.search(r"/(login|sign_in|users/sign_in)\b", info["final"]):
        bad = f"redirected to login ({info['final']})"
    elif "logged_in" in info and not info["logged_in"] and info["status"] == 200:
        bad = "no logout link in page (session lost?)"
    if bad:
        raise Abort(f"{bad} while fetching {url}")


def slugify(s, n=50):
    s = s.lower()
    s = re.sub(r"^\s*(module|week|lesson|part|session|day|step)?\s*\d+(\.\d+)*\s*[|:.\-–—)]\s*", "", s)
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > n:
        cut = s[:n]
        if "-" in cut[n // 2:]:
            cut = cut[: cut.rfind("-")]
        s = cut.strip("-")
    return s or "untitled"


def cat_id(url):
    m = re.search(r"/categories/(\d+)/?$", url)
    return int(m.group(1)) if m else None


def post_ids(url):
    m = re.search(r"/categories/(\d+)/posts/(\d+)", url)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


class Browser:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.connect_over_cdp(CDP)
        self.page = self.browser.contexts[0].new_page()
        self.page.goto(SITE + "/library", wait_until="domcontentloaded")
        self.n = 0

    def ev(self, js, arg):
        polite()
        self.n += 1
        return self.page.evaluate(js, arg)

    def close(self):
        try:
            self.page.close()
        finally:
            self._pw.stop()  # does not close the user's Chrome


# ---------------------------------------------------------------- crawl


def fetch_listing(br, cache, url):
    """Category/product listing with pagination folded in. Cached."""
    if url in cache["cats"]:
        return cache["cats"][url]
    info = br.ev(JS_LISTING, url)
    check_resp(info, url)
    pages = [url]
    queue = [p for p in info["pagination"] if p.split("#")[0] != url]
    seen = {url}
    while queue:
        p = queue.pop(0).split("#")[0]
        if p in seen or not re.search(r"[?&]page=\d+", p):
            continue
        seen.add(p)
        extra = br.ev(JS_LISTING, p)
        check_resp(extra, p)
        known = {c["href"] for c in info["children"]}
        info["children"] += [c for c in extra["children"] if c["href"] not in known]
        queue += extra["pagination"]
        pages.append(p)
    info["pages_fetched"] = pages
    cache["cats"][url] = info
    save_cache(cache)
    return info


def walk(br, cache, slug):
    """Return the tree: {'lessons': [post dicts], 'categories': [cat dicts]} under the product root."""
    root_url = f"{SITE}/products/{slug}"
    visited = set()

    def node_from(url, title_hint):
        info = fetch_listing(br, cache, url)
        cid = cat_id(url)
        node = {"id": cid, "url": url, "title": info["h1"] or title_hint, "lessons": [], "categories": [], "lessons_label": info.get("lessons_label"),
                "post_count_label": info.get("post_count_label"), "paged": len(info.get("pages_fetched", [])) > 1}
        for ch in info["children"]:
            if "/posts/" in ch["href"]:
                cid2, pid = post_ids(ch["href"])
                node["lessons"].append({"post_id": pid, "url": ch["href"], "list_title": ch["title"],
                                        "locked_listing": ch["locked"], "cls": ch["cls"]})
            elif cat_id(ch["href"]):
                c2 = cat_id(ch["href"])
                if c2 in visited:
                    print(f"  WARN: category {c2} seen twice, skipping duplicate", file=sys.stderr)
                    continue
                visited.add(c2)
                node["categories"].append(node_from(ch["href"], ch["title"]))
        return node

    root = fetch_listing(br, cache, root_url)
    tree = {"lessons": [], "categories": [], "lessons_label": root.get("lessons_label")}
    cids = []  # newer themes show a category's first posts plus "Show More" on the product page: walk by category id
    for ch in root["children"]:
        c_id = post_ids(ch["href"])[0] if "/posts/" in ch["href"] else cat_id(ch["href"])
        if c_id and c_id not in cids:
            cids.append(c_id)
    for c_id in cids:
        if c_id in visited:
            continue
        visited.add(c_id)
        tree["categories"].append(node_from(f"{SITE}/products/{slug}/categories/{c_id}", f"category {c_id}"))
    return tree


def iter_lessons(node):
    for l in node["lessons"]:
        yield l
    for c in node["categories"]:
        yield from iter_lessons(c)


def nav_verify(br, info, url):
    """No video in the fetched HTML: confirm with a real navigation (JS-rendered embeds)."""
    if info["wistia"] or "nav_check" in info:
        return False
    if [m for m in info["other_media"] if not m.startswith(("ytlink:", "embed:youtu.be"))]:
        return False
    polite()
    br.page.goto(url, wait_until="networkidle")
    br.page.wait_for_timeout(2500)
    nv = br.page.evaluate(JS_NAV)
    info["nav_check"] = nv
    if re.search(r"/(login|sign_in)", nv["url"]):
        raise Abort(f"navigation redirected to login: {nv['url']}")
    if nv["wistia"]:
        info["wistia"] = nv["wistia"]
        info["nav_found_video"] = True
    return True


def fetch_lessons(br, cache, tree, label):
    todo = [l for l in iter_lessons(tree) if l["url"] not in cache["lessons"]]
    total = sum(1 for _ in iter_lessons(tree))
    print(f"[{label}] lessons: {total} total, {len(todo)} to fetch", flush=True)
    for i, l in enumerate(todo, 1):
        info = br.ev(JS_LESSON, l["url"])
        check_resp(info, l["url"])
        nav_verify(br, info, l["url"])
        cache["lessons"][l["url"]] = info
        save_cache(cache)
        if i % 10 == 0 or i == len(todo):
            print(f"  [{label}] {i}/{len(todo)} fetched", flush=True)
    for l in iter_lessons(tree):
        info = cache["lessons"][l["url"]]
        if nav_verify(br, info, l["url"]):
            save_cache(cache)
            print(f"  [{label}] nav-checked no-video lesson: {info['h1']} -> wistia={info['wistia']}", flush=True)


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kajabi_map)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_wistia(cache, ids):
    todo = [i for i in ids if i not in cache["wistia"]]
    print(f"wistia: {len(ids)} ids, {len(todo)} to fetch", flush=True)
    for n, wid in enumerate(todo, 1):
        rec = {"error": None}
        try:
            m = http_json(f"https://fast.wistia.com/embed/medias/{wid}.json")["media"]
            rec["duration"] = m.get("duration")
            rec["name"] = m.get("name")
        except Exception as e:  # noqa: BLE001 - record and continue
            rec["error"] = f"media: {e}"
        time.sleep(0.3)
        try:
            c = http_json(f"https://fast.wistia.com/embed/captions/{wid}.json")
            caps = {}
            for cap in c.get("captions", []):
                lang = cap.get("wistiaLanguageCode") or cap.get("language") or cap.get("bcp47LanguageTag")
                lines = len((cap.get("hash") or {}).get("lines", []))
                caps[lang] = lines
            rec["captions"] = caps
        except urllib.error.HTTPError as e:
            rec["captions"] = {}
            if e.code != 404:
                rec["error"] = (rec["error"] or "") + f" captions: HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            rec["captions"] = {}
            rec["error"] = (rec["error"] or "") + f" captions: {e}"
        cache["wistia"][wid] = rec
        time.sleep(0.3)
        if n % 25 == 0:
            save_cache(cache)
            print(f"  wistia {n}/{len(todo)}", flush=True)
    save_cache(cache)


# ---------------------------------------------------------------- build


class Flow(dict):
    pass


class FlowList(list):
    pass


def _flow_dict(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


def _flow_list(dumper, data):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


yaml.add_representer(Flow, _flow_dict, Dumper=yaml.SafeDumper)
yaml.add_representer(FlowList, _flow_list, Dumper=yaml.SafeDumper)


def video_str(i):
    return f"wistia:{i}"


def build_lesson(cache, pcode, ccode, n, l):
    info = cache["lessons"][l["url"]]
    title = info["h1"] or l["list_title"]
    ids = info["wistia"]
    ytl = []
    other = []
    for m in info["other_media"]:
        mm = re.match(r"(?:ytlink:|embed:youtu\.be/|embed:youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})", m)
        if mm:
            if mm.group(1) not in ytl:
                ytl.append(mm.group(1))
        elif m in ("audio:", "video:"):
            continue  # element without a direct src (Kajabi audio/video player shell)
        elif not m.startswith("kjb-video"):
            other.append(m)
    vids = [video_str(i) for i in ids] + other
    w = [cache["wistia"].get(i, {}) for i in ids]
    dur = round(sum((x.get("duration") or 0) for x in w), 2)
    langs = []
    for x in w:
        for k in x.get("captions", {}):
            if k not in langs:
                langs.append(k)
    en_lines = sum(x.get("captions", {}).get("eng", 0) for x in w)
    lid = f"{pcode}-{ccode}-l{n:02d}"
    out = {"id": lid, "post_id": l["post_id"], "title": title, "url": l["url"]}
    if not vids:
        out["video"] = "none"
    elif len(vids) == 1:
        out["video"] = vids[0]
    else:
        out["video"] = vids
    out["duration_s"] = dur
    out["captions"] = FlowList(langs)
    out["caption_lines_en"] = en_lines
    tc = info["text_chars"] or 0
    head = info.get("text_head") or ""
    for lab in ("Download Video ", "Mark As Complete "):  # entries fetched before labels were stripped in JS
        if head.startswith(lab):
            tc -= len(lab)
            head = head[len(lab):]
    out["text_chars"] = max(tc, 0)
    atts = []
    vdl = False
    for a in info["attachments"]:
        if "amazonaws.com" in a["url"] and "X-Amz-Signature" in a["url"]:
            vdl = True  # Kajabi 'Download Video' (signed, expiring S3 URL): never stored, only flagged
            continue
        atts.append(a)
    out["attachments"] = [Flow(title=a["title"], url=a["url"]) for a in atts]
    if vdl:
        out["video_download"] = True
    audio = [a["url"] for a in atts if att_type(a["url"]) in ("mp3", "m4a", "wav")]
    if audio:
        out["audio_downloads"] = len(audio)
    if info.get("comments_label"):
        out["comments"] = int(re.sub(r"\D", "", info["comments_label"]) or 0)
    if ytl:
        out["youtube_links"] = FlowList(ytl)
    flags = []
    if l.get("locked_listing"):
        flags.append("locked-listing")
    if info.get("lock_hint"):
        flags.append("lock-text-hint")
    if len(ids) > 1:
        flags.append("multiple-videos")
    if any(m.startswith("kjb-video") for m in info["other_media"]):
        flags.append("kjb-video-no-wistia-id")
    if any(x.get("error") for x in w):
        flags.append("wistia-error")
    if flags:
        out["flags"] = FlowList(flags)
    return out, lid


def build_cat(cache, pcode, node, code, counters, atts_unique, lesson_index):
    counters["categories"] += 1
    ccode_slug = f"{code}-{slugify(node['title'])}"
    lessons = []
    for n, l in enumerate(node["lessons"], 1):
        les, lid = build_lesson(cache, pcode, code, n, l)
        les["raw_path"] = f"{BRAIN.name}/raw/{pcode}/{ccode_slug}/l{n:02d}-{slugify(les['title'])}.md"
        lessons.append(les)
        lesson_index.append(les)
        counters["lessons"] += 1
        counters["attachments"] += len(les["attachments"])
        for a in les["attachments"]:
            e = atts_unique.setdefault(a["url"], {"title": a["title"], "url": a["url"], "lessons": []})
            e["lessons"].append(lid)
        vs = les["video"] if isinstance(les["video"], list) else [les["video"]]
        for v in vs:
            if v != "none":
                counters["videos"] += 1
        ids = [v.split(":", 1)[1] for v in vs if v.startswith("wistia:")]
        for i in ids:
            if cache["wistia"].get(i, {}).get("captions", {}).get("eng"):
                counters["captioned_en"] += 1
        counters["duration_s"] += les["duration_s"]
    sub = []
    for k, c in enumerate(node["categories"], 1):
        sub.append(build_cat(cache, pcode, c, f"{code}-s{k:02d}", counters, atts_unique, lesson_index))
    d = {"id": node["id"], "code": code, "title": node["title"], "url": node["url"], "lessons": lessons}
    if node.get("paged"):
        d["paginated"] = True
    d["categories"] = sub
    return d


def build_outline(cache, trees, titles, only):
    products = []
    all_atts = {}
    all_lessons = []
    for code, slug, sid in PRODUCTS:
        if only and code not in only:
            continue
        if slug not in trees:
            continue
        tree = trees[slug]
        counters = {"categories": 0, "lessons": 0, "videos": 0, "captioned_en": 0, "duration_s": 0.0, "attachments": 0}
        atts_unique = {}
        lesson_index = []
        cats = []
        if tree["lessons"]:  # lessons directly on the product root
            root = {"id": None, "url": f"{SITE}/products/{slug}", "title": "(product root)",
                    "lessons": tree["lessons"], "categories": []}
            cats.append(build_cat(cache, code, root, "m00", counters, atts_unique, lesson_index))
        for k, c in enumerate(tree["categories"], 1):
            cats.append(build_cat(cache, code, c, f"m{k:02d}", counters, atts_unique, lesson_index))
        counters["duration_s"] = round(counters["duration_s"], 2)
        ann = cache["extra"].get("announcements", {}).get(slug)
        for u, e in atts_unique.items():
            all_atts.setdefault(u, {"title": e["title"], "url": u, "lessons": []})["lessons"] += e["lessons"]
        products.append({
            "code": code, "slug": slug, "title": titles.get(slug) or slug,
            "url": f"{SITE}/products/{slug}",
            "announcements_url": f"{SITE}/products/{slug}/announcements" if ann and ann.get("status") == 200 else None,
            "totals": Flow(**counters), "categories": cats,
        })
        all_lessons += lesson_index
    uniq = [{"title": e["title"], "url": e["url"], "type": att_type(e["url"]), "file": att_file(e["url"]),
             "lessons": FlowList(e["lessons"])} for e in all_atts.values()]
    return {"generated": GENERATED, "site": SITE, "products": products,
            "attachments_unique": uniq}


def att_file(url):
    m = re.search(r"/downloads/\d+/([^/?#]+)$", url)
    return m.group(1) if m else url.rsplit("/", 1)[-1]


def att_type(url):
    m = re.search(r"/downloads/\d+/[^/?#]*-([a-z0-9]{2,5})$", url)
    if m:
        return m.group(1)
    m = re.search(r"\.([a-z0-9]{2,5})(?:\?|#|$)", url)
    return m.group(1).lower() if m else "unknown"


def lesson_list_hash(product):
    """Refresh cursor for a course: hash of its lesson list (post id + video), see docs/updates.md."""
    import hashlib
    rows = sorted(f"{l['post_id']}:{l['video']}" for k in _walk(product["categories"]) for l in k["lessons"])
    return f"lessons:{len(rows)}:sha256:{hashlib.sha256(chr(10).join(rows).encode()).hexdigest()[:16]}"


def write_sources(outline, cache, overrides=None):
    """Refresh mapped fields; retain curated metadata, extra sources and refresh state."""
    data = brainlib.load_yaml(SOURCES, {"sources": []}) or {"sources": []}
    original = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    entries = data.setdefault("sources", [])
    old = {entry["id"]: entry for entry in entries}
    sid_for = {code: sid for code, _, sid in PRODUCTS}
    for product in outline["products"]:
        sid = sid_for[product["code"]]
        totals = product["totals"]
        entry = old.get(sid)
        if entry is None:
            entry = {"id": sid, "title": product["title"].removeprefix("(NEW) "),
                     "type": "course", "access": "login-browser", "platform": "kajabi",
                     "video_host": "wistia", "status": "mapped", "refresh": "monthly",
                     "last_crawled": None, "cursor": None}
            entries.append(entry)
        langs = sorted({lang for cat in _walk(product["categories"]) for lesson in cat["lessons"] for lang in lesson["captions"]})
        entry["url"] = product["url"]
        entry["captions"] = (f"{'+'.join(langs) or 'none'} ({totals['captioned_en']} of {totals['videos']} videos have English)"
                             if totals["videos"] else "none")
        counts = entry.setdefault("counts", {})
        counts.setdefault("modules", len(product["categories"]))
        counts.update(lessons=totals["lessons"], attachments=totals["attachments"])
        counts.setdefault("words", 0)
        updates = dict((overrides or {}).get(sid, {}))
        if "words" in updates:
            counts["words"] = updates.pop("words")
        entry.update(updates)
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    if rendered != original or not SOURCES.exists():
        brainlib.write_text(SOURCES, rendered)


def _walk(cats):
    for k in cats:
        yield k
        yield from _walk(k["categories"])


def write_outline(outline):
    OUTLINE.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(outline, Dumper=yaml.SafeDumper, sort_keys=False, allow_unicode=True, width=1000)
    newline = "\r\n" if OUTLINE.exists() and b"\r\n" in OUTLINE.read_bytes() else "\n"
    OUTLINE.write_text(text, encoding="utf-8", newline=newline)


# ---------------------------------------------------------------- validate


def validate(br, cache, n):
    import itertools
    lessons = [(u, i) for u, i in cache["lessons"].items() if i["wistia"] or i["attachments"]]
    # spread picks across the cache
    picks = lessons[:: max(1, len(lessons) // n)][:n]
    ok = True
    for u, fi in picks:
        br.page.goto(u, wait_until="networkidle")
        br.page.wait_for_timeout(2500)
        nv = br.page.evaluate(JS_NAV)
        strip = lambda x: re.sub(r"(amazonaws\.com/[^?| ]*)\?[^ |]*", lambda m: m.group(1), x)  # signed S3 URLs differ per request
        fa = sorted(strip(a["url"] + " | " + a["title"]) for a in fi["attachments"])
        na = sorted(strip(x) for x in nv["atts"])
        same_w = nv["wistia"] == fi["wistia"]
        same_a = fa == na
        print(f"{u}\n  wistia fetch={fi['wistia']} nav={nv['wistia']} same={same_w}\n"
              f"  attachments fetch={len(fa)} nav={len(na)} same={same_a}\n  h1 same={nv['h1'] == fi['h1']}")
        ok &= same_w and same_a
        time.sleep(random.uniform(1.0, 1.5))
    print("VALIDATION", "OK" if ok else "MISMATCH")


# ---------------------------------------------------------------- main


def community_hits(hrefs):
    pat = re.compile(r"communit|circle\.so|skool\.com|mighty|discord|facebook\.com/groups|slack", re.I)
    return sorted({h for h in hrefs if pat.search(h)})


def mark_crawled():
    """After a crawl: set status, last_crawled, cursor and transcript word counts in sources.yaml."""
    outline = yaml.safe_load(OUTLINE.read_text(encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sid_for = {code: sid for code, _, sid in PRODUCTS}
    overrides = {}
    for p in outline["products"]:
        lessons = [l for k in _walk(p["categories"]) for l in k["lessons"]]
        missing = [l["id"] for l in lessons if not brain_path(BRAIN, l["raw_path"]).exists()]
        if missing:
            print(f"{p['code']}: {len(missing)} lessons have no raw file yet; not marking crawled")
            continue
        words = sum(len(re.sub(r"^---.*?---", "", brain_path(BRAIN, l["raw_path"]).read_text(encoding="utf-8"), count=1, flags=re.S).split())
                    for l in lessons)
        overrides[sid_for[p["code"]]] = {"status": "crawled", "last_crawled": now,
                                         "cursor": lesson_list_hash(p), "words": words}
        print(f"{p['code']}: crawled, {words:,} words, cursor {lesson_list_hash(p)}")
    write_sources(outline, None, overrides)


def main():
    global BRAIN, CACHE, OUTLINE, SOURCES, SITE, CDP, PRODUCTS, GENERATED
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--port", type=int)
    ap.add_argument("--site")
    ap.add_argument("--only", help="comma list of product codes")
    ap.add_argument("--validate", type=int, metavar="N")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--limit-products", type=int)
    ap.add_argument("--mark-crawled", action="store_true",
                    help="after a crawl: advance cursor/last_crawled and word counts in sources.yaml")
    a = ap.parse_args()
    BRAIN, config = configure(a)
    SITE = site(config, a.site)
    CDP = cdp(config, a.port) if not (a.build_only or a.mark_crawled) else None
    PRODUCTS = [(p["code"], p["slug"], p["source_id"]) for p in config.get("products", [])]
    if not PRODUCTS:
        ap.error("set products in crawl.yaml")
    CACHE, OUTLINE, SOURCES = map_cache(BRAIN), BRAIN / "outline.yaml", BRAIN / "sources.yaml"
    # Rebuilding a cache keeps its recorded date; a live crawl stamps today.
    GENERATED = (brainlib.load_yaml(OUTLINE, {}) or {}).get("generated", datetime.date.today().isoformat()) if a.build_only else datetime.date.today().isoformat()
    if a.mark_crawled:
        return mark_crawled()
    only = set(a.only.split(",")) if a.only else None
    if a.build_only and not CACHE.exists():
        sys.exit(f"missing map cache: {CACHE}")
    cache = load_cache()
    t0 = time.time()
    prods = [p for p in PRODUCTS if not only or p[0] in only]
    trees = {}
    br = None
    try:
        if not a.build_only:
            br = Browser()
            if a.validate:
                validate(br, cache, a.validate)
                return
            if "library" not in cache["extra"]:
                lib = br.ev(JS_LIBRARY, SITE + "/library")
                check_resp({**lib, "logged_in": True, "challenge": False}, "library")
                cache["extra"]["library"] = lib
                save_cache(cache)
            lib = cache["extra"]["library"]
            lib_slugs = {p["slug"] for p in lib["products"]}
            missing = [p[1] for p in PRODUCTS if p[1] not in lib_slugs]
            print("library products:", sorted(lib_slugs), "| missing from library:", missing, flush=True)
        for code, slug, sid in prods:
            if a.build_only:
                # rebuild tree from cache only
                br_stub = None
            tree = None
            if not a.build_only:
                tree = walk(br, cache, slug)
                fetch_lessons(br, cache, tree, code)
                # announcements + product-level links (community check)
                ex = cache["extra"].setdefault("announcements", {})
                if slug not in ex:
                    info = br.ev(JS_ANNOUNCE, f"{SITE}/products/{slug}/announcements")
                    ex[slug] = info
                pl = cache["extra"].setdefault("product_links", {})
                if slug not in pl:
                    pl[slug] = br.ev(JS_PRODUCT_LINKS, f"{SITE}/products/{slug}")
                save_cache(cache)
                cache["extra"].setdefault("trees", {})[slug] = tree
                save_cache(cache)
            trees[slug] = cache["extra"]["trees"][slug]
        ids = []
        for slug in trees:
            for l in iter_lessons({"lessons": trees[slug]["lessons"], "categories": trees[slug]["categories"]}):
                for w in cache["lessons"].get(l["url"], {}).get("wistia", []):
                    if w not in ids:
                        ids.append(w)
        if not a.build_only:
            fetch_wistia(cache, ids)
    except Abort as e:
        save_cache(cache)
        print(f"ABORT: {e}\nCache saved; rerun to resume after the user fixes the session.", file=sys.stderr)
        sys.exit(2)
    finally:
        if br:
            br.close()
    lib = cache["extra"].get("library", {"products": []})
    titles = {}
    for p in lib["products"]:
        if p["title"] and p["slug"] not in titles:
            titles[p["slug"]] = p["title"]
    outline = build_outline(cache, trees, titles, only)
    write_outline(outline)
    write_sources(outline, cache)
    print(f"wrote {OUTLINE}; elapsed {time.time() - t0:.0f}s; kajabi requests this run: {br.n if br else 0}")


if __name__ == "__main__":
    main()
