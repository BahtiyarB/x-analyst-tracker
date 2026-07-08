#!/usr/bin/env python3
"""fetch_thread.py — Bir X tweet/thread linkinden TUM self-thread'i indirir.

Kullanim:
  python fetch_thread.py <url_veya_id> [--out DIR] [--json]
  python fetch_thread.py https://x.com/user/status/123 --out ~/Downloads

Ne yapar:
  1. URL/ID'den tweet id cikarir.
  2. `node x_tweetdetail.mjs <id>` ile TweetDetail JSON'u ceker (cookie-auth).
  3. thread_util.reconstruct_thread ile yazarin self-thread reply-zincirini kurar.
  4. <slug>.txt (duz metin) + <id>.thread.json (yapisal) yazar.

Thread degilse tek tweet'i yazar ("thread değil" notuyla). Cikti yolu: --out (varsayilan cwd).
"""
from __future__ import annotations
import sys, os, re, json, argparse, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from thread_util import reconstruct_thread, thread_to_txt

def parse_id(s: str) -> str | None:
    s = s.strip()
    m = re.search(r"status/(\d+)", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", s):
        return s
    return None

def slugify(text: str, maxlen: int = 60) -> str:
    tr = str.maketrans({"ç":"c","Ç":"c","ş":"s","Ş":"s","ı":"i","İ":"i",
                        "ğ":"g","Ğ":"g","ü":"u","Ü":"u","ö":"o","Ö":"o"})
    text = (text or "").translate(tr).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > maxlen:
        text = text[:maxlen].rsplit("-", 1)[0] or text[:maxlen]
    return text.strip("-")

def fetch_raw(tweet_id: str) -> dict:
    mjs = os.path.join(ROOT, "x_tweetdetail.mjs")
    r = subprocess.run(["node", mjs, tweet_id], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.stderr.write(r.stderr)
        raise RuntimeError(f"TweetDetail cekilemedi (exit {r.returncode})")
    return json.loads(r.stdout)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="X status URL veya tweet id")
    ap.add_argument("--out", default=".", help="cikti dizini (varsayilan: cwd)")
    ap.add_argument("--json", action="store_true", help="ayrica yapisal .thread.json yaz")
    args = ap.parse_args()

    tid = parse_id(args.target)
    if not tid:
        sys.exit(f"Gecersiz hedef (URL ya da id bekleniyor): {args.target}")

    outdir = os.path.expanduser(args.out)
    os.makedirs(outdir, exist_ok=True)

    print(f"[thread] TweetDetail cekiliyor: {tid}", file=sys.stderr)
    raw = fetch_raw(tid)
    th = reconstruct_thread(raw, tid)
    if not th:
        sys.exit("Fokal tweet yanitta bulunamadi (silinmis/erisilemez olabilir).")

    # dosya adi: fokal metinden slug (yoksa yazar+id)
    first = th["tweets"][0]["text"]
    slug = slugify(first) or slugify(f"{th['author']}-{tid}")
    txt_path = os.path.join(outdir, f"{slug or tid}.txt")
    open(txt_path, "w", encoding="utf-8").write(thread_to_txt(th))

    print(f"[thread] {'THREAD' if th['is_thread'] else 'tek tweet'} · "
          f"{len(th['tweets'])} tweet · @{th['author']}", file=sys.stderr)
    print(txt_path)  # stdout: txt yolu (cagiran icin)

    if args.json:
        jpath = os.path.join(outdir, f"{tid}.thread.json")
        json.dump(th, open(jpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(jpath)

if __name__ == "__main__":
    main()
