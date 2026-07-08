#!/usr/bin/env python3
"""build_threads.py — Bookmark'lardan thread olanlari tespit edip kaydeder (Faz 2).

Mevcut TweetDetail raw'larindan (x_articles_raw/ + x_threads_rawjson/) her bookmark icin
self-thread'i kurar; thread olanlari `x_threads_raw/<id>.json` (reconstruct edilmis, kompakt)
olarak yazar + `x_threads_checked.json` manifest'ine isler (idempotent — tekrar cekmemek icin).

build_html.py bu `x_threads_raw/<id>.json`'lari okuyup bookmark HTML'ine `## Thread` bolumu ekler.

Akis:
  1. (opsiyonel) Non-article bookmark id'leri icin raw cek:
       ls'le _filemap'ten id'ler - x_articles_raw'da olmayanlar -> ids.txt
       node fetch_articles.mjs --file ids.txt x_threads_rawjson   (rate-limited, ~1 saat)
  2. python build_threads.py   -> mevcut TUM raw'lari isle, thread'leri kaydet
Idempotent: her cagride mevcut raw'lardan yeniden uretir; batch ilerledikce tekrar kosulabilir.
"""
from __future__ import annotations
import os, sys, glob, json, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thread_util import reconstruct_thread

ROOT = os.path.dirname(os.path.abspath(__file__))
FILEMAP = os.path.join(ROOT, "_filemap.csv")
RAW_DIRS = [os.path.join(ROOT, "x_articles_raw"), os.path.join(ROOT, "x_threads_rawjson")]
OUT_DIR = os.path.join(ROOT, "x_threads_raw")
MANIFEST = os.path.join(ROOT, "x_threads_checked.json")

def all_bookmark_ids():
    ids = []
    if os.path.exists(FILEMAP):
        with open(FILEMAP, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ids.append(row["tweet_id"])
    return ids

def find_raw(tid):
    for d in RAW_DIRS:
        p = os.path.join(d, tid + ".json")
        if os.path.exists(p):
            return p
    return None

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {}
    if os.path.exists(MANIFEST):
        try: manifest = json.load(open(MANIFEST, encoding="utf-8"))
        except Exception: manifest = {}

    ids = all_bookmark_ids()
    have_raw = miss_raw = threads = singles = 0
    for tid in ids:
        raw_path = find_raw(tid)
        if not raw_path:
            miss_raw += 1
            continue
        have_raw += 1
        try:
            raw = json.load(open(raw_path, encoding="utf-8"))
        except Exception:
            continue
        th = reconstruct_thread(raw, tid)
        if not th:
            manifest[tid] = {"is_thread": False, "n": 0}
            continue
        manifest[tid] = {"is_thread": th["is_thread"], "n": len(th["tweets"])}
        if th["is_thread"]:
            threads += 1
            json.dump(th, open(os.path.join(OUT_DIR, tid + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
        else:
            singles += 1
            # tek tweet ise varsa eski thread dosyasini temizle (tutarlilik)
            stale = os.path.join(OUT_DIR, tid + ".json")
            if os.path.exists(stale):
                os.remove(stale)

    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"[threads] bookmark={len(ids)}  raw_var={have_raw}  raw_yok={miss_raw}")
    print(f"[threads] THREAD={threads}  tek_tweet={singles}  -> {OUT_DIR}/")
    # ids-to-fetch ozet: raw'i olmayanlar (henuz cekilmemis)
    if miss_raw:
        print(f"[threads] NOT: {miss_raw} bookmark'in raw'i yok — batch cekim gerekli "
              f"(bkz. dosya basi: node fetch_articles.mjs --file <ids> x_threads_rawjson)")

if __name__ == "__main__":
    main()
