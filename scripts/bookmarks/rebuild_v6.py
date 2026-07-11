#!/usr/bin/env python3
"""rebuild_v6.py — Bookmark koleksiyonunu sifirdan, icerik-tam ve yeniden-kategorize kurar.

Kaynaklar (kategori-bagimsiz, id-anahtarli):
  - raw/bookmarks_<latest>.json      : guncel bookmark seti (meta + metin)
  - x_articles_raw/ , x_threads_rawjson/ : her bookmark'in TweetDetail JSON'u
                                           (article govdesi + thread + resolved link + medya)
  - _media/<id>/                     : indirilmis tweet medyasi (kok — kategori-bagimsiz)

Ne yapar:
  1. Her bookmark icin meta (yazar/tarih/metrik/metin/link) TweetDetail'den (yoksa raw'dan).
  2. Tweet medyasi: yerel _media/<id>/ (yoksa syndication API ile indirir).
  3. Article govdesi: build_html.article_from_draftjs_data (GORSEL + VIDEO + MARKDOWN/kod bloklari).
  4. Thread devami: thread_util (fokal haric).
  5. YENIDEN KATEGORIZE: zengin icerik (tweet + article + thread + link domain + yazar) uzerine
     regex kurallari. LLM YOK (lokal Qwen descriptor/kategori icin bos donuyor).
  6. Dosya adi: <YYYY-MM-DD>_<descriptor>.html  (tweet'in TARIHI basta).
  7. <kategori>/<ad>.html yazar; medya '../_media/<id>/...' referansi (kategori degisse de calisir).

Kullanim:
  uv run --no-project --with httpx python rebuild_v6.py           # tam
  uv run --no-project --with httpx python rebuild_v6.py --limit 5 --no-clean   # test
"""
from __future__ import annotations
import os, sys, re, json, glob, csv, argparse
from datetime import datetime
from collections import Counter
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import httpx
import build_html as B
from thread_util import reconstruct_thread, thread_to_html
from fetch_thread_html import focal_meta
from process_fast import CATEGORIES

MEDIA_ROOT = os.path.join(ROOT, "_media")
RAW_DIRS = [os.path.join(ROOT, "x_articles_raw"), os.path.join(ROOT, "x_threads_rawjson")]
SYNDICATION = "https://cdn.syndication.twimg.com/tweet-result"
MEDIA_EXT = B.VIDEO_EXT | B.IMG_EXT

def latest_raw():
    return sorted(glob.glob(os.path.join(ROOT, "raw", "bookmarks_*.json")))[-1]

def load_td(tid):
    for d in RAW_DIRS:
        p = os.path.join(d, tid + ".json")
        if os.path.exists(p):
            try: return json.load(open(p, encoding="utf-8"))
            except Exception: return None
    return None

def tweet_date(created):
    for fmt in ("%a %b %d %H:%M:%S %z %Y",):
        try: return datetime.strptime(created, fmt).strftime("%Y-%m-%d")
        except Exception: pass
    # ISO fallback (bird raw createdAt)
    try: return datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception: return "0000-00-00"

def local_media(tid):
    d = os.path.join(MEDIA_ROOT, tid)
    if not os.path.isdir(d): return []
    return [f"../_media/{tid}/{f}" for f in sorted(os.listdir(d))
            if os.path.splitext(f)[1].lower() in MEDIA_EXT]

def _dl(url, dest, client):
    if os.path.exists(dest) and os.path.getsize(dest) > 0: return
    try:
        with client.stream("GET", url, timeout=60, follow_redirects=True) as r:
            if r.status_code != 200: return
            with open(dest, "wb") as f:
                for ch in r.iter_bytes(65536): f.write(ch)
    except Exception:
        if os.path.exists(dest):
            try: os.remove(dest)
            except OSError: pass

def download_media_for(tid, client):
    dest = os.path.join(MEDIA_ROOT, tid)
    if os.path.isdir(dest) and os.listdir(dest): return  # zaten var
    try:
        r = client.get(SYNDICATION, params={"id": tid, "token": "x"}, timeout=15)
        if r.status_code != 200: return
        meta = r.json()
    except Exception: return
    if not (meta.get("mediaDetails")): return
    os.makedirs(dest, exist_ok=True)
    for m in meta["mediaDetails"]:
        if m.get("type") == "photo" and m.get("media_url_https"):
            u = m["media_url_https"]; _dl(u, os.path.join(dest, u.split("/")[-1].split("?")[0]), client)
        else:
            vs = [v for v in ((m.get("video_info") or {}).get("variants") or [])
                  if v.get("content_type") == "video/mp4" and v.get("url")]
            if vs:
                best = max(vs, key=lambda v: v.get("bitrate", 0))
                _dl(best["url"], os.path.join(dest, best["url"].split("/")[-1].split("?")[0]), client)

