#!/usr/bin/env python3
"""build_html.py — Bookmark .md dosyalarini descriptor-adli .html'e cevirir.

Ne yapar (idempotent):
  1. Her <kategori>/<tweet_id>.md dosyasini okur (yoksa <kategori>/_md_backup/<id>.md).
  2. Dosya adi = anlamli descriptor:
       - Article ise  -> article basligi (DraftJS/md title)
       - Degilse       -> HIBRIT: metin >= ~40 anlamli karakterse ilk kelimelerden slug,
                          yoksa Qwen (LM Studio) ile 4-8 kelimelik descriptor
  3. Icerigi TEK bir self-display HTML sayfasina render eder:
       - baslik + yazar + tarih + metrik + orijinal link
       - tweet metni (linkler tiklanir)
       - article govdesi -> x_articles_raw/<id>.json DraftJS'ten (bold/italik/link/gorsel korunur),
         yoksa md'deki "## Article Icerigi" bolumu
       - MEDYA GALERISI: <img> / <video controls> — relative src="_media/<id>/...", inline
  4. Eski .md -> <kategori>/_md_backup/<id>.md (tasinir).
  5. _filemap.csv (tweet_id,kategori,eski_md,yeni_html,descriptor_kaynagi) + _descriptor_cache.json.

Kullanim:
  uv run --no-project --with httpx python build_html.py            # tum 724
  uv run --no-project --with httpx python build_html.py --limit 5  # ilk 5 (test)
  uv run --no-project --with httpx python build_html.py --only claude-optimization
  BUILD_NO_MOVE=1 ...   # .md tasima (test icin)
"""
from __future__ import annotations
import os, re, sys, json, csv, glob, html, shutil, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
ART_RAW = os.path.join(ROOT, "x_articles_raw")
CACHE_PATH = os.path.join(ROOT, "_descriptor_cache.json")
FILEMAP_PATH = os.path.join(ROOT, "_filemap.csv")
THREADS_DIR = os.path.join(ROOT, "x_threads_raw")  # build_threads.py ciktisi (Faz 2)
LLM_URL = os.environ.get("LLM_URL", "http://localhost:1234/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive")

sys.path.insert(0, ROOT)
from thread_util import thread_to_html  # bookmark thread'i icin '## Thread' bolumu

def load_thread_html(tid: str) -> str:
    """x_threads_raw/<tid>.json varsa thread'in devamini (fokal HARIÇ) HTML'e cevir."""
    p = os.path.join(THREADS_DIR, tid + ".json")
    if not os.path.exists(p):
        return ""
    try:
        th = json.load(open(p, encoding="utf-8"))
    except Exception:
        return ""
    return thread_to_html(th)

VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# md dosyasindaki bilinen Turkce bolum basliklari (article govdesi kendi ## basliklarini
# icerebilir, o yuzden yalniz bu ANCHOR'lara gore boluyoruz)
KNOWN_SECTIONS = ["## Icerik", "## İçerik", "## Linkler", "## Medya",
                  "## Article Icerigi", "## Article İçeriği"]

# ---------------------------------------------------------------- slug
_TR = str.maketrans({
    "ç": "c", "Ç": "c", "ş": "s", "Ş": "s", "ı": "i", "İ": "i",
    "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ö": "o", "Ö": "o",
    "â": "a", "î": "i", "û": "u", "é": "e", "è": "e", "ñ": "n",
})

def slugify(text: str, maxlen: int = 70) -> str:
    text = (text or "").translate(_TR).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if len(text) > maxlen:
        text = text[:maxlen].rsplit("-", 1)[0] or text[:maxlen]
    return text.strip("-")

