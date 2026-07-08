"""1) syndication API'den medya URL'leri → indir
2) links-only'yi resolved URL'e göre reclassify.
"""

import concurrent.futures as cf
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).parent
RAW_BOOKMARKS = ROOT / "raw" / "bookmarks_20260708.json"
SYNDICATION = "https://cdn.syndication.twimg.com/tweet-result"


def fetch_media_meta(tweet_id: str, client: httpx.Client) -> dict | None:
    try:
        r = client.get(SYNDICATION, params={"id": tweet_id, "token": "x"}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def download_media(url: str, dest: Path, client: httpx.Client) -> bool:
    try:
        if dest.exists() and dest.stat().st_size > 0:
            return True
        with client.stream("GET", url, timeout=60, follow_redirects=True) as r:
            if r.status_code != 200:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(65536):
                    fh.write(chunk)
        return True
    except Exception:
        return False


def find_md_for_id(tweet_id: str) -> Path | None:
    for md in ROOT.glob(f"*/{tweet_id}.md"):
        return md
    return None


def process_media(bm: dict) -> tuple[str, int, int]:
    tid = bm["id"]
    md = find_md_for_id(tid)
    if md is None:
        return tid, 0, 0
    cat_dir = md.parent
    media_dir = cat_dir / "_media" / tid
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}) as c:
        meta = fetch_media_meta(tid, c)
        if not meta:
            return tid, 0, 0
        n_p = n_v = 0
        urls = []
        for m in (meta.get("mediaDetails") or []):
            mtype = m.get("type", "photo")
            if mtype == "photo":
                u = m.get("media_url_https")
                if u:
                    name = Path(urlparse(u).path).name
                    if download_media(u, media_dir / name, c):
                        n_p += 1
                        urls.append(f"_media/{tid}/{name}")
            elif mtype in ("video", "animated_gif"):
                variants = ((m.get("video_info") or {}).get("variants") or [])
                mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4s:
                    best = max(mp4s, key=lambda v: v.get("bitrate", 0))
                    u = best["url"].split("?")[0]
                    name = Path(urlparse(u).path).name
                    if download_media(best["url"], media_dir / name, c):
                        n_v += 1
                        urls.append(f"_media/{tid}/{name}")
        if urls:
            existing = md.read_text(encoding="utf-8", errors="replace")
            if "## Medya" not in existing:
                add = ["", "## Medya", ""] + [f"- ![]({u})" for u in urls]
                md.write_text(existing.rstrip() + "\n" + "\n".join(add) + "\n", encoding="utf-8")
    return tid, n_p, n_v


DOMAIN_RULES = {
    "engineering-devtools": [r"^github\.com/", r"^gitlab\.com/", r"^gist\.github\.com/",
                              r"^rust-lang\.org", r"^golang\.org", r"^python\.org",
                              r"^docker\.com", r"^kubernetes\.io", r"^stackoverflow\.com"],
    "ai-research": [r"^arxiv\.org/", r"^papers\.ssrn\.com", r"^openreview\.net",
                     r"^proceedings\.neurips\.cc", r"^huggingface\.co/papers"],
    "ai-generic": [r"^openai\.com", r"^anthropic\.com", r"^ai\.googleblog\.com",
                    r"^ai\.google\.dev", r"^gemini\.google\.com", r"^chatgpt\.com",
                    r"^cursor\.com", r"^windsurf\.com"],
    "local-models": [r"^huggingface\.co/(?!papers)", r"^ollama\.com", r"^lmstudio\.ai",
                      r"^mistral\.ai", r"^together\.ai"],
    "claude-optimization": [r"^claude\.com", r"^claude\.ai", r"^docs\.anthropic\.com",
                             r"^console\.anthropic\.com"],
    "cybersecurity": [r"^hackingarticles\.in", r"^specterops\.io", r"^krebsonsecurity",
                       r"^security\.google\.com", r"^nvd\.nist\.gov"],
    "crypto-onchain": [r"^glassnode\.com", r"^checkonchain\.com", r"^cryptoquant\.com"],
    "crypto-market": [r"^coingecko\.com", r"^coinmarketcap\.com", r"^binance\.com",
                       r"^coinbase\.com", r"^kraken\.com", r"^hyperliquid\.xyz"],
    "trading-quant": [r"^quantconnect\.com", r"^tradingview\.com"],
    "product-startup": [r"^ycombinator\.com", r"^news\.ycombinator\.com",
                          r"^producthunt\.com", r"^indiehackers\.com"],
    "turkish-content": [r"^finped\.com", r"^bloomberght\.com", r"^bigpara\.hurriyet\.com\.tr",
                          r"^ekonomim\.com", r"^dunya\.com"],
}


