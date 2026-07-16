# Oturum Handoff — 2026-07-08 → 2026-07-11

**Model:** Claude Opus 4.8 (`claude-opus-4-8`) · **Repo:** BahtiyarB/x-analyst-tracker
**Kapsam:** X (Twitter) bookmark indirme/kategorize pipeline'ının geliştirilmesi —
HTML çıktı formatı, thread çekme özelliği, içerik-tamlık düzeltmesi, tam yeniden-kurulum (v6).

Bu doküman bu oturumda **fiilen yapılan işi** özetler. Pipeline'ın tam teknik referansı
`scripts/bookmarks/HANDOFF.md`'de; bu dosya oturumun neyi neden değiştirdiğini anlatır.

---

## 1. v4 — `.md` → adlandırılmış `.html` (inline medya)

Önceki durum: her bookmark `<tweet_id>.md` idi. İstek: anlamlı-adlı, medyası tek sayfada
gömülü HTML.

- **`build_html.py`**: her bookmark'ı `<descriptor>.html`'e çevirir.
  - Dosya adı = hibrit descriptor: article başlığı / metnin ilk kelimeleri / link path'i.
    Türkçe translit + slug + çakışma eki.
  - Görünen H1 başlık slug'dan ayrı (insan-okunur).
  - Medya inline: `<img>` / `<video controls>`; article gövdesi ham DraftJS'ten
    (bold/italik/link korunur).
  - Eski `.md` → `_md_backup/`.
- **Öğrenilen:** lokal Qwen `qwen3.6-35b-...-aggressive` descriptor/kategori için
  **kullanılamıyor** — sürekli reasoning yapıp boş `content` dönüyor. Descriptor mantığı
  link/author heuristiğine geçirildi (deterministik, LLM'siz).

## 2. Thread çekme özelliği (Faz 1 + Faz 2)

İstek: verilen ya da bookmark edilen tweet thread ise **tüm self-thread** çekilsin.

- **Çekirdek:** `x_tweetdetail.mjs` — ortak TweetDetail GraphQL istemcisi (cookie-auth,
  Chrome "Profile 2"). `fetch_articles.mjs` de bunu kullanacak şekilde refactor edildi
  (çıktı doğrulandı, aynı). `thread_util.py` — yazarın `in_reply_to` reply-zincirini kurar,
  txt/html'e çevirir.
- **Ad-hoc (Faz 1):**
  - `fetch_thread.py <url|id>` → temiz `.txt` (+ `.thread.json`).
  - `fetch_thread_html.py <url|id>` → tek self-contained `.html` (X Article gövdesi + thread +
    medya; görseller base64 gömülü). X Article'ları da işler.
- **Bookmark entegrasyonu (Faz 2):**
  - `build_threads.py` — mevcut TweetDetail raw'larından thread'leri ayıklar → `x_threads_raw/`.
  - `build_html.py`'ye `## Thread (devamı)` bölümü eklendi (fokal hariç devam tweet'leri).
  - 517 non-article bookmark için rate-limited TweetDetail batch çekildi (~1 saat, 4 pencere).
  - Sonuç: **296/724 bookmark thread** (%41), en uzunu **31 tweet**, ortalama 4.6.
- **Kalıcı hafıza** yazıldı: "kullanıcı X linki verince tek tweet'le yetinme, tüm thread'i çek".

## 3. İçerik-tamlık düzeltmesi (KRİTİK bug)

Kullanıcı bir X Article'da eksik içerik fark etti. Sistematik debugging ile kök neden bulundu:
`build_html.article_from_draftjs` atomic bloklarda **yalnız MEDIA(foto)+DIVIDER** işliyordu.
Düşen içerik:
- **Video medya** (AmplifyVideo; `media_info.variants` mp4, `original_img_url` yok) → `<video>`
  + poster, URL'den en yüksek çözünürlük.
- **MARKDOWN atomic entity** (`data.markdown`, çoğu prompt/kod bloğu) → `<pre><code>`
  (satır-kaydırmalı). Metin `block.text`'te olmadığı için ilk kontroller ıskalamıştı.
- Etki: humzaakhalid makalesinde 3 video + 11 prompt geri geldi; koleksiyonda **22 bookmark'a
  video, 98'ine kod bloğu** eklendi. (commit `d6369f4`)

## 4. v6 — tam yeniden-indirme + yeniden-kategorize + timestamp adlandırma

İstek: bütün bookmark'ları gözden geçir + tekrar indir (görsel/kod eksik olmasın), dosya
adı başına **tweet'in tarihi**, hepsini **tekrar kategorize**, zip + push.