# ---------------------------------------------------------------- md parse
def parse_md(text: str) -> dict:
    lines = text.splitlines()
    meta = {"username": "", "name": "", "date": "", "url": "", "metrics": "",
            "content": "", "links": [], "media": [], "article_md": ""}
    # header: "# @username — Name"
    for ln in lines[:6]:
        m = re.match(r"^#\s+@(\S+)\s+[—-]\s+(.*)$", ln)
        if m:
            meta["username"], meta["name"] = m.group(1), m.group(2).strip()
            break
        m = re.match(r"^#\s+@(\S+)\s*$", ln)
        if m:
            meta["username"] = m.group(1); break
    for ln in lines[:10]:
        if ln.startswith("**Tarih:**"):   meta["date"] = ln.split("**", 2)[-1].strip()
        elif ln.startswith("**URL:**"):    meta["url"] = ln.replace("**URL:**", "").strip()
        elif ln.startswith("**Metrikler:**"): meta["metrics"] = ln.replace("**Metrikler:**", "").strip()

    # bolumleri bilinen anchor'lara gore ayir. Turkce-normalize + TAM eslesme
    # (article govdesi kendi "## ..." basliklarini icerir; substring/loose match onlari
    #  yanlislikla bolum sanardi). "article icerigi" gorulunce dur — sonrasi hep article.
    SECTION_KEYS = {"icerik": "content", "linkler": "links",
                    "medya": "media", "article icerigi": "article"}
    idxs = []  # (line_index, kind)
    for i, ln in enumerate(lines):
        st = ln.strip()
        if not st.startswith("##"):
            continue
        key = re.sub(r"\s+", " ", st.lstrip("#").strip().translate(_TR).lower())
        kind = SECTION_KEYS.get(key)
        if kind:
            idxs.append((i, kind))
            if kind == "article":
                break
    for j, (i, kind) in enumerate(idxs):
        end = idxs[j + 1][0] if j + 1 < len(idxs) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        if kind == "content":
            meta["content"] = body
        elif kind == "article":
            meta["article_md"] = body
        elif kind == "links":
            meta["links"] = [re.sub(r"^-\s*", "", x).strip()
                             for x in body.splitlines() if x.strip()]
        elif kind == "media":
            for x in body.splitlines():
                m = re.search(r"\((_media/[^)]+)\)", x)
                if m:
                    meta["media"].append(m.group(1).strip())
    return meta

# ---------------------------------------------------------------- DraftJS -> html
def _u16_slice(text: str, off: int, length: int) -> str:
    """DraftJS offset'leri UTF-16 code-unit; emoji kaymasini onlemek icin utf-16'dan kes."""
    b = text.encode("utf-16-le")
    return b[off * 2:(off + length) * 2].decode("utf-16-le", "replace")

def _u16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2

def render_inline(text: str, style_ranges, entity_ranges, ent_map: dict) -> str:
    if not text:
        return ""
    if not style_ranges and not entity_ranges:
        return html.escape(text)
    n = _u16_len(text)
    bounds = {0, n}
    for r in (style_ranges or []):
        bounds.add(r["offset"]); bounds.add(r["offset"] + r["length"])
    for r in (entity_ranges or []):
        bounds.add(r["offset"]); bounds.add(r["offset"] + r["length"])
    bounds = sorted(b for b in bounds if 0 <= b <= n)
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        seg = html.escape(_u16_slice(text, a, b - a))
        styles = {r["style"].lower() for r in (style_ranges or [])
                  if r["offset"] <= a and r["offset"] + r["length"] >= b}
        link = None
        for r in (entity_ranges or []):
            if r["offset"] <= a and r["offset"] + r["length"] >= b:
                ent = ent_map.get(str(r["key"]))
                if ent and ent.get("type") == "LINK":
                    link = ent.get("data", {}).get("url")
        if "bold" in styles:   seg = f"<strong>{seg}</strong>"
        if "italic" in styles: seg = f"<em>{seg}</em>"
        if link:               seg = f'<a href="{html.escape(link)}" target="_blank" rel="noopener">{seg}</a>'
        out.append(seg)
    return "".join(out)

