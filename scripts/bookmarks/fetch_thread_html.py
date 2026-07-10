#!/usr/bin/env python3
"""fetch_thread_html.py — Bir X tweet/thread/article linkinden TAM icerigi tek HTML sayfasi olarak indirir.

URL/ID -> TweetDetail cek -> (X Article body DraftJS + thread devami + medya) -> self-contained .html
build_html.py'nin render_page + article render'ini + thread_util'i yeniden kullanir.
--embed (varsayilan) gorselleri base64 gomer -> tek dosya, offline acilir. --no-embed remote link birakir.

Kullanim:
  uv run --no-project python fetch_thread_html.py <url|id> [--out DIR] [--no-embed]
"""
from __future__ import annotations
import sys, os, re, json, base64, argparse, subprocess, html, urllib.request
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import build_html as B
from thread_util import reconstruct_thread, thread_to_html

def parse_id(s: str) -> str | None:
    m = re.search(r"status/(\d+)", s or "")
    if m: return m.group(1)
    return s if re.fullmatch(r"\d+", (s or "").strip()) else None

def fetch_raw(tid: str) -> dict:
    r = subprocess.run(["node", os.path.join(ROOT, "x_tweetdetail.mjs"), tid],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.stderr.write(r.stderr)
        raise RuntimeError(f"TweetDetail cekilemedi (exit {r.returncode})")
    return json.loads(r.stdout)

def focal_meta(raw: dict, tid: str) -> dict | None:
    """Fokal tweet'in meta'sini render_page'in bekledigi sozluk seklinde cikarir."""
    holder = {}
    def walk(o):
        if isinstance(o, dict):
            tr = o.get("tweet_results")
            if isinstance(tr, dict):
                res = tr.get("result")
                if isinstance(res, dict):
                    r = res.get("tweet") if res.get("__typename") == "TweetWithVisibilityResults" else res
                    if isinstance(r, dict) and r.get("rest_id") == tid:
                        holder["r"] = r
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(raw)
    r = holder.get("r")
    if not r: return None
    lg = r.get("legacy", {}) or {}
    core = (r.get("core") or {}).get("user_results", {}).get("result", {})
    uname = ((core.get("core") or {}).get("screen_name")
             or (core.get("legacy") or {}).get("screen_name") or "")
    name = ((core.get("core") or {}).get("name")
            or (core.get("legacy") or {}).get("name") or "")
    nt = (((r.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {})
    content = html.unescape(nt.get("text") or lg.get("full_text", ""))
    urls = (lg.get("entities") or {}).get("urls") or []
    for u in urls:  # t.co -> gercek link (content + link listesi icin)
        if u.get("url") and u.get("expanded_url"):
            content = content.replace(u["url"], u["expanded_url"])
    links = [u["expanded_url"] for u in urls if u.get("expanded_url")]
    media = []
    mlist = ((lg.get("extended_entities") or {}).get("media")
             or (lg.get("entities") or {}).get("media") or [])
    for m in mlist:
        if m.get("type") in ("video", "animated_gif"):
            variants = [v for v in (m.get("video_info") or {}).get("variants", [])
                        if v.get("content_type") == "video/mp4" and v.get("url")]
            if variants:
                media.append(max(variants, key=lambda v: v.get("bitrate", 0))["url"])
        elif m.get("media_url_https"):
            media.append(m["media_url_https"])
    return {
        "username": uname, "name": name, "date": lg.get("created_at", ""),
        "url": f"https://x.com/{uname}/status/{tid}",
        "metrics": f"❤️{lg.get('favorite_count',0)} / 🔁{lg.get('retweet_count',0)} / 💬{lg.get('reply_count',0)}",
        "content": content.strip(), "links": links, "media": media,
    }

_IMG_SRC = re.compile(r'<img([^>]*?)src="(https://pbs\.twimg\.com/[^"]+)"')

def embed_images(page: str) -> tuple[str, int]:
    """HTML icindeki remote pbs gorsellerini base64 data-URI'ye cevir (self-contained)."""
    cache = {}
    n = [0]
    def repl(m):
        url = m.group(2)
        if url not in cache:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                    ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                cache[url] = f"data:{ct};base64,{base64.b64encode(raw).decode()}"
                n[0] += 1
            except Exception as e:
                sys.stderr.write(f"[embed] atlandi {url}: {e}\n")
                cache[url] = url
        return f'<img{m.group(1)}src="{cache[url]}"'
    return _IMG_SRC.sub(repl, page), n[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--out", default=".")
    ap.add_argument("--no-embed", action="store_true", help="gorselleri gomme, remote link birak")
    args = ap.parse_args()

    tid = parse_id(args.target)
    if not tid: sys.exit(f"Gecersiz hedef: {args.target}")
    outdir = os.path.expanduser(args.out); os.makedirs(outdir, exist_ok=True)

    print(f"[html] TweetDetail cekiliyor: {tid}", file=sys.stderr)
    raw = fetch_raw(tid)
    meta = focal_meta(raw, tid)
    if not meta: sys.exit("Fokal tweet bulunamadi (silinmis/erisilemez?).")

    article_html, art_title = B.article_from_draftjs_data(raw)
    th = reconstruct_thread(raw, tid)
    thread_html = thread_to_html(th) if (th and th["is_thread"]) else ""

    display = (art_title.strip() if art_title else "") or " ".join(
        re.sub(r"https?://\S+", "", meta["content"]).split()[:10]) or f"@{meta['username']}"
    page = B.render_page(meta, display, article_html, thread_html)

    embedded = 0
    if not args.no_embed:
        page, embedded = embed_images(page)

    slug = B.slugify(display) or tid
    path = os.path.join(outdir, f"{slug}.html")
    open(path, "w", encoding="utf-8").write(page)

    kind = "ARTICLE" if article_html else ("THREAD" if thread_html else "tweet")
    print(f"[html] {kind} · @{meta['username']} · gomulu gorsel={embedded} · {len(page)} bytes", file=sys.stderr)
    print(path)

if __name__ == "__main__":
    main()