def categorize(rich_text):
    for cat, pat in CATEGORIES.items():
        if re.search(pat, rich_text, re.I): return cat
    return None

def strip_tags(h): return re.sub(r"<[^>]+>", " ", h or "")

def build_one(bm, client):
    tid = bm["id"]
    td = load_td(tid)
    meta = (focal_meta(td, tid) if td else None) or {}
    au = bm.get("author", {}) or {}
    meta.setdefault("username", au.get("username", "") or "")
    meta.setdefault("name", au.get("name", "") or "")
    if not meta.get("content"): meta["content"] = bm.get("text", "") or ""
    meta.setdefault("links", [])
    meta["url"] = f"https://x.com/{meta.get('username','')}/status/{tid}"
    if not meta.get("date"): meta["date"] = bm.get("createdAt", "") or ""
    if not meta.get("metrics"):
        meta["metrics"] = f"❤️{bm.get('likeCount',0)} / 🔁{bm.get('retweetCount',0)} / 💬{bm.get('replyCount',0)}"
    download_media_for(tid, client)
    meta["media"] = local_media(tid)
    art_html, art_title = (B.article_from_draftjs_data(td) if td else (None, ""))
    th = reconstruct_thread(td, tid) if td else None
    thread_html = thread_to_html(th) if (th and th["is_thread"]) else ""
    date = tweet_date(meta.get("date", ""))
    # descriptor (build_html ile ayni hibrit mantik)
    if art_title.strip():
        slug, display = B.slugify(art_title), art_title.strip()
    else:
        h = B.heuristic_descriptor(meta["content"])
        l = None if h else B.link_descriptor(meta["links"])
        if h: slug, display = h
        elif l: slug, display = l
        else:
            slug = B.slugify(f"{meta['username']}-{'medya' if meta['media'] else 'gonderi'}") or tid
            display = f"@{meta['username']} {'medya' if meta['media'] else 'gonderisi'}"
    # kategori (zengin)
    thread_txt = " ".join(t["text"] for t in th["tweets"]) if th else ""
    domains = " ".join(re.findall(r"https?://(?:www\.)?([^/]+)", " ".join(meta["links"])))
    rich = f"{meta['content']} {strip_tags(art_html)[:4000]} {thread_txt[:2500]} {domains} author:{meta['username']}"
    cat = categorize(rich)
    if not cat:
        cat = "links-only" if (not meta["content"].strip() and not art_html and not thread_html) else "misc"
    return (tid, cat, date, slug, display, meta, art_html, thread_html)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-clean", action="store_true")
    args = ap.parse_args()

    bms = json.load(open(latest_raw(), encoding="utf-8"))
    if args.limit: bms = bms[:args.limit]
    print(f"[rebuild] kaynak: {os.path.basename(latest_raw())} · {len(bms)} bookmark")

    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"})
    prepared = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(build_one, bm, client): bm for bm in bms}
        done = 0
        for fu in as_completed(futs):
            bm = futs[fu]
            try:
                prepared.append(fu.result())
            except Exception as e:
                sys.stderr.write(f"[hata] {bm.get('id')}: {e}\n")
            done += 1
            if done % 100 == 0: print(f"  {done}/{len(bms)}")

    if not args.no_clean:
        for f in glob.glob(os.path.join(ROOT, "*", "*.html")):
            os.remove(f)

    used = {}; rows = []; catcount = Counter()
    prepared.sort(key=lambda x: (x[1], x[2], x[0]))
    for (tid, cat, date, slug, display, meta, art_html, thread_html) in prepared:
        base = f"{date}_{slug or tid}"
        name = base
        if used.get((cat, name)) not in (None, tid): name = f"{base}-{tid[-6:]}"
        n2 = name; k = 1
        while used.get((cat, n2)) not in (None, tid): n2 = f"{name}-{k}"; k += 1
        used[(cat, n2)] = tid
        fname = n2 + ".html"
        cdir = os.path.join(ROOT, cat); os.makedirs(cdir, exist_ok=True)
        page = B.render_page(meta, display, art_html, thread_html)
        open(os.path.join(cdir, fname), "w", encoding="utf-8").write(page)
        catcount[cat] += 1
        rows.append([tid, cat, date, fname])

    with open(os.path.join(ROOT, "_filemap.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["tweet_id", "kategori", "tarih", "html"])
        w.writerows(sorted(rows, key=lambda r: (r[1], r[3])))
    print(f"[rebuild] {sum(catcount.values())} HTML yazildi. kategori dagilimi:")
    for c, n in catcount.most_common(): print(f"  {n:4d}  {c}")

if __name__ == "__main__":
    main()