def get_first_link(md_path: Path) -> str | None:
    txt = md_path.read_text(encoding="utf-8", errors="replace")
    in_links = False
    for line in txt.splitlines():
        if line.strip() == "## Linkler":
            in_links = True
            continue
        if in_links and line.startswith("- "):
            url = line[2:].strip()
            if "t.co" not in url and url.startswith("http"):
                return url
    return None


def classify_by_domain(url: str) -> str | None:
    p = urlparse(url)
    hostpath = (p.netloc + p.path).lstrip("www.")
    for cat, rules in DOMAIN_RULES.items():
        for r in rules:
            if re.match(r, hostpath, re.IGNORECASE):
                return cat
    return None


def reclassify_links_only() -> dict[str, int]:
    stats: dict[str, int] = {}
    src = ROOT / "links-only"
    if not src.exists():
        return stats
    for md in list(src.glob("*.md")):
        url = get_first_link(md)
        if not url:
            continue
        new_cat = classify_by_domain(url)
        if not new_cat or new_cat == "links-only":
            continue
        dest = ROOT / new_cat
        dest.mkdir(exist_ok=True)
        shutil.move(str(md), str(dest / md.name))
        tid = md.stem
        m_src = src / "_media" / tid
        m_dst = dest / "_media" / tid
        if m_src.exists():
            m_dst.parent.mkdir(exist_ok=True)
            shutil.move(str(m_src), str(m_dst))
        stats[new_cat] = stats.get(new_cat, 0) + 1
    return stats


def main():
    bookmarks = json.loads(RAW_BOOKMARKS.read_text())
    limit = int(os.environ.get("LIMIT", "0")) or len(bookmarks)
    workers = int(os.environ.get("WORKERS", "10"))
    print(f"=== FAZ 1: Medya çekimi ({limit} tweet, {workers} worker) ===")
    start = time.time()
    total_p = total_v = with_m = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_media, bm): bm["id"] for bm in bookmarks[:limit]}
        done = 0
        for f in cf.as_completed(futures):
            try:
                _tid, p, v = f.result()
                total_p += p
                total_v += v
                if p or v:
                    with_m += 1
            except Exception as e:
                print(f"  hata: {str(e)[:60]}", file=sys.stderr)
            done += 1
            if done % 60 == 0:
                el = time.time() - start
                eta = (limit - done) * (el / done) / 60 if done else 0
                print(f"  [{done}/{limit}] {total_p}p {total_v}v, ETA {eta:.1f} dk", flush=True)
    print(f"\n  medya bulunan tweet: {with_m}")
    print(f"  fotoğraf: {total_p}, video/gif: {total_v}")
    print(f"  süre: {(time.time()-start)/60:.1f} dk\n")
    print("=== FAZ 2: links-only reclassification ===")
    stats = reclassify_links_only()
    if stats:
        for cat, n in sorted(stats.items(), key=lambda x: -x[1]):
            print(f"  {cat:30s} +{n}")
    else:
        print("  taşınan yok")
    print(f"  toplam taşınan: {sum(stats.values())}")


if __name__ == "__main__":
    main()
