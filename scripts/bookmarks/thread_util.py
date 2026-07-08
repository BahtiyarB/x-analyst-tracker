#!/usr/bin/env python3
"""thread_util.py — TweetDetail JSON'undan yazarin self-thread'ini kurar + formatlar.

Ortak modul: fetch_thread.py (ad-hoc) ve build_html.py (bookmark entegrasyonu) kullanir.

reconstruct_thread(raw, focal_id) -> {
    "focal": id, "author": screen_name, "name": full_name, "created": ...,
    "is_thread": bool, "tweets": [{"id","text","created","reply_to"}...]  # fokal dahil, sirali
}
thread_to_txt(thread)  -> duz metin (baslik + numarali tweet'ler)
thread_to_html(thread) -> "## Thread" HTML bolumu (build_html.py icin)

Self-thread = fokal tweet + ayni yazarin `in_reply_to` zincirini takip eden tweet'leri.
"""
from __future__ import annotations
import html as _html
import re

# ---------------------------------------------------------------- TweetDetail parse
def _unwrap(res):
    if not isinstance(res, dict):
        return None
    if res.get("__typename") == "TweetWithVisibilityResults":
        return res.get("tweet")
    return res

def _screen_name(res):
    core = (res.get("core") or {}).get("user_results", {}).get("result", {})
    return ((core.get("core") or {}).get("screen_name")
            or (core.get("legacy") or {}).get("screen_name") or "?")

def _full_name(res):
    core = (res.get("core") or {}).get("user_results", {}).get("result", {})
    return ((core.get("core") or {}).get("name")
            or (core.get("legacy") or {}).get("name") or "")

def _get_text(res):
    nt = (((res.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {})
    if nt.get("text"):
        return nt["text"]
    return (res.get("legacy") or {}).get("full_text", "")

def _collect_all_tweets(raw):
    """Yanittaki tum tweet objelerini {id: {...}} olarak topla + t.co->expanded url map."""
    tweets = {}
    urlmap = {}

    def collect_urls(res):
        lg = (res.get("legacy") or {}).get("entities", {}) or {}
        nt = (((res.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {})
        nte = (nt.get("entity_set") or {})
        for src in (lg.get("urls") or []) + (nte.get("urls") or []):
            if src.get("url") and src.get("expanded_url"):
                urlmap[src["url"]] = src["expanded_url"]

    def walk(o):
        if isinstance(o, dict):
            tr = o.get("tweet_results")
            if isinstance(tr, dict):
                res = _unwrap(tr.get("result"))
                if isinstance(res, dict) and (res.get("legacy") or {}).get("full_text") is not None:
                    rid = res.get("rest_id")
                    if rid and rid not in tweets:
                        lg = res["legacy"]
                        collect_urls(res)
                        tweets[rid] = {
                            "id": rid, "author": _screen_name(res), "name": _full_name(res),
                            "reply_to": lg.get("in_reply_to_status_id_str"),
                            "created": lg.get("created_at"), "text": _get_text(res),
                        }
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(raw)
    return tweets, urlmap

def reconstruct_thread(raw: dict, focal_id: str) -> dict | None:
    """Fokal tweet'ten baslayarak ayni yazarin reply-zincirini kurar."""
    tweets, urlmap = _collect_all_tweets(raw)
    if focal_id not in tweets:
        return None
    focal = tweets[focal_id]
    fa = focal["author"]

    chain = [focal]
    cur = focal_id
    while True:
        nxt = [t for t in tweets.values() if t["reply_to"] == cur and t["author"] == fa]
        if not nxt:
            break
        nxt.sort(key=lambda t: int(t["id"]))
        chain.append(nxt[0])
        cur = nxt[0]["id"]

    def clean(txt):
        txt = _html.unescape(txt or "")
        for tco, exp in urlmap.items():
            txt = txt.replace(tco, exp)
        # sondaki self-thread t.co (kendi sonraki tweet'ine link) -> at
        txt = re.sub(r"\s*https://t\.co/\w+\s*$", "", txt).rstrip()
        return txt

    for t in chain:
        t["text"] = clean(t["text"])

    return {
        "focal": focal_id, "author": fa, "name": focal.get("name", ""),
        "created": focal.get("created", ""), "is_thread": len(chain) > 1,
        "tweets": chain,
    }

# ---------------------------------------------------------------- formatlar
def thread_to_txt(th: dict) -> str:
    fa = th["author"]; name = th.get("name", "")
    n = len(th["tweets"])
    out = []
    label = "Thread" if th["is_thread"] else "Tweet"
    out.append(f"{label} by @{fa}" + (f" ({name})" if name else ""))
    out.append(f"URL:   https://x.com/{fa}/status/{th['focal']}")
    out.append(f"Tarih: {th.get('created','')}")
    out.append(f"Tweet sayısı: {n}")
    if not th["is_thread"]:
        out.append("(Not: bu tek bir tweet — thread değil.)")
    out.append("=" * 70)
    out.append("")
    for i, t in enumerate(th["tweets"], 1):
        out.append(f"[{i}/{n}]")
        out.append(t["text"])
        out.append("")
        out.append("-" * 70)
        out.append("")
    return "\n".join(out).rstrip() + "\n"

def thread_to_html(th: dict) -> str:
    """build_html.py'nin '## Thread' bolumu icin HTML (fokal HARIÇ — geri kalan zincir)."""
    rest = th["tweets"][1:]  # fokal zaten bookmark'in kendi icerigi
    if not rest:
        return ""
    parts = []
    for i, t in enumerate(rest, 2):
        body = _html.escape(t["text"]).replace("\n", "<br>")
        # url linkify
        body = re.sub(r"(https?://[^\s<>()]+)",
                      lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>',
                      body)
        parts.append(f'<div class="thread-tweet"><span class="thread-n">{i}/{len(th["tweets"])}</span>'
                     f'<div class="thread-body">{body}</div></div>')
    return "\n".join(parts)
