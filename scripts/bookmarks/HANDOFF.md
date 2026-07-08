# Twitter Bookmarks Download & Categorization — HANDOFF

> **Kim için:** Bu dokümanı başka bir Claude Code oturumunda (ya da başka bir
> AI/kişi) bookmark projesini devralmak için kullan. Tüm scriptler, öğrenilenler,
> yapılan seçimler, bilinen sınırlar burada.
>
> **Tarih:** 2026-07-08 · **Durum:** ✅ TAMAM (v3 — X Articles dahil).
> Daha sonra "yeni bookmark'ları da al" ya da "ikinci tur medya çek" istenirse
> tüm scriptler idempotent olarak yeniden koşulabilir.
>
> **Proje kökü:** `~/Projects/x-analyst-tracker/out/bookmarks_download/`

---

## 1. Görev tanımı

Operatör'ün Twitter (X) bookmark'larının **tamamını** indirmek:
- Tweet metni + metadata (yazar, tarih, metrikler)
- Tweet'e ekli medyalar (fotoğraf, video, GIF)
- Tweet'te link olarak paylaşılmış harici makaleler (blog, GitHub README, PDF)
- **X'in kendi uzun-form Article'ları** (`x.com/i/article/<ID>` linkleri)
- Bookmark'ları **konu bazlı alt-klasörlere** ayır (claude-optimization, hermes,
  local-models, cybersecurity vb.)
- Kompakt zip'le Telegram'a gönder

## 2. Nihai sonuç (2026-07-08)

**Sayılar:**
- **724 bookmark** tam işlendi (`raw/bookmarks_20260708.json`)
- **207/207 X Article** çekildi + parse edildi (149'u ilk turda, kalan 58'i
  15-dakikalık rate-limit bekleme sonrası retry ile)
- **428 medya** indirildi (276 fotoğraf + 152 video/gif)
- **163 harici makale** çekildi (blog HTML + 45 GitHub README raw)
- **16 kategori** klasörü
- **Disk boyutu:** 19 GB (medya dahil)
- **Zip:** 1.9 MB (kompakt — medya + HTML dışarıda, .md + article body + README raw dahil)

**Final kategori dağılımı:**
```
claude-optimization  175     ai-generic            57
local-models          42     ai-agents             20
hermes                17     turkish-content       14
ai-research           14     crypto-onchain        14
cybersecurity         13     engineering-devtools  13
trading-quant         11     links-only            11 (kalan)
crypto-market         10     product-startup        8
life-philosophy        3     misc                 302
```

**Telegram'a gönderilen:**
`~/Projects/x-analyst-tracker/out/downloads/bookmarks_v3_20260708.zip`

## 3. Dizin yapısı (nihai)

```
~/Projects/x-analyst-tracker/out/bookmarks_download/
├── HANDOFF.md                      # bu doküman
├── raw/
│   └── bookmarks_20260708.json     # bird çıkışı — 724 bookmark (359 KB)
├── logs/
│   ├── process_fast.log            # ana pipeline log
│   ├── enrich.log                  # medya + reclassify
│   └── process_fast.err            # hata satırları
├── x_articles_raw/                 # 207 raw TweetDetail GraphQL yanıtı
│   └── <tweet_id>.json             # her article için ham JSON
├── <kategori>/                     # 16 kategori klasörü
│   ├── <tweet_id>.md               # bookmark markdown'ı (text + linkler + article body + medya listesi)
│   ├── _media/
│   │   └── <tweet_id>/
│   │       ├── *.jpg               # foto
│   │       └── *.mp4               # video
│   └── _articles/
│       ├── domain_path.html        # harici makale (blog vs.)
│       ├── domain_path.README.md   # GitHub raw README (JS-render bypass)
│       └── domain_path.AUTH_GATED  # login gerekli işareti
└── *.py / *.mjs                    # pipeline scriptleri (aşağıda)
```

## 4. Pipeline'ın adım adım hikayesi (kronolojik)

Kod okuduğunda mantığı anlamak için sıra:

