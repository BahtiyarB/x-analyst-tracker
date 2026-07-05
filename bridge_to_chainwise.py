#!/usr/bin/env python3
"""bridge_to_chainwise.py — x-analyst-tracker -> ChainWise ingest_articles koprusu.

BU DOSYA ISKELETTIR. jawond-bird'in gercek "search --json" cikti semasi henuz
cookie ile dogrulanmadi (bu ortamda X'e agla istegi atilmadi). Asagidaki
normalize_tweet() fonksiyonundaki alan adlari (id/text/created_at/vb.) en
olasi GraphQL/adapter seklidir ama TODO olarak isaretlenen noktalar operator
tarafindan gercek bir `node jawond-bird/dist/index.js search "from:x" -n 5
--json` ciktisiyla karsilastirilarak dogrulanmalidir.

Bu script, x-analyst-tracker/out/tweets_*.json dosyalarini okuyup her tweeti
ChainWise'in ingest_articles tablosuna (src.common.models.Article) yazar.
ChainWise bu tabloyu zaten RSS/blog makaleleri icin kullaniyor (bkz.
migrations/versions/0003_ingest_articles.py, prompts/extract_text.md); ayni
hat (scripts/extract_articles.py / scripts/load_text_signals.py) tweetleri de
"makale" gibi isleyip sinyal cikaracaktir. Yani bu bridge YENI bir sinyal
hatti KURMUYOR, mevcut metin-sinyal hattina bir besleme (feeder) ekliyor.

x-analyst-tracker AYRI BIR PROJE oldugu icin ChainWise repo'suna dogrudan
import bagi yok; --chainwise-repo argumaniyla verilen yol sys.path'e eklenir
ve import orada calisir. Bu sayede iki proje birbirinden bagimsiz gelisebilir.

Kullanim:
    python3 bridge_to_chainwise.py \
        --chainwise-repo /Users/ahmet/Projects/ChainWise/repo \
        --input-dir ./out \
        [--dry-run]

Idempotency: Article.url UNIQUE kisitina dayanir (session_scope + upsert ile
conflict_cols=["url"] kullanilir). Ayni tweet ikinci kez calistirildiginda
DO NOTHING davranisiyla atlanir (content_hash guncellenmez).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass
class NormalizedTweet:
    id: str
    handle: str
    created_at: datetime | None
    text: str
    url: str


def _parse_created_at(raw: Any) -> datetime | None:
    """Tweet zaman damgasini datetime'a cevirir.

    TODO(cookie-dogrulama): jawond-bird'in search --json ciktisinda
    zaman alani "created_at" (Twitter'in klasik RFC2822 formati, ör.
    "Wed Oct 10 20:19:24 +0000 2018") mi yoksa ISO-8601 mi donuyor,
    yoksa Sweetistics/GraphQL adaptorunde farkli bir isim (ornegin
    "createdAt", "timestamp", "legacy.created_at") mi kullaniliyor —
    gercek bir ciktiyla dogrulanmadan bilinemiyor. Asagida hem klasik
    Twitter formatini hem ISO-8601'i deneyen genis bir parser var;
    gercek semaya gore daraltilmali.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        # epoch saniye ya da milisaniye olabilir - TODO dogrula
        ts = raw / 1000 if raw > 10_000_000_000 else raw
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(raw, str):
        # 1) Klasik Twitter formati: "Wed Oct 10 20:19:24 +0000 2018"
        try:
            return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            pass
        # 2) ISO-8601
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _extract_handle(tweet: dict[str, Any], fallback_handle: str) -> str:
    """Tweet nesnesinden yazar handle'ini cikarir, yoksa dosya adindan gelen
    fallback'i kullanir.

    TODO(cookie-dogrulama): jawond-bird ciktisinda yazar bilgisi
    "user.screen_name", "author.username", "username" gibi farkli
    yollarda olabilir. asagidaki liste tahminidir, gercek semaya gore
    guncellenmelidir.
    """
    candidates = [
        tweet.get("username"),
        tweet.get("screen_name"),
        (tweet.get("user") or {}).get("screen_name") if isinstance(tweet.get("user"), dict) else None,
        (tweet.get("author") or {}).get("username") if isinstance(tweet.get("author"), dict) else None,
    ]
    for c in candidates:
        if c:
            return str(c).lstrip("@")
    return fallback_handle


def _extract_id(tweet: dict[str, Any]) -> str | None:
    """TODO(cookie-dogrulama): id alani "id", "id_str", veya "rest_id"
    olabilir (Twitter GraphQL genelde rest_id + id_str ikisini de dondurur).
    """
    for key in ("id_str", "id", "rest_id", "tweet_id"):
        val = tweet.get(key)
        if val:
            return str(val)
    return None


def _extract_text(tweet: dict[str, Any]) -> str | None:
    """TODO(cookie-dogrulama): metin alani "text", "full_text", veya
    "legacy.full_text" (GraphQL'in "legacy" nested yapisi) olabilir.
    """
    if isinstance(tweet.get("legacy"), dict) and tweet["legacy"].get("full_text"):
        return tweet["legacy"]["full_text"]
    for key in ("full_text", "text"):
        val = tweet.get(key)
        if val:
            return str(val)
    return None