def article_from_draftjs(tweet_id: str) -> tuple[str | None, str]:
    """(html_body, title) doner; article yoksa (None, '')."""
    path = os.path.join(ART_RAW, tweet_id + ".json")
    if not os.path.exists(path):
        return None, ""
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None, ""
    # rekursif: content_state + article title + media_entities
    cs = []; titles = []; media_ents = []
    def walk(o):
        if isinstance(o, dict):
            if "content_state" in o and isinstance(o["content_state"], dict):
                cs.append(o["content_state"])
            if o.get("title") and isinstance(o["title"], str):
                titles.append(o["title"])
            if "media_entities" in o and isinstance(o["media_entities"], list):
                media_ents.extend(o["media_entities"])
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)
    if not cs:
        return None, (titles[0] if titles else "")
    state = cs[0]
    blocks = state.get("blocks", [])
    ent_map = {}
    for e in (state.get("entityMap") or []):
        if isinstance(e, dict) and "key" in e:
            ent_map[str(e["key"])] = e.get("value", {})
    media_url = {}
    for me in media_ents:
        mid = str(me.get("media_id", ""))
        url = (me.get("media_info") or {}).get("original_img_url")
        if mid and url:
            media_url[mid] = url

    title = titles[0] if titles else ""
    out = []
    list_open = None  # 'ul' | 'ol'
    def close_list():
        nonlocal list_open
        if list_open:
            out.append(f"</{list_open}>"); list_open = None
    for b in blocks:
        btype = b.get("type", "unstyled")
        inner = render_inline(b.get("text", ""), b.get("inlineStyleRanges"),
                              b.get("entityRanges"), ent_map)
        if btype in ("unordered-list-item", "ordered-list-item"):
            want = "ul" if btype.startswith("unordered") else "ol"
            if list_open != want:
                close_list(); out.append(f"<{want}>"); list_open = want
            out.append(f"<li>{inner}</li>")
            continue
        close_list()
        if btype == "unstyled":
            if inner.strip(): out.append(f"<p>{inner}</p>")
        elif btype == "header-one":   out.append(f"<h2>{inner}</h2>")
        elif btype == "header-two":   out.append(f"<h3>{inner}</h3>")
        elif btype == "header-three": out.append(f"<h4>{inner}</h4>")
        elif btype == "blockquote":   out.append(f"<blockquote>{inner}</blockquote>")
        elif btype == "code-block":   out.append(f"<pre><code>{inner}</code></pre>")
        elif btype == "atomic":
            img = None
            for r in (b.get("entityRanges") or []):
                ent = ent_map.get(str(r["key"]))
                if not ent: continue
                if ent.get("type") == "MEDIA":
                    for mi in ent.get("data", {}).get("mediaItems", []):
                        url = media_url.get(str(mi.get("mediaId", "")))
                        if url: img = url
                elif ent.get("type") == "DIVIDER":
                    out.append("<hr>")
            if img:
                out.append(f'<figure class="art-img"><img loading="lazy" '
                           f'src="{html.escape(img)}" alt=""></figure>')
        else:
            if inner.strip(): out.append(f"<p>{inner}</p>")
    close_list()
    return "\n".join(out), title

def article_from_md(article_md: str) -> tuple[str | None, str]:
    """md'deki '## Article Icerigi' fallback: '### title' + govde -> basit html."""
    if not article_md.strip():
        return None, ""
    lines = article_md.splitlines()
    title = ""
    body = []
    for ln in lines:
        s = ln.strip()
        if not title and s.startswith("### "):
            title = s[4:].strip(); continue
        body.append(ln)
    html_body = md_block_to_html("\n".join(body))
    return html_body, title

# ---------------------------------------------------------------- basit md -> html (icerik + md-article fallback)
_URL_RE = re.compile(r"(https?://[^\s<>()]+)")