### Adım 1 — Bookmark keşif (`bird bookmarks`)
```bash
cd ~/Projects/x-analyst-tracker
CHROME_PROFILE="Profile 2" node jawond-bird/dist/index.js \
    --chrome-profile "Profile 2" bookmarks --json --all --max 2000 \
    > out/bookmarks_download/raw/bookmarks_20260708.json
```
- jawond-bird'ün `bookmarks` komutu Twitter GraphQL `BookmarkSearchTimeline`'a
  cursor-pagination'la vurup 724 bookmark'ı JSON list olarak döner.
- **Cookie:** Chrome "Profile 2" profilinden okunur (jawond-bird'ün
  `extractCookiesFromChrome` fonksiyonu).
- JSON yapısı: `[{id, text, createdAt, replyCount, retweetCount, likeCount,
  conversationId, author: {username, name}}, ...]`
- **Not:** Bookmark JSON'unda medya URL'leri, resolved link'ler, article body
  YOK. Bunların hepsi ayrı çağrı gerektiriyor (Adım 3+).

### Adım 2 — Kural + LLM tabanlı kategorize etme (`process_fast.py`)
- İlk versiyon `process.py` çok yavaştı (~1 bookmark / 30 sn) — durduruldu.
- `process_fast.py` yeniden yazıldı:
  - **link-only tespiti:** URL'ler dışında <15 karakter içeriği olan tweet'ler
    → `links-only/` kategorisi (LLM'siz)
  - **Regex kuralları:** 14 kategori × spesifik pattern'ler (case-insensitive).
    En üst kategori önce eşleşir.
  - **LLM fallback** (yalnız kural eşleşmeyenlere): lokal Qwen 3.6-35B via
    LM Studio (`http://localhost:1234/v1/chat/completions`).
    Temperature 0.0, max_tokens 12.
  - **Paralel:** 8-12 thread pool worker.
- Her bookmark için:
  - `<kategori>/<tweet_id>.md` yazılır (Türkçe başlıklarla).
  - `t.co` link'leri HEAD redirect ile çözülür.
  - Çözülen link'ler harici makaleyse (github, blog, vb.) HTML olarak
    `_articles/` altına indirilir.
- **Sonuç:** ~4.3 dk, 3.3 bookmark/sn.

### Adım 3 — Medya çekimi + gap-fill (`enrich_all.py`)
- **Sorun:** bookmark JSON'unda medya URL'leri yok. Tweet HTML'i JS-render.
- **Çözüm:** Twitter'ın **public syndication API**'sini kullan:
  ```
  https://cdn.syndication.twimg.com/tweet-result?id=<TID>&token=x
  ```
  - Auth **gerekmez**, User-Agent yeterli.
  - Yanıt: `mediaDetails[]` içinde `media_url_https` (foto) ve
    `video_info.variants[]` (video, mp4 URL'leri).
- Her medya `<kategori>/_media/<tweet_id>/<dosya>` olarak indirilir.
- Bookmark `.md` dosyasının sonuna `## Medya` başlığıyla path listesi eklenir.
- **Ayrıca:** links-only'yi resolved URL domain'ine göre reclassify eder
  (github → engineering-devtools, arxiv → ai-research vb.).
  **BU AŞAMADA 0 TAŞIMA OLDU** çünkü links-only'lerin tümü `x.com/i/article/...`
  linkleri — X'in kendi article'ları (Adım 5'te çözüldü).
- **Sonuç:** ~6.4 dk, 12 worker.

### Adım 4 — HTML makale iyileştirme (`fix_articles.py`)
- Adım 2'de indirilen HTML makalelerin bazıları eksikti:
  - **GitHub sayfaları:** README'yi client-side render eder — HTML'de yok
  - **Auth-gated:** login sayfası olarak inmiş (Google Docs vb.)
- **Çözüm:**
  - `github.com/OWNER/REPO` → `raw.githubusercontent.com/.../README.md` fetch et
    → `<kategori>/_articles/<name>.README.md` olarak yaz
  - `github.com/OWNER/REPO/blob/BRANCH/PATH` → aynı repo'nun raw dosyası
  - Auth-gated tespit (URL pattern'i) → `.AUTH_GATED` boş dosya bırak (işaret)
  - Küçük dosyalarda (<5 KB) text extraction dene
- **Sonuç:** 45 GitHub README raw, 1 auth-gated.

### Adım 5 — X Articles keşfi + çözümü (KRİTİK)
**Sorun:** 207 links-only bookmark'ın hepsi `x.com/i/article/<ID>` — X'in
uzun-form Article platformu. Syndication API bunlara **404** verir. Sayfayı
doğrudan çekince SPA render — HTML'de içerik yok.

**Çözüm — bird'ün cookie extraction'ını + doğrudan GraphQL çağrısını**
(`fetch_articles.mjs`):
1. `jawond-bird/dist/lib/cookies.js`'ten `extractCookiesFromChrome('Profile 2')`
   çağır → `authToken` + `ct0` al.
2. `TweetDetail` GraphQL endpoint'ini çağır:
   - URL: `https://x.com/i/api/graphql/nBS-WpgA6ZG0CyNHD517JQ/TweetDetail`
   - Query ID `nBS-WpgA6ZG0CyNHD517JQ` (2026-07-06 itibarıyla geçerli, bird
     source'undan alındı; **kırılırsa güncellenmesi gerekir**).
   - **KRİTİK FIELD TOGGLE:** `withArticlePlainText: true` (bird varsayılan
     olarak `false` yapmıştı — bu yüzden bird'ün kendi `read` komutu article
     body'lerini vermiyor).
   - Auth header'ları: `Bearer <sabit bearer token>`, `x-csrf-token: ct0`,
     `cookie: auth_token=...; ct0=...`, `x-twitter-active-user: yes`, vb.
   - **Bearer token bird source'unda sabit yazılmış** (public — Twitter web
     istemcisinin token'ı).
3. Yanıt:
   ```
   data.threaded_conversation_with_injections_v2.instructions[1]
       .entries[0].content.itemContent.tweet_results.result
       .article.article_results.result
   ```
   → `title`, `preview_text`, `content_state.blocks[]` (DraftJS format).
4. **Rate limit:** ~140 istek sonrası HTTP 429 (window ~15 dk). Retry mantığı:
   - Betiği tekrar koş (`--file <retry.txt>` idempotent — mevcut `.json` skip)
   - 15 dk beklemek yeterli — retry batch 66 istek 100% başarılı.

### Adım 6 — Article body parse + reclassify (`parse_articles.py`)
- `x_articles_raw/<id>.json`'daki DraftJS blok yapısını Markdown'a çevir:
  - `unstyled` → düz paragraf
  - `header-N` → `#` × N
  - `unordered-list-item` → `- `
  - `ordered-list-item` → `1. `
- Bookmark `.md` dosyasının sonuna `## Article İçeriği` başlığıyla ekle.
- Article title + body'ye 14 kategori regex'i uygula → reclassify.
- **Yalnız `links-only/` içindeki dosyalar taşınır** (diğer kategoriler zaten
  doğru — zorla taşımıyoruz).
- **Sonuç:** 207 → 11 links-only. claude-optimization 59 → 175 (+196%).

### Adım 7 — Zip + Telegram
- Kompakt zip: HTML/medya/raw hariç, .md + README + Article body dahil.
- Boyut: 1.9 MB (10 MB Telegram sınırının altında).
- `curl` ile Telegram Bot API'sine POST.

## 5. Scriptler — sırayla ne yapar

| Dosya | Amaç | Girdi | Çıktı |
|---|---|---|---|
| `process_fast.py` | Ana pipeline: kategorize + link çöz + harici makale indir | `raw/bookmarks_*.json` | `<kategori>/*.md`, `_articles/*.html` |
| `enrich_all.py` | Twitter medyalarını syndication API'siyle indir; links-only reclassify | `<kategori>/*.md` | `<kategori>/_media/<id>/*.jpg\|.mp4` |
| `fix_articles.py` | HTML makale iyileştirme (GitHub README raw, auth işaretleme) | `_articles/*.html` | `_articles/*.README.md`, `*.AUTH_GATED` |
| `fetch_articles.mjs` | X Article'larını TweetDetail GraphQL ile çek (auth'lu) | Article ID listesi | `x_articles_raw/<id>.json` |
| `parse_articles.py` | Article JSON'unu Markdown'a çevir + reclassify | `x_articles_raw/*.json` | `.md` güncellenir, kategori taşınır |
| `process.py` | (arşiv — ilk yavaş versiyon) | — | — kullanma |
| `fetch_x_articles.py` | (arşiv — syndication API ile başarısız article denemesi) | — | — kullanma |

## 6. Yeniden koşma (idempotent)

Tüm scriptler zaten var olan dosyaları atlar. Baştan tümünü yeniden koşmak için:

```bash
cd ~/Projects/x-analyst-tracker/out/bookmarks_download

# 1) Yeni bookmark keşfi (mevcut raw'ın üstüne yazar; başka bir tarih için ayrı dosya kullan)
cd ~/Projects/x-analyst-tracker
CHROME_PROFILE="Profile 2" node jawond-bird/dist/index.js \
    --chrome-profile "Profile 2" bookmarks --json --all --max 2000 \
    > out/bookmarks_download/raw/bookmarks_$(date +%Y%m%d).json
cd out/bookmarks_download

# 2) Kategorize + harici makale indir (~5 dk)
WORKERS=8 uv run --no-project --with httpx python process_fast.py

# 3) Medya indir + links-only ilk pass reclassify (~6 dk)
WORKERS=12 uv run --no-project --with httpx python enrich_all.py

# 4) HTML makale iyileştirme (~1 dk)
uv run --no-project --with httpx python fix_articles.py

# 5) links-only ID'lerini çıkar
ls links-only/*.md 2>/dev/null | xargs -I {} basename {} .md > /tmp/article_ids.txt

# 6) X Articles çek (~3-5 dk; rate limit'e takılırsa 15 dk bekleyip retry)
node fetch_articles.mjs --file /tmp/article_ids.txt x_articles_raw
# Rate limit hatası (429) alırsa:
#   sleep 900
#   node fetch_articles.mjs --file /tmp/article_ids.txt x_articles_raw

# 7) Article'ları parse + reclassify (~30 sn)
uv run --no-project python parse_articles.py

# 8) Kompakt zip + Telegram
cd ~/Projects/x-analyst-tracker/out
zip -qr downloads/bookmarks_v$(date +%Y%m%d).zip bookmarks_download/ \
    -x "*.jpg" "*.jpeg" "*.png" "*.gif" "*.mp4" "*.mov" "*.webp" "*.webm" \
    -x "*.html" "*/raw/*" "*/logs/*" "*/x_articles_raw/*" "*.py" "*.mjs"
```

## 7. Ortam gereksinimleri

| Bileşen | Nasıl kurulur | Neden |
|---|---|---|
| Chrome + "Profile 2" profili | Zaten mevcut, X'e giriş yapmış olmalı | Cookie extraction (auth_token, ct0) |
| Node.js 22+ | `brew install node` | fetch_articles.mjs (top-level await + dynamic import) |
| jawond-bird build | `cd jawond-bird && npm install && npm run build` | Cookie extraction fonksiyonu |
| Python 3.12 + uv | Zaten mevcut | Pipeline scriptleri |
| LM Studio + Qwen 3.6-35B | Zaten mevcut, port 1234 açık | LLM fallback kategorizasyonu |
| Internet | — | Twitter API'ler + harici makale fetch |

**Bağımlılık paketleri:**
- Python: `httpx` (uv `--with httpx` ile inline install ediliyor; ayrı venv gerektirmez)
- Node: yalnız stdlib (fetch, fs, path) + jawond-bird'ün kendi modülleri

## 8. Kritik öğrenilen dersler

### 8.1 Twitter API katmanları — hangisi ne verir

| API | Auth? | Neyi verir? | Neyi vermez? |
|---|---|---|---|
| `cdn.syndication.twimg.com/tweet-result` | Hayır | Tweet + medya URL'leri + note_tweet + quote | X Articles (404) |
| bird `bookmarks` (GraphQL) | Evet (cookie) | id + text + author + metrikler | Medya URL'leri, resolved link'ler, article body |
| bird `read` (TweetDetail) | Evet | Bookmarks + genişletilmiş metadata | Article body (bird `withArticlePlainText: false` yapıyor) |
| TweetDetail + `withArticlePlainText: true` | Evet | **Article body** DraftJS blokları | — |

**Sonuç:** X Articles için TweetDetail + custom fieldToggle şart.

### 8.2 Twitter GraphQL query ID'leri kırılgan
- `TweetDetail: nBS-WpgA6ZG0CyNHD517JQ` — 2026-07-06'ya kadar geçerli
- Twitter query ID'lerini periyodik değiştirir (mobile app releaselerinde)
- **Kırılırsa:** X'te bir article'ı elle aç → DevTools → Network → GraphQL
  istekleri arasında `TweetDetail`'i bul → URL'deki hash'i al →
  `fetch_articles.mjs` `QID` değişkenine yaz.
- Alternatif: jawond-bird'ün `src/lib/twitter-client.ts` line ~17'sini oku
  (bird her upgrade'de günceller).

### 8.3 Rate limit gerçekleri
- **TweetDetail:** ~140 istek / 15 dk pencere. 400 ms rate ile ~40 sn/60 istek.
- **429 sonrası:** 15 dk bekle → **tam retry başarılı** (tetiklenmiş kullanıcı
  ban değil, geçici throttle).
- Bookmark endpoint: cursor-based, tek call tüm 724'ü verir (sorun yok).
- Syndication API: yakalanmadım, teoride limitsiz ama respectful ol.

### 8.4 Feature flag'lar
- `withArticlePlainText: true` şart (article body için)
- `withArticleSummaryText: true` faydalı (preview text)
- `articles_preview_enabled: true` — TWEET_FEATURES içinde, article kartlarının
  görünmesi için
- `longform_notetweets_consumption_enabled: true` — normal note tweet'ler için

### 8.5 Chrome cookie extraction Mac özgü
- Path: `~/Library/Application Support/Google/Chrome/Profile 2/Cookies`
- SQLite şifreli (Chrome Safe Storage kullanıyor — macOS keychain)
- jawond-bird bunu abstrakt eder; **manuel** yapmaya çalışma.
- **Profile adı kritik:** Operatör'ün X'e giriş yaptığı profil "Profile 2".
  Default profil "Default"; farklıysa `CHROME_PROFILE` env değişkeniyle
  override edilir.

### 8.6 DraftJS parsing (X Article format)
X Article'ları [Facebook Draft.js](https://draftjs.org/) content_state
formatında yollar. `blocks[]` array'i, her block:
```json
{
  "text": "...",
  "type": "unstyled|header-1|header-2|unordered-list-item|ordered-list-item|blockquote|code-block",
  "entityRanges": [],
  "inlineStyleRanges": [{"offset": N, "length": M, "style": "BOLD|ITALIC|..."}],
  "key": "..."
}
```
- Nested list'ler: `depth` field'i var
- Link'ler: `entityRanges` içinde entity map'e referans (metadata'da)
- Bizim parser inline style'ları düz metne çeviriyor (bold/italic marker YOK)
  — tam faithful render için gelecekte geliştirilebilir.

### 8.7 Kategorize kalitesi — misc yüksek
Final: 302 bookmark hâlâ `misc/`. Nedenleri:
- Kısa/ambiguous tweet'ler (5-15 kelime, hiçbir kategori keyword'ü tetiklemez)
- Retweet başlıkları (context kaybı)
- Türkçe/İngilizce karışık, keyword'lerimiz İngilizce-ağırlıklı
- **İyileştirme fırsatı:** LM Studio'da Qwen 30B fine-tune veya few-shot prompt
  ile misc'i %60-70 daraltmak mümkün. Bu turda yapılmadı (yeter olarak kabul).

## 9. Bilinen sınırlamalar

1. **X Articles fetch cookie'ye bağımlı** — X'ten çıkış yaparsan çalışmaz.
   Yeniden giriş yeterli (Chrome kapalıyken bile cookie DB güncel).
2. **Twitter query ID'leri değişebilir** — 6-12 ayda bir bird'ü güncelle.
3. **Auth-gated harici link'ler** (Google Docs, Notion) çekilemedi — 1 tespit.
   Playwright ile authenticated fetch mümkün; şu an yapılmadı.
4. **Video dosyaları büyük** (bazıları 100+ MB) — disk 19 GB dedi. VPS'e alma
   istersen ayrı düşün (S3 gibi).
5. **Reclassify yalnız links-only'den kaynak alır** — misc'te hâlâ kategorize
   edilebilir bookmark'lar olabilir; bir ikinci-pass reclassify eklenebilir.
6. **11 links-only kaldı** — `fetch_articles.mjs` retry'da başarılı olsa da
   parse aşamasında content_state'i olmayan article'lar (draft/silinmiş?)
   olabilir.

## 10. İleride yapılabilecekler (gap-fill fırsatları)

### 10.1 Yeni bookmark artırımı (delta)
- `raw/bookmarks_20260708.json`'daki ID'leri set olarak tut
- Yeni `bird bookmarks --json --all` çıkışıyla diff al
- Yalnız yeni ID'ler için pipeline'ı koş
- **Hazır kod yok — 30 dk iş**

### 10.2 misc daraltma (LLM re-pass)
- 302 misc bookmark için ikinci LLM pass:
  - Daha uzun context (tam text + resolved link + preview)
  - Chain-of-thought prompt
  - Muhtemelen %40-50'sini kategorize eder
- Gerekli değişiklik: `process_fast.py`'de `--rescore-misc` flag

### 10.3 Twitter video download iyileştirme
- Şu an syndication API `mediaDetails.video_info.variants` en yüksek bitrate
  mp4'ünü indiriyor
- Bazı video'lar HLS-only (m3u8) — atlanıyor
- ffmpeg + yt-dlp ile HLS → mp4 birleştirme yapılabilir

### 10.4 Full-text search UI
- Yaklaşık 3+ MB text içerik var (tweet + article body + README + blog HTML)
- Simple text search: `grep -r "<terim>" ~/Projects/x-analyst-tracker/out/bookmarks_download/`
- Zenginleştirme: `rg` (ripgrep) + fzf → 5 dk iş
- SQLite FTS5 tablosu → 30 dk iş
- pgvector embedding → hafta sonu iş

### 10.5 Duplicate detection
- Aynı X Article'ı farklı 2 tweet bookmark edilmişse → 2 kez indirilmez
  (sidecar-skip) ama iki .md ayrı klasörde durur
- SHA256 hash-based dedupe eklenebilir

### 10.6 Kategori taxonomisi genişletme
- Şu an 15 kategori (misc hariç)
- "photography", "design", "hardware", "science-general" gibi eksik olanlar
- Operatör'ün bookmark örüntüsünden çıkarılabilir (Qwen'e sor)

## 11. Sorun giderme

**Q: `Cookie extraction failed`**
- A: Chrome açık olmasa da Cookies DB kilitli olabilir. `pgrep -f Chrome`
  ile kontrol; süreç varsa uyku moduna al ya da tamamen kapat.
- A: Profil adı yanlış olabilir. `ls ~/Library/Application\ Support/Google/Chrome/`
  ile listele.

**Q: `HTTP 429 Rate limit exceeded`**
- A: 15 dk bekle → yeniden koş. Idempotent; mevcut `.json`'lar skip edilir.
- A: Batch'i 100'e böl, aralarında 60 sn sleep ekle.

**Q: Article `no_article`**
- A: Bookmark ID article ID değil olabilir — bookmark bir Article'ı **quote**
  ediyorsa, embedded ID başka. `x.com/i/article/<ID>` içindeki gerçek ID kullan
  (script `get_article_id` fonksiyonu bunu yapıyor — hata var mı bak).

**Q: Article body boş**
- A: `withArticlePlainText: true` **kesin** olmalı. `fetch_articles.mjs`
  içinde default `false` olduğunda body gelmiyor.

**Q: LM Studio bağlantısı yok**
- A: `curl http://localhost:1234/v1/models` — dönmüyorsa LM Studio'yu manuel aç.
- A: Alternatif: `LLM_URL` env değişkeniyle başka endpoint (Ollama, agy) yönlendir.

**Q: Telegram göndermede `chat_id is empty`**
- A: `.env` yerine tam yol kullan: `~/Projects/ChainWise/repo/.env`
- A: `TELEGRAM_OPERATOR_CHAT_ID` (uzun ad) kullan, `OPERATOR_CHAT_ID` DEĞİL.

## 12. Dosya adlandırma & metadata

- **Bookmark .md**: `<tweet_id>.md`
- **Medya**: `_media/<tweet_id>/<orijinal_dosya_adı>` (twitter'ın verdiği isim)
- **Harici makale**: `_articles/<domain>_<path_slug>.html` (max 100 char)
- **GitHub README**: `_articles/<domain>_<path>.README.md`
- **Article raw**: `x_articles_raw/<tweet_id>.json`

**Bookmark markdown'ının yapısı:**
```markdown
# @<username> — <full_name>

**Tarih:** <ISO tarih>
**URL:** https://x.com/<username>/status/<id>
**Metrikler:** ❤️<like> / 🔁<retweet> / 💬<reply>

## İçerik

<tweet text>

## Linkler

- <resolved_url_1>
- <resolved_url_2>

## Medya

- ![](_media/<id>/photo1.jpg)
- ![](_media/<id>/video1.mp4)

## Article İçeriği

### <article title>

<article body — DraftJS'ten markdown'a çevrilmiş>
```

## 13. Devir kontrol listesi (yeni agent için)

Bir sonraki oturumda devralırken kontrol et:

- [ ] `HANDOFF.md` (bu doküman) okundu
- [ ] `~/Projects/x-analyst-tracker/out/bookmarks_download/` yapısı doğrulandı
- [ ] `raw/bookmarks_20260708.json` mevcut (724 kayıt)
- [ ] `x_articles_raw/*.json` 207 dosya
- [ ] Chrome "Profile 2" X'te giriş yapmış
- [ ] LM Studio Qwen 3.6-35B ile ayakta
- [ ] Kategoriler yaklaşık dağılım eşleşiyor (misc ~302, claude-optimization ~175)
- [ ] `fetch_articles.mjs --id <örnek>` çalışıyor (cookie hâlâ geçerli)
- [ ] Yeni bookmark artırımı gerekiyorsa Adım 10.1 planı hazır

## 14. Referans dosyaları (dışarıdan)

- `~/Projects/x-analyst-tracker/README.md` — proje geneli
- `~/Projects/x-analyst-tracker/jawond-bird/README.md` — bird CLI
- `~/Projects/x-analyst-tracker/jawond-bird/src/lib/twitter-client.ts`
  — GraphQL query ID'leri, feature flag'ları
- `~/Projects/x-analyst-tracker/jawond-bird/src/lib/cookies.ts`
  — Chrome cookie extraction implementation
- `~/Projects/ChainWise/repo/.env` — Telegram token + operator chat ID

---

**Doküman sonu.** Yeni bir agent bu dokümanı okuduktan sonra 5 dk'da devralabilir.
Belirsizlik varsa kod inline yorumlarına ya da git log'una bak.

---

## EK NOT (kalıcı konum)

Bu scriptler `scripts/bookmarks/` altında version-controlled (x-analyst-tracker repo,
private GitHub remote). Çalışma verisi ve çıktılar `out/bookmarks_download/` altında
(gitignore — 19GB medya). Yeniden koşarken scriptleri `out/bookmarks_download/`'a
kopyala ya da oradan çalıştır (path'ler ROOT = script dizini varsayar).
