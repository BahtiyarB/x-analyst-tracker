#!/usr/bin/env python3
"""bridge_to_chainwise.py — x-analyst-tracker -> ChainWise ingest_articles koprusu.

jawond-bird'in `user-tweets <handle> -n N --json` ciktisi canli cookie ile
dogrulanmis KESIN semaya sahiptir: ust duzey JSON bir DIZI (list), sarmalayici
YOK. Her eleman:

    {
      "id": "2072760978907742228",
      "text": "RT @Efloud: ...",
      "createdAt": "Thu Jul 02 19:15:02 +0000 2026",
      "replyCount": 0,
      "retweetCount": 17,
      "likeCount": 0,
      "conversationId": "...",
      "author": {"username": "KardesBaris", "name": "Baris Kardes"}
    }

- id            -> tweet["id"]
- text          -> tweet["text"]
- author handle -> tweet["author"]["username"]
- created_at    -> tweet["createdAt"], klasik Twitter/RFC2822 format
                   ("Thu Jul 02 19:15:02 +0000 2026"),
                   email.utils.parsedate_to_datetime ile parse edilir.

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
ChainWise'in kendi sqlalchemy/uv ortami ayri oldugu icin bu script'i
ChainWise repo'sunda `uv run python bridge_to_chainwise.py ...` ile
calistirmak (ya da PYTHONPATH'i o ortama gore ayarlamak) gerekir; aksi halde
import hatasi alinir (asagida run() icinde net bir hata mesaji uretilir).

Kullanim:
    uv run python bridge_to_chainwise.py \
        out/tweets_KardesBaris_20260706.json \
        --chainwise-repo /Users/ahmet/Projects/ChainWise/repo \
        [--skip-retweets] [--dry-run]

    # veya --input-dir ile bir klasordeki tum tweets_*.json dosyalarini isle:
    uv run python bridge_to_chainwise.py \
        --input-dir ./out --skip-retweets --dry-run

Idempotency: Article.url UNIQUE kisitina dayanir (session_scope + upsert ile
conflict_cols=["url"] kullanilir). Ayni tweet ikinci kez calistirildiginda
DO NOTHING davranisiyla atlanir (content_hash guncellenmez).

Retweet'ler analist gorusu degil (baskasinin tweetinin retweet'i), bu yuzden
--skip-retweets bayragiyla atlanabilir. Retweet tespiti: text.startswith("RT @").
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
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass
class NormalizedTweet:
    id: str
    handle: str
    created_at: datetime | None
    text: str
    url: str
    is_retweet: bool


def _parse_created_at(raw: Any) -> datetime | None:
    """Tweet zaman damgasini (tweet["createdAt"]) datetime'a cevirir.

    Canli dogrulanan format klasik Twitter/RFC2822'dir, ornek:
    "Thu Jul 02 19:15:02 +0000 2026". email.utils.parsedate_to_datetime bu
    formati dogrudan parse eder ve tz-aware bir datetime dondurur; UTC'ye
    normalize edilir.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        # epoch saniye ya da milisaniye - jawond-bird bu sekli donmuyor ama
        # gelecekte baska bir kaynaktan gelirse diye tolere edilir.
        ts = raw / 1000 if raw > 10_000_000_000 else raw
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(raw, str):
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        # yedek: ISO-8601 (jawond-bird kullanmiyor ama zararsiz bir tolerans)
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    return None


def _extract_id(tweet: dict[str, Any]) -> str | None:
    val = tweet.get("id")
    return str(val) if val else None


def _extract_text(tweet: dict[str, Any]) -> str | None:
    val = tweet.get("text")
    return str(val) if val else None


def _extract_handle(tweet: dict[str, Any], fallback_handle: str) -> str:
    author = tweet.get("author")
    if isinstance(author, dict):
        username = author.get("username")
        if username:
            return str(username).lstrip("@")
    return fallback_handle


def normalize_tweet(raw_tweet: dict[str, Any], fallback_handle: str) -> NormalizedTweet | None:
    """Ham jawond-bird tweet nesnesini NormalizedTweet'e cevirir.

    Alanlar: {id, handle, created_at(UTC datetime), text,
    url=f"https://x.com/{handle}/status/{id}", is_retweet}.
    """
    tweet_id = _extract_id(raw_tweet)
    text = _extract_text(raw_tweet)
    if not tweet_id or not text:
        return None

    handle = _extract_handle(raw_tweet, fallback_handle)
    created_at = _parse_created_at(raw_tweet.get("createdAt"))
    url = f"https://x.com/{handle}/status/{tweet_id}"
    is_retweet = text.startswith("RT @")

    return NormalizedTweet(
        id=tweet_id,
        handle=handle,
        created_at=created_at,
        text=text,
        url=url,
        is_retweet=is_retweet,
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
    """jawond-bird `user-tweets --json` ciktisini okuyup tweet listesi dondurur.

    Canli dogrulanan sema: ust duzey JSON dogrudan bir dizi (list), sarmalayici
    yok. Yine de olasi eski/farkli formatlara (search --json vb. sarmalayici
    donebilecek komutlara) karsi esnek bir fallback birakilmistir.
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


def run(
    chainwise_repo: str,
    input_dir: str | None,
    input_files: list[str],
    dry_run: bool,
    skip_retweets: bool,
) -> None:
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
            f"--chainwise-repo dogru mu? Bu script ChainWise'in kendi "
            f"sqlalchemy ortamina ihtiyac duyar: ChainWise repo'da `uv run` ile "
            f"calistirin (ornek: cd {repo_path} && uv run python "
            f"/path/to/bridge_to_chainwise.py ...) ya da PYTHONPATH'i o "
            f"ortama gore ayarlayin. Detay: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    if input_files:
        paths = [Path(p) for p in input_files]
    else:
        paths = list(iter_tweet_files(input_dir or "./out"))

    total_files = 0
    total_tweets = 0
    total_written = 0
    total_skipped = 0
    total_retweets_skipped = 0

    for path in paths:
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
            if skip_retweets and normalized.is_retweet:
                total_retweets_skipped += 1
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
        f"yazilan(deneme): {total_written}, atlanan: {total_skipped}, "
        f"RT-atlanan: {total_retweets_skipped}"
    )
    yeni = total_tweets if dry_run else total_written
    atlanan = total_skipped + total_retweets_skipped
    print(f"{yeni} yeni, {atlanan} atlandi")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="x-analyst-tracker tweet ciktilarini ChainWise ingest_articles tablosuna yazar."
    )
    parser.add_argument(
        "input_files",
        nargs="*",
        help="Islenecek belirli tweets_*.json dosyalari (verilmezse --input-dir kullanilir)",
    )
    parser.add_argument(
        "--chainwise-repo",
        default="/Users/ahmet/Projects/ChainWise/repo",
        help="ChainWise repo kok dizini (varsayilan: /Users/ahmet/Projects/ChainWise/repo)",
    )
    parser.add_argument(
        "--input-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"),
        help="fetch_analysts.sh'nin yazdigi tweets_*.json dosyalarinin bulundugu klasor (varsayilan: ./out). "
        "input_files verilmisse yok sayilir.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Veritabanina yazmadan sadece normalize edilen tweetleri ozetler.",
    )
    parser.add_argument(
        "--skip-retweets",
        action="store_true",
        help="Retweet'leri (text 'RT @' ile basliyorsa) atlar; retweet'ler analist gorusu degildir.",
    )
    args = parser.parse_args()
    run(
        args.chainwise_repo,
        args.input_dir,
        args.input_files,
        args.dry_run,
        args.skip_retweets,
    )


if __name__ == "__main__":
    main()