def linkify(escaped: str) -> str:
    return _URL_RE.sub(lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>', escaped)

def md_block_to_html(text: str) -> str:
    out, list_open = [], None
    def close():
        nonlocal list_open
        if list_open: out.append(f"</{list_open}>"); list_open = None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            close(); continue
        esc = linkify(html.escape(s))
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close(); lvl = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{linkify(html.escape(m.group(2)))}</h{lvl}>"); continue
        if s.startswith(("> ", ">")):
            close(); out.append(f"<blockquote>{linkify(html.escape(s.lstrip('> ')))}</blockquote>"); continue
        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            if list_open != "ol": close(); out.append("<ol>"); list_open = "ol"
            out.append(f"<li>{linkify(html.escape(m.group(2)))}</li>"); continue
        if s.startswith(("- ", "* ")):
            if list_open != "ul": close(); out.append("<ul>"); list_open = "ul"
            out.append(f"<li>{linkify(html.escape(s[2:]))}</li>"); continue
        close(); out.append(f"<p>{esc}</p>")
    close()
    return "\n".join(out)

# ---------------------------------------------------------------- descriptor (hibrit)
STOP = {"the","a","an","and","or","of","to","in","on","for","is","are","with",
        "bir","bu","ve","ile","da","de","icin","için","cok","çok"}

def clean_text_for_desc(content: str) -> str:
    t = re.sub(r"https?://\S+", " ", content)
    t = re.sub(r"@\w+", " ", t)
    t = re.sub(r"#(\w+)", r"\1", t)
    t = re.sub(r"[\r\n]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def heuristic_descriptor(content: str):
    """(slug, display) doner; metin yetersizse None."""
    t = clean_text_for_desc(content)
    if len(t) < 40:  # anlamli metin uzunlugu yeterli mi?
        return None
    words = t.split()[:10]
    display = " ".join(words).strip(" -–—:·|")
    slug = slugify(display)
    if len(slug) < 12:
        return None
    return slug, display

# Metinsiz bookmark'lar icin: cozulmus (t.co olmayan) link path'inden descriptor.
# Lokal LLM (Qwen "aggressive") descriptor icin kullanilamiyor — surekli reasoning yapip
# bos content donduruyor. Link path'i link-only tweet'lerde zaten iyi descriptor verir.
_NOISE_DOM = {"github", "twitter", "x", "youtube", "youtu", "medium", "substack"}
_NOISE_PATH = {"blob", "tree", "main", "master", "status", "watch", "index",
               "home", "en", "docs", "www", "p", "s", "dp", "article", "articles"}

def link_descriptor(links: list):
    """(slug, display) doner; uygun link yoksa None."""
    for u in links:
        if any(x in u for x in ("t.co/", "/photo/", "/video/")):
            continue
        m = re.match(r"https?://(?:www\.)?([^/?#]+)(/[^?#]*)?", u)
        if not m:
            continue
        domain = m.group(1)
        dom_word = domain.split(".")[-2] if domain.count(".") >= 1 else domain
        raw_parts = [p for p in (m.group(2) or "").strip("/").split("/") if p]
        parts = [p for p in raw_parts if p.lower() not in _NOISE_PATH]
        cand = []
        if dom_word.lower() not in _NOISE_DOM:
            cand.append(dom_word)
        cand += parts[:3]
        slug = slugify(" ".join(cand))
        if slug and len(slug) >= 4:
            display = slug.replace("-", " ")
            return slug, display
    return None

# ---------------------------------------------------------------- HTML sayfa
PAGE_CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:#fafaf9;color:#1c1917;
 font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:32px 20px 96px}
header.bm{border-bottom:1px solid #e7e5e4;padding-bottom:16px;margin-bottom:24px}
h1.title{font-size:1.7rem;line-height:1.25;margin:0 0 12px}
.byline{color:#57534e;font-size:.95rem}
.byline a{color:#57534e}
.meta{color:#78716c;font-size:.85rem;margin-top:6px}
.meta .metrics{margin-left:2px}
a{color:#0369a1;text-decoration:none}
a:hover{text-decoration:underline}
.content{white-space:pre-wrap;font-size:1.05rem;margin:0 0 8px}
section.article{margin-top:28px;border-top:1px solid #e7e5e4;padding-top:8px}
section.article h2{font-size:1.35rem;margin:1.4em 0 .5em}
section.article h3{font-size:1.15rem;margin:1.2em 0 .4em}
section.article p{margin:0 0 1em}
section.article blockquote{margin:1em 0;padding:.2em 1em;border-left:3px solid #d6d3d1;color:#44403c}
section.article ul,section.article ol{padding-left:1.4em}
section.article li{margin:.25em 0}
section.article pre{background:#f5f5f4;padding:12px;border-radius:8px;overflow:auto}
figure.art-img{margin:1.2em 0}
figure.art-img img{max-width:100%;border-radius:8px}
.links{margin:20px 0 0;padding:0;list-style:none;font-size:.9rem}
.links li{margin:.2em 0;word-break:break-all}
.media{margin-top:28px;display:grid;grid-template-columns:1fr;gap:14px}
.media img,.media video{width:100%;max-width:100%;border-radius:10px;display:block;background:#000}
.sec-label{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:#a8a29e;margin:28px 0 8px}
section.thread{margin-top:28px;border-top:1px solid #e7e5e4;padding-top:8px}
.thread-tweet{display:flex;gap:12px;padding:14px 0;border-bottom:1px solid #f0efed}
.thread-tweet:last-child{border-bottom:none}
.thread-n{flex:0 0 auto;font-size:.75rem;color:#a8a29e;font-variant-numeric:tabular-nums;padding-top:3px}
.thread-body{white-space:pre-wrap;min-width:0;word-wrap:break-word}
@media (prefers-color-scheme:dark){
 body{background:#0c0a09;color:#e7e5e4}
 header.bm,section.article,section.thread{border-color:#292524}
 .byline,.byline a{color:#a8a29e}.meta{color:#78716c}
 section.article blockquote{border-color:#44403c;color:#d6d3d1}
 section.article pre{background:#1c1917}
 .thread-tweet{border-color:#1c1917}
 .sec-label{color:#57534e}
}
"""

def render_page(meta: dict, descriptor: str, article_html: str | None, thread_html: str = "") -> str:
    uname = meta["username"]
    name = meta["name"] or uname
    url = meta["url"]
    title = html.escape(descriptor)
    byline = ""
    if uname:
        prof = f"https://x.com/{html.escape(uname)}"
        byline = (f'<div class="byline"><a href="{prof}" target="_blank" rel="noopener">'
                  f'@{html.escape(uname)}</a>' + (f' — {html.escape(name)}' if meta["name"] else "") + '</div>')
    metaline = []
    if meta["date"]: metaline.append(html.escape(meta["date"]))
    if meta["metrics"]: metaline.append(f'<span class="metrics">{html.escape(meta["metrics"])}</span>')
    if url: metaline.append(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">X\'te aç ↗</a>')
    metahtml = f'<div class="meta">{" · ".join(metaline)}</div>' if metaline else ""

    content_html = ""
    if meta["content"].strip():
        content_html = f'<div class="content">{linkify(html.escape(meta["content"].strip()))}</div>'

    # linkler (t.co ve tweet'in kendi foto/video permalink'leri disinda cozulmus linkler)
    links_html = ""
    extra = [l for l in meta["links"]
             if l and not any(x in l for x in ("t.co/", "/photo/", "/video/"))]
    if extra:
        items = "".join(f'<li><a href="{html.escape(l)}" target="_blank" rel="noopener">{html.escape(l)}</a></li>'
                        for l in extra)
        links_html = f'<div class="sec-label">Bağlantılar</div><ul class="links">{items}</ul>'

    article_sec = ""
    if article_html and article_html.strip():
        article_sec = f'<section class="article">{article_html}</section>'

    thread_sec = ""
    if thread_html and thread_html.strip():
        thread_sec = (f'<div class="sec-label">Thread (devamı)</div>'
                      f'<section class="thread">{thread_html}</section>')

    media_html = ""
    if meta["media"]:
        cells = []
        for m in meta["media"]:
            ext = os.path.splitext(m)[1].lower()
            src = html.escape(m)
            if ext in VIDEO_EXT:
                cells.append(f'<video controls preload="metadata" src="{src}"></video>')
            else:
                cells.append(f'<img loading="lazy" src="{src}" alt="">')
        media_html = ('<div class="sec-label">Medya</div><div class="media">'
                      + "\n".join(cells) + "</div>")

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="bm">
<h1 class="title">{title}</h1>
{byline}
{metahtml}
</header>
{content_html}
{links_html}
{article_sec}
{media_html}
{thread_sec}
</div>
</body>
</html>
"""

# ---------------------------------------------------------------- pipeline
def find_sources(only: str | None):
    """[(category, tweet_id, md_path)] — top-level ve _md_backup birlesik, dedupe."""
    seen = {}
    cats = [only] if only else [d for d in os.listdir(ROOT)
                                 if os.path.isdir(os.path.join(ROOT, d))
                                 and not d.startswith((".", "_"))
                                 and d not in ("raw", "logs", "x_articles_raw")]
    for cat in cats:
        cdir = os.path.join(ROOT, cat)
        if not os.path.isdir(cdir):
            continue
        for md in glob.glob(os.path.join(cdir, "*.md")):
            tid = os.path.splitext(os.path.basename(md))[0]
            seen.setdefault((cat, tid), md)
        for md in glob.glob(os.path.join(cdir, "_md_backup", "*.md")):
            tid = os.path.splitext(os.path.basename(md))[0]
            seen.setdefault((cat, tid), md)  # top-level oncelikli (once eklendi)
    return [(c, t, p) for (c, t), p in seen.items()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("WORKERS", "6")))
    args = ap.parse_args()
    no_move = os.environ.get("BUILD_NO_MOVE") == "1"

    cache = {}
    if os.path.exists(CACHE_PATH):
        try: cache = json.load(open(CACHE_PATH, encoding="utf-8"))
        except Exception: cache = {}

    sources = sorted(find_sources(args.only), key=lambda x: (x[0], x[1]))
    if args.limit:
        sources = sources[:args.limit]
    print(f"[build] {len(sources)} bookmark islenecek (workers={args.workers}, no_move={no_move})")

    # 1) parse + descriptor (paralel). Not: lokal LLM descriptor icin kullanilamadi
    #    (surekli reasoning, bos content) — link/author heuristigine gecildi. Ag bagimliligi yok.
    prepared = []  # (cat, tid, md_path, meta, article_html, desc_text, desc_src, src_count)
    lock_counts = {"title": 0, "heuristic": 0, "link": 0, "author": 0, "cache": 0}

    def prep(item):
        cat, tid, md_path = item
        text = open(md_path, encoding="utf-8").read()
        meta = parse_md(text)
        # article govdesi: once DraftJS, sonra md fallback
        art_html, art_title = article_from_draftjs(tid)
        if art_html is None:
            art_html, art_title = article_from_md(meta["article_md"])
        # descriptor: slug (dosya adi) + display (H1'de gorunen insan-okunur baslik)
        if tid in cache:
            c = cache[tid]
            desc_text = c["slug"]; desc_display = c.get("display") or c["slug"]
            desc_src, src_count = c["src"], "cache"
        elif art_title.strip():
            desc_text, desc_display = slugify(art_title), art_title.strip()
            desc_src = src_count = "title"
        else:
            h = heuristic_descriptor(meta["content"])
            l = None if h else link_descriptor(meta["links"])
            if h:
                (desc_text, desc_display), desc_src, src_count = h, "heuristic", "heuristic"
            elif l:
                (desc_text, desc_display), desc_src, src_count = l, "link", "link"
            else:
                uname = meta["username"] or "post"
                kind = "medya" if meta["media"] else "gonderi"
                desc_text = slugify(f"{uname}-{kind}") or tid
                desc_display = f"@{uname} {'medya' if meta['media'] else 'gonderisi'}"
                desc_src = src_count = "author"
        if not desc_text:
            desc_text = tid
        if not desc_display:
            desc_display = desc_text
        return (cat, tid, md_path, meta, art_html, desc_text, desc_display, desc_src, src_count)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(prep, it): it for it in sources}
        done = 0
        for fu in as_completed(futs):
            r = fu.result()
            prepared.append(r)
            lock_counts[r[8]] = lock_counts.get(r[8], 0) + 1
            done += 1
            if done % 50 == 0:
                print(f"  descriptor: {done}/{len(sources)}")

    # 2) descriptor cache guncelle
    for (cat, tid, _md, _meta, _art, desc_text, desc_display, desc_src, _sc) in prepared:
        cache[tid] = {"slug": desc_text, "display": desc_display, "src": desc_src}
    json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    # 3) collision cozumu (deterministik: kategori+tid sirali)
    prepared.sort(key=lambda x: (x[0], x[1]))
    used = {}   # (cat, name) -> tid
    final_name = {}  # tid -> filename
    for (cat, tid, _md, _meta, _art, desc_text, _disp, _src, _sc) in prepared:
        base = desc_text or tid
        name = base
        if used.get((cat, name)) not in (None, tid):
            name = f"{base}-{tid[-6:]}"
        n2 = name; k = 1
        while used.get((cat, n2)) not in (None, tid):
            n2 = f"{name}-{k}"; k += 1
        used[(cat, n2)] = tid
        final_name[tid] = n2 + ".html"

    # 4) yaz + .md tasi + filemap
    rows = []
    written = 0
    for (cat, tid, md_path, meta, art_html, desc_text, desc_display, desc_src, _sc) in prepared:
        fname = final_name[tid]
        out_path = os.path.join(ROOT, cat, fname)
        page = render_page(meta, desc_display, art_html, load_thread_html(tid))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(page)
        written += 1
        # .md'yi _md_backup'a tasi (yalniz top-level'daysa)
        if not no_move and os.path.dirname(md_path) == os.path.join(ROOT, cat):
            bdir = os.path.join(ROOT, cat, "_md_backup")
            os.makedirs(bdir, exist_ok=True)
            shutil.move(md_path, os.path.join(bdir, os.path.basename(md_path)))
        rows.append([tid, cat, f"{tid}.md", fname, desc_src])

    rows.sort(key=lambda r: (r[1], r[3]))
    with open(FILEMAP_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tweet_id", "kategori", "eski_md", "yeni_html", "descriptor_kaynagi"])
        w.writerows(rows)

    print(f"[build] {written} HTML yazildi -> {FILEMAP_PATH}")
    print(f"[build] descriptor kaynaklari: {lock_counts}")

if __name__ == "__main__":
    main()