def normalize_tweet(raw_tweet: dict[str, Any], fallback_handle: str) -> NormalizedTweet | None:
    """Ham jawond-bird tweet nesnesini (id, handle, created_at, text, url) yapisina cevirir.

    TODO(cookie-dogrulama): Bu fonksiyonun tum alan-adi varsayimlari
    cookie ile yapilacak gercek bir `search --json` testinden sonra
    dogrulanmali / duzeltilmelidir. Bu iskelet, en olasi Twitter GraphQL
    / jawond-bird cikti semasina gore yazilmistir.
    """
    tweet_id = _extract_id(raw_tweet)
    text = _extract_text(raw_tweet)
    if not tweet_id or not text:
        return None

    handle = _extract_handle(raw_tweet, fallback_handle)
    created_at = _parse_created_at(
        raw_tweet.get("created_at")
        or (raw_tweet.get("legacy") or {}).get("created_at")
    )
    url = f"https://x.com/{handle}/status/{tweet_id}"

    return NormalizedTweet(
        id=tweet_id,
        handle=handle,
        created_at=created_at,
        text=text,
        url=url,
    )


def iter_tweet_files(input_dir: str) -> Iterable[Path]:
    pattern = str(Path(input_dir) / "tweets_*.json")
    for path in sorted(glob.glob(pattern)):
        yield Path(path)


def handle_from_filename(path: Path) -> str:
    """tweets_<handle>_<tarih>.json dosya adindan handle'i cikarir."""
    stem = path.stem  # tweets_<handle>_<tarih>
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "tweets":
        # tarih son parca (YYYYMMDD), handle ortadaki her sey
        return "_".join(parts[1:-1])
    return "unknown"


def load_tweets_from_file(path: Path) -> list[dict[str, Any]]:
    """jawond-bird search --json ciktisini okuyup tweet listesi dondurur.

    TODO(cookie-dogrulama): jawond-bird `search --json` komutunun ciktisi
    duz bir JSON dizisi mi ({"tweets": [...]} gibi bir sarmalayici mi,
    yoksa {"data": {"tweets": [...]}} gibi nested bir GraphQL yaniti mi
    donduruyor bilinmiyor - cookie testinden sonra dogrulanmali. Asagida
    en yaygin 3 sekli de deneyen esnek bir parser var.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"UYARI: {path} JSON olarak ayristirilamadi: {e}", file=sys.stderr)
        return []

    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("tweets", "results", "data", "items"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                inner = val.get("tweets") or val.get("results")
                if isinstance(inner, list):
                    return inner
    print(f"UYARI: {path} icin beklenmeyen JSON semasi, atlaniyor.", file=sys.stderr)
    return []


def build_article_values(tweet: NormalizedTweet) -> dict[str, Any]:
    """NormalizedTweet -> Article satiri (dict) icin degerler.

    ChainWise Article semasi (src/common/models.py):
        source, url, title, author, published_at, content_text,
        content_hash, status, fetched_at (server_default).
    """
    content_text = tweet.text
    content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    title = content_text[:120].replace("\n", " ").strip() or f"tweet {tweet.id}"

    return {
        "source": f"x:{tweet.handle}",
        "url": tweet.url,
        "title": title,
        "author": tweet.handle,
        "published_at": tweet.created_at,
        "content_text": content_text,
        "content_hash": content_hash,
        "status": "new",
    }


def run(chainwise_repo: str, input_dir: str, dry_run: bool) -> None:
    repo_path = str(Path(chainwise_repo).resolve())
    if repo_path not in sys.path:
        sys.path.insert(0, repo_path)

    # ChainWise'in kendi modullerini burada, sys.path ayarlandiktan sonra import
    # ediyoruz (bu ayri proje oldugu icin dogrudan ust duzeyde import etmiyoruz).
    try:
        from src.common.db import session_scope, upsert  # type: ignore
        from src.common.models import Article  # type: ignore
    except ImportError as e:
        print(
            f"HATA: ChainWise modulleri import edilemedi ({repo_path} altinda). "
            f"--chainwise-repo dogru mu? Detay: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    total_files = 0
    total_tweets = 0
    total_written = 0
    total_skipped = 0

    for path in iter_tweet_files(input_dir):
        total_files += 1
        fallback_handle = handle_from_filename(path)
        raw_tweets = load_tweets_from_file(path)

        values_batch: list[dict[str, Any]] = []
        for raw_tweet in raw_tweets:
            if not isinstance(raw_tweet, dict):
                total_skipped += 1
                continue
            normalized = normalize_tweet(raw_tweet, fallback_handle)
            if normalized is None:
                total_skipped += 1
                continue
            total_tweets += 1
            values_batch.append(build_article_values(normalized))

        if not values_batch:
            print(f"{path}: yazilacak tweet yok (0 gecerli tweet).")
            continue

        if dry_run:
            print(f"{path}: {len(values_batch)} tweet DRY-RUN icin hazir (yazilmadi).")
            for v in values_batch[:3]:
                print(f"  ornek -> source={v['source']} url={v['url']} title={v['title'][:60]!r}")
            continue

        with session_scope() as session:
            upsert(
                session,
                Article,
                values_batch,
                conflict_cols=["url"],
                update_cols=None,  # DO NOTHING: url zaten varsa atla (idempotent)
            )
            total_written += len(values_batch)
        print(f"{path}: {len(values_batch)} tweet ingest_articles'a yazildi (veya zaten vardi).")

    print("---")
    print(
        f"Dosya: {total_files}, tweet(gecerli): {total_tweets}, "
        f"yazilan(deneme): {total_written}, atlanan: {total_skipped}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="x-analyst-tracker tweet ciktilarini ChainWise ingest_articles tablosuna yazar."
    )
    parser.add_argument(
        "--chainwise-repo",
        required=True,
        help="ChainWise repo kok dizini (ornek: /Users/ahmet/Projects/ChainWise/repo)",
    )
    parser.add_argument(
        "--input-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"),
        help="fetch_analysts.sh'nin yazdigi tweets_*.json dosyalarinin bulundugu klasor (varsayilan: ./out)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Veritabanina yazmadan sadece normalize edilen tweetleri ozetler.",
    )
    args = parser.parse_args()
    run(args.chainwise_repo, args.input_dir, args.dry_run)


if __name__ == "__main__":
    main()