- **`rebuild_v6.py`** — koleksiyonu TweetDetail + raw + yerel medyadan sıfırdan kurar (paralel).
  - Taze bird çekimi: **721 güncel bookmark** (8 yeni indirildi, 11 kaldırılan düşürüldü).
  - Dosya adı: `<YYYY-MM-DD>_<descriptor>.html` (tweet tarihi başta, kronolojik sıralanır).
  - İçerik-tam: §3 fix + yerel tweet medyası (`../_media/<id>/`).
  - **Yeniden kategorize:** LLM bozuk olduğu için zengin içerik (tweet + article gövdesi +
    thread + link domaini) üzerine regex → **misc 302 → 220**, links-only eridi, 15 kategori.
  - Medya kök `_media/`'ye birleştirildi (kategori-bağımsız, 355 klasör/428 dosya).
  - Doğrulama: 721/721 well-formed, 180 video + 145 kod bloğu + 293 thread. (commit `0da96b3`)

## 5. Diğer

- **`saved_articles/`** — @humzaakhalid "clone Fable 5 into Opus 4.8" makalesi self-contained
  HTML olarak indirilip repo'ya kondu (commit `7aac03c`, düzeltmeli `d6369f4`).
- **Telegram:** v5 kompakt zip + humzaakhalid makalesi operator chat'ine gönderildi.
- **Export zip** (`bookmarks_v6_20260711.zip`, 34MB: 721 HTML + 282 görsel, video hariç):
  önce repo'ya kondu, sonra kullanıcı isteğiyle git'ten kaldırıldı (commit amend + force-push,
  geçmişten de silindi) ve `out/downloads/`'a (gitignore) taşındı.

---

## Bu oturumun commit'leri (en yeni → eski)

- `0da96b3` bookmarks v6: full re-download + re-categorize + timestamp naming (rebuild_v6.py)
- `d6369f4` fix: article DraftJS atomic blocks — render video + MARKDOWN (were dropped)
- `7aac03c` saved_articles: @humzaakhalid clone-Fable-5 (X Article, self-contained HTML)
- `87c2959` fetch_thread_html.py — ad-hoc X article/thread → self-contained HTML
- `fa4893b` HANDOFF v5 — thread batch sonucu (296/724 thread)
- `c847724` thread bookmark integration (Faz 2) — build_threads.py + '## Thread'
- `6d94aa0` thread fetcher (Faz 1) — x_tweetdetail.mjs + fetch_thread.py + thread_util.py
- `42ed5b1` preview: .claude/launch.json

## Mevcut durum

- 721 güncel bookmark, `<kategori>/<tarih>_<descriptor>.html` (gitignore'lu `out/bookmarks_download/`).
- Medya kök `_media/` (18GB, çoğu video). Export zip `out/downloads/` (gitignore).
- Version-control'de: `scripts/bookmarks/*.py|*.mjs` + `HANDOFF.md` + `saved_articles/` + `docs/`.
- Repo temiz, origin senkron (`0da96b3`).

## Bilinen sınırlar / devralana notlar

1. **LLM (Qwen) bozuk** — descriptor/kategori için boş dönüyor; her yerde regex/heuristik
   kullanıldı. Farklı bir yerel model bağlanırsa kategorizasyon daha da iyileşir.
2. **Video zip'te yok** — 18GB, GitHub limitini aşar. Export zip HTML + görsel (34MB); yerel
   video linkleri zip'te kırık, tam `_media/` yerelde.
3. **Twitter GraphQL query-id kırılgan** — `x_tweetdetail.mjs` QID'si bozulursa
   x-graphql-recovery skill / bird ile güncellenmeli.
4. **Article içi görseller remote** (pbs/video.twimg) — çevrimiçi çalışır, offline değil.
5. **Timestamp = tarih** (saat değil). İstenirse `YYYYMMDD-HHMMSS` yapılabilir.

## Yeniden koşma

```bash
cd ~/Projects/x-analyst-tracker
# taze bookmark:
CHROME_PROFILE="Profile 2" node jawond-bird/dist/index.js --chrome-profile "Profile 2" \
  bookmarks --json --all --max 2000 > out/bookmarks_download/raw/bookmarks_$(date +%Y%m%d).json
cd out/bookmarks_download
# yeni id'lerin TweetDetail'i:  node fetch_articles.mjs --file <ids.txt> x_threads_rawjson
uv run --no-project --with httpx python rebuild_v6.py      # tam yeniden-kurulum
# ad-hoc thread/makale:  uv run --no-project python fetch_thread_html.py <url> --out ~/Downloads
```
