"""Fetch lesson page text and deduplicated attachments into media/.

Only one browser-driving process per session. --dry-run reports work without connecting."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, brain_path, cdp, site

import argparse
import hashlib
import json
import pathlib
import random
import re
import shutil
import time

import yaml
from playwright.sync_api import sync_playwright

# Old themes use .post-content; new themes use #section-post_body.
JS_PAGE = r"""async (u) => {
  const r = await fetch(u, {credentials: 'include'});
  const html = await r.text();
  const d = new DOMParser().parseFromString(html, 'text/html');
  const meta = {status: r.status, url: r.url, title: d.title, challenge: /Just a moment|cf-chl|challenge-platform/i.test(html.slice(0, 20000)),
                login: !!d.querySelector('form[action*="login"], form[action*="sign_in"], input[type=password]')};
  let roots = [], theme = null;
  const old = d.querySelector('.post-content');
  const nw = d.querySelector('#section-post_body');
  if (old) { roots = [old]; theme = 'old'; }
  else if (nw) { roots = [...nw.querySelectorAll('.panel__block')]; theme = 'new'; }
  if (!theme) return {...meta, md: null, theme, blocks: 0};
  const DROP = 'h1,h5.panel__sub-title,script,style,iframe,button,noscript,video,audio,form,.btn,.kjb-video-responsive,.video,' +
    '.mark-as-complete,.smart-next,.downloads,a[href*="/downloads/"],#section-post_comments,.comments,[id*="comment"],[class*="comment"]';
  const norm = s => s.replace(/[ \s]+/g, ' ');
  const walk = (n) => {
    if (n.nodeType === 3) return norm(n.textContent);
    if (n.nodeType !== 1) return '';
    const tag = n.tagName.toLowerCase();
    const inner = [...n.childNodes].map(walk).join('');
    if (/^(mark as complete|download video|completed)$/i.test(inner.trim())) return '';
    if (/^h[2-6]$/.test(tag)) return `\n\n### ${inner.trim()}\n\n`;
    if (tag === 'li') return `\n- ${inner.trim()}`;
    if (tag === 'br') return '\n';
    if (tag === 'a') { const h = n.getAttribute('href') || ''; return h && !h.startsWith('#') && inner.trim() ? `[${inner.trim()}](${new URL(h, u).href})` : inner; }
    if (tag === 'strong' || tag === 'b') return inner.trim() ? `**${inner.trim()}** ` : '';
    if (/^(p|div|ul|ol|section|blockquote)$/.test(tag)) return `\n\n${inner}\n\n`;
    return inner;
  };
  const parts = roots.map(root => {
    const c = root.cloneNode(true);
    c.querySelectorAll(DROP).forEach(e => e.remove());
    return walk(c);
  });
  const md = parts.join('\n\n').split('\n').map(l => l.trim()).join('\n').replace(/\n{3,}/g, '\n\n').trim();
  return {...meta, md, theme, blocks: roots.length};
}"""


class StopCrawl(Exception):
    pass


def lessons_in_order() -> list:
    o = yaml.safe_load((BRAIN / "outline.yaml").read_text(encoding="utf-8"))
    out = []

    def walk(cats):
        for c in cats or []:
            out.extend(c.get("lessons") or [])
            walk(c.get("categories"))

    for p in o["products"]:
        walk(p["categories"])
    return out


def lessons_by_id() -> dict:
    return {l["id"]: l for l in lessons_in_order()}


def filename_for(url: str) -> str:
    # .../courses/downloads/3839138/foundations_workbook-pdf -> foundations_workbook.pdf
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"-(pdf|png|jpe?g|mp3|docx?|xlsx?|zip|txt|csv)$", r".\1", slug)


def download_id_for(url: str) -> str:
    return url.rstrip("/").rsplit("/", 2)[-2]


def bylink_path(url: str) -> pathlib.Path:
    return BYLINK / f"{download_id_for(url)}__{filename_for(url)}"


def polite() -> None:
    time.sleep(random.uniform(1.0, 1.5))


def fetch_page(page, lid: str, url: str) -> dict:
    res = page.evaluate(JS_PAGE, url)
    polite()
    if res["status"] in (403, 429) or res["challenge"]:
        raise StopCrawl(f"{lid}: HTTP {res['status']} / challenge={res['challenge']} ({res['title']!r}); stopping")
    if res["status"] != 200 or res["login"] or re.search(r"/(login|sign_in)", res["url"]):
        raise StopCrawl(f"{lid}: page fetch failed (HTTP {res['status']}, url {res['url']}, login={res['login']}); stopping")
    if res["md"] is None:
        raise StopCrawl(f"{lid}: no text root found (neither .post-content nor #section-post_body); stopping")
    return res


SIGS = {".pdf": b"%PDF", ".png": b"\x89PNG"}


def download(ctx, ua: str, lid: str, a: dict, dest: pathlib.Path) -> bool:
    """Returns True if downloaded; False on a soft failure. Raises StopCrawl on login/403/429."""
    r = ctx.request.get(a["url"], max_redirects=0, headers={"User-Agent": ua})
    polite()
    loc = r.headers.get("location")
    if r.status in (403, 429):
        raise StopCrawl(f"{lid}: download {a['url']} returned HTTP {r.status}; stopping")
    if r.status in (301, 302, 303, 307):
        if re.search(r"/(login|sign_in)", loc or ""):
            raise StopCrawl(f"{lid}: download redirected to login ({loc}); stopping")
        f = ctx.request.get(loc)  # signed S3 URL; no delay needed
    else:
        f = r
    ctype = f.headers.get("content-type", "")
    if f.status != 200 or ctype.startswith("text/html"):
        print(f"  ! {a['title']}: HTTP {r.status}/{f.status} {ctype}")
        return False
    body = f.body()
    sig = SIGS.get(dest.suffix.lower())
    if not body or (sig and not body.startswith(sig)):
        print(f"  ! {dest.name}: bad body ({len(body)} B, starts {body[:8]!r})")
        return False
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    print(f"  + {dest.name} {len(body):,} B {ctype}")
    return True


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(lessons: list) -> bool:
    """Hash every by-link file, dedupe, write manifest.json, verify, delete by-link/. Returns True on success."""
    links = []  # (lesson_id, attachment, path)
    missing = []
    for l in lessons:
        for a in l.get("attachments") or []:
            p = bylink_path(a["url"])
            if p.exists():
                links.append((l["id"], a, p))
            else:
                missing.append((l["id"], a["url"]))
    if missing:
        print(f"manifest: {len(missing)} link(s) not downloaded, not building: {missing[:5]}")
        return False

    groups: dict = {}  # sha -> {filename, size, links}
    first_path: dict = {}
    for lid, a, p in links:
        sha = sha256_of(p)
        first_path.setdefault(sha, p)
        g = groups.setdefault(sha, {"sha256": sha, "size": p.stat().st_size, "filename": filename_for(a["url"]), "links": []})
        g["links"].append({"url": a["url"], "lesson_id": lid, "title": a["title"]})

    # Canonical names. The plain name goes to the group matching an existing canonical file, else the group with most links.
    # If an existing canonical file matches no group it is left alone and every group gets a __sha8 name.
    by_name: dict = {}
    for g in groups.values():
        by_name.setdefault(g["filename"], []).append(g)
    for name, gs in by_name.items():
        existing = ATT / name
        existing_sha = sha256_of(existing) if existing.exists() else None
        orphan = bool(existing_sha) and existing_sha not in {g["sha256"] for g in gs}
        if orphan:
            print(f"manifest: WARNING existing {name} (sha {existing_sha[:8]}) matches no downloaded link; not overwriting")
        gs.sort(key=lambda g: (g["sha256"] != existing_sha, -len(g["links"]), g["sha256"]))
        stem, dot, ext = name.rpartition(".")
        for i, g in enumerate(gs):
            g["canonical_name"] = name if (i == 0 and not orphan) else f"{stem}__{g['sha256'][:8]}{dot}{ext}"
        if len(gs) > 1:
            print(f"manifest: same filename, different hashes: {name} -> " +
                  ", ".join(f"{g['canonical_name']} ({g['sha256'][:8]}, {len(g['links'])} links)" for g in gs))

    manifest = []
    for g in sorted(groups.values(), key=lambda g: (g["filename"], g["canonical_name"])):
        dest = ATT / g["canonical_name"]
        if not dest.exists():
            shutil.copyfile(first_path[g["sha256"]], dest)
        manifest.append({"sha256": g["sha256"], "size": g["size"], "filename": g["filename"],
                         "canonical": dest.relative_to(BRAIN).as_posix(), "links": g["links"]})
    (ATT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    # Verify from disk.
    m = json.loads((ATT / "manifest.json").read_text(encoding="utf-8"))
    n_links = sum(len(e["links"]) for e in m)
    expected = sum(len(l.get("attachments") or []) for l in lessons)
    problems = []
    if n_links != expected:
        problems.append(f"link count {n_links} != {expected}")
    for e in m:
        c = brain_path(BRAIN, e["canonical"])
        if not c.exists() or c.stat().st_size != e["size"] or sha256_of(c) != e["sha256"]:
            problems.append(f"canonical mismatch: {e['canonical']}")
    if problems:
        print("manifest: VERIFY FAILED, keeping by-link/:", problems)
        return False
    shutil.rmtree(BYLINK)
    print(f"manifest: {len(m)} distinct files, {n_links} links, verified; by-link/ deleted")
    return True


def main() -> None:
    global BRAIN, MEDIA, ATT, BYLINK
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--port", type=int)
    ap.add_argument("--site")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="every lesson in outline order; skips pages that already exist")
    ap.add_argument("--no-attachments", action="store_true")
    ap.add_argument("--manifest", action="store_true", help="build the manifest after an explicit-id run (always done with --all)")
    args = ap.parse_args()
    BRAIN, config = configure(args)
    MEDIA = BRAIN / "media"
    ATT, BYLINK = MEDIA / "attachments", MEDIA / "attachments" / "by-link"
    if not args.ids and not args.all:
        ap.error("give lesson ids or --all")
    ordered = lessons_in_order()
    by_id = {l["id"]: l for l in ordered}
    if args.all:
        todo = ordered
    else:
        unknown = [i for i in args.ids if i not in by_id]
        if unknown:
            sys.exit(f"unknown lesson ids: {unknown}")
        todo = [by_id[i] for i in args.ids]
    if args.dry_run:
        pages = sum(not (MEDIA / "pages" / f"{lesson['id']}.md").exists() or not args.all for lesson in todo)
        print(f"{len(todo)} lessons, {pages} pages to fetch; dry run (no browser)")
        return
    endpoint, base = cdp(config, args.port), site(config, args.site)
    (MEDIA / "pages").mkdir(parents=True, exist_ok=True)
    if not args.no_attachments:
        BYLINK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    fails = []
    consecutive = 0
    ok = False

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.goto(base + "/library", wait_until="domcontentloaded")
            ua = page.evaluate("navigator.userAgent")
            polite()
            for n, l in enumerate(todo, 1):
                lid = l["id"]
                pf = MEDIA / "pages" / f"{lid}.md"
                if args.all and pf.exists():
                    print(f"[{n}/{len(todo)}] {lid}: page have")
                else:
                    res = fetch_page(page, lid, l["url"])
                    pf.write_text((res["md"] + "\n") if res["md"] else "", encoding="utf-8", newline="\n")
                    note = f"{len(res['md'])} chars, theme={res['theme']}, blocks={res['blocks']}"
                    if not res["md"]:
                        note += "  ** EMPTY **"
                        with (MEDIA / "pages_empty.txt").open("a", encoding="utf-8", newline="\n") as fh:
                            fh.write(lid + "\n")
                    if "�" in res["md"]:
                        note += "  ** contains U+FFFD **"
                    print(f"[{n}/{len(todo)}] {lid}: page text {note}", flush=True)
                if args.no_attachments:
                    continue
                for a in l.get("attachments") or []:
                    dest = bylink_path(a["url"])
                    if dest.exists():
                        print(f"  = {dest.name} (have)")
                        continue
                    # Kajabi answers with a 302 to a signed S3 URL; in-page fetch can't follow it (CORS),
                    # so use the context's request API, which shares the session cookies.
                    try:
                        good = download(ctx, ua, lid, a, dest)
                    except StopCrawl:
                        raise
                    except Exception as e:  # noqa: BLE001
                        print(f"  ! {a['title']}: {e!r}")
                        good = False
                    if good:
                        consecutive = 0
                    else:
                        fails.append((lid, a["url"]))
                        consecutive += 1
                        if consecutive >= 3:
                            raise StopCrawl(f"3 consecutive download failures, last at {lid}; stopping")
            ok = True
        except StopCrawl as e:
            print(f"STOP: {e}")
        finally:
            page.close()

    print(f"elapsed {time.time() - t0:.0f}s; download failures: {fails or 'none'}")
    if not ok:
        sys.exit(1)
    if (args.all or args.manifest) and not args.no_attachments and not fails:
        if not build_manifest(ordered):
            sys.exit(2)


if __name__ == "__main__":
    main()
