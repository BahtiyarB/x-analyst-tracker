# x-analyst-tracker — Proje Dokümanı (kapsamlı)

> Bu araç **ChainWise'dan bağımsız** çalışır. Tek ChainWise bağı `bridge_to_chainwise.py`
> ve o da opsiyonel/eklenti — silinirse geri kalan her şey (X'ten tweet/liste/bookmark
> çekme) aynen çalışır. Bu doküman aracın NE olduğunu, nasıl kurulduğunu, nasıl
> çalıştığını, neden bu tasarım seçildiğini ve nasıl taşınacağını anlatır.
> Geliştirmeye devam / başka dile port için: `docs/HANDOFF.md`.

---

## 1. Ne işe yarar

Kripto analistlerinin (ve herhangi bir X hesabının/listesinin) tweetlerini **resmi API
olmadan, tarayıcı oturum çerezi ile** çekip JSON olarak verir. Amaç: takip edilen
analistlerin paylaşımlarını toplu/derin çekip aşağı-akış işleme (sinyal çıkarımı, arşiv,
analiz) beslemek.

**Neden API değil:** X resmi API'si pahalı ve kısıtlı. Bu araç X'in web arayüzünün
kullandığı **iç GraphQL endpoint'lerini** senin login oturumunla çağırır — ücretsiz.

**Ne verir (komutlar):**
- `user-tweets <handle>` — bir kullanıcının tweetleri (cursor pagination ile derin geçmiş)
- `list-tweets <id>` / `my-lists` — X listelerinin akışı / kendi listelerin
- `bookmarks` — kendi kaydettiğin tweetler
- `user-articles <handle>` — bir kullanıcının X long-form Articles'ı
- `search <query>` — Gmail-benzeri arama (`from:`, `since:` vb.)
- `read` / `replies` / `thread` — tek tweet / yanıtlar / konuşma
- `whoami` / `check` — oturum doğrulama
- (`tweet` / `reply` yazma komutları da var ama bu proje OKUMA odaklı; yazma query-id'leri
  doğrulanmadı)

Tüm okuma komutları `--json` destekler.

---

## 2. Mimari

```
x-analyst-tracker/
├── jawond-bird/          # X/Twitter CLI (TypeScript) — ÇEKİRDEK
│   ├── src/
│   │   ├── index.ts              # komut tanımları (commander)
│   │   └── lib/
│   │       ├── twitter-client.ts # GraphQL istemci: query-id + feature + toggle + parse
│   │       ├── query-ids.json    # X operation query-id'leri (bundle'dan)
│   │       ├── x-features.json    # feature/toggle setleri (bundle'dan, refresh çıktısı)
│   │       ├── cookies.ts        # Chrome/Firefox profilinden çerez okuma
│   │       └── sweetistics-client.ts # alternatif ücretli backend (kullanılmıyor)
│   └── scripts/
│       ├── refresh-x-metadata.mjs # X bundle'ından query-id+feature+toggle tazeler ⭐
│       └── update-query-ids.ts    # eski/kırık query-id tazeleyici (kullanma)
├── enc0der-bird/          # REFERANS klon (user-tweets/lists lib'i var ama CLI kırık)
├── analysts.yaml          # takip edilen analistler (handle + lang + focus)
├── fetch_analysts.sh      # analysts.yaml'ı okuyup her handle'ı çekip out/'a yazar
├── bridge_to_chainwise.py # OPSİYONEL: out/ JSON → ChainWise ingest_articles
├── out/                   # çekilen tweet/liste/bookmark JSON'ları (gitignore)
└── docs/                  # bu doküman + HANDOFF
```

**Veri akışı:**
```
Chrome (login çerezi) → jawond-bird (GraphQL) → JSON (stdout/out/) → [opsiyonel bridge] → ChainWise
```

---

## 3. Kimlik doğrulama (kritik)

**Loginsiz okuma İMKÂNSIZ** — X guest-token erişimini kapattı (2023). Tek yol: login
oturum çerezi (`auth_token` 40-hex + `ct0` csrf).

**Çerez nasıl geliyor:** jawond-bird, Chrome/Firefox profilindeki çerez veritabanını
okur (macOS'ta Keychain'den şifre çözer). Yani: **o tarayıcı profilinde x.com'a login
olman yeterli**, elle çerez girmene gerek yok.
```bash
node dist/index.js check --chrome-profile "Profile 2"   # oturumu doğrula
```
Alternatif: `--auth-token <x> --ct0 <y>` veya `AUTH_TOKEN`/`CT0` env var (DevTools →
Application → Cookies → x.com'dan alınır).

**Güvenlik:** çerez oturum kimliğidir. Ayrı/burner X hesabı kullanmak daha güvenli.

**Rate limit:** X hız sınırı kullanıcı/IP bazlı. Derin çekimlerde (yüzlerce tweet) HTTP
429 gelir; araç sayfalar arası 1.5s bekler, ama analistler arası birkaç dakika soğuma
gerekebilir (yaşandı: ~400 tweet sonra 429).

---

## 4. Kurulum (bu makinede / yeniden)

Gereksinim: **Node ≥ 22** (mevcut: v25.8.2), npm veya pnpm.

```bash
cd jawond-bird
npm install          # veya: corepack enable && pnpm install
npm run build        # tsc → dist/
node dist/index.js --help
```

`bridge_to_chainwise.py` için: Python 3.12 + ChainWise repo'su (sadece bridge kullanılacaksa).

---

## 5. Kullanım örnekleri

```bash
cd jawond-bird
P="--chrome-profile Profile 2"   # kendi profilin

# Tek analist, derin geçmiş
node dist/index.js user-tweets KardesBaris --all --max 400 --json $P > ../out/kb.json

# Bir listenin akışı (önce my-lists ile id bul)
node dist/index.js my-lists --json $P
node dist/index.js list-tweets 1488441864923582468 --all --max 500 --json $P > ../out/list.json

# Toplu: analysts.yaml'daki herkesi çek
cd .. && CHROME_PROFILE="Profile 2" ./fetch_analysts.sh 20260706
```

`analysts.yaml` formatı:
```yaml
analysts:
  - handle: KardesBaris    # @ olmadan
    lang: tr
    focus: onchain
default_count: 50
```

---

## 6. X'in GraphQL'i nasıl çözüldü (implementasyonun kalbi)

X'in web GraphQL'i sürekli değişir ve unofficial client'ları kırar. Bu araç, doğru
metadata'yı **X'in kendi JS bundle'ından çıkararak** ayakta kalır — tahminle değil.

**refresh-x-metadata.mjs** (X değişince ÇALIŞTIR):
1. `x.com/?lang=en` HTML'inden `abs.twimg.com/.../main.*.js` bundle URL'ini bulur.
2. Bundle'ı indirir, her operation'ın `{queryId, operationName, featureSwitches[],
   fieldToggles[]}` bloğunu regex'le çıkarır.
3. `query-ids.json` + `x-features.json`'a yazar.

Her X GraphQL isteği üç parça ister: **query-id** (operation kimliği), **features**
(39 zorunlu flag), **fieldToggles** (8 flag). Üçü de bundle'da tanımlı.

> Detaylı teknik reçete + 2026 kırılmaları + status-kodu teşhisi:
> `~/.claude/skills/x-graphql-recovery/SKILL.md` (Claude Code skill'i) ve HANDOFF.md §Port.

---

## 7. Öğrenilen dersler (bu araç geliştirilirken)

1. **steipete/bird kaldırıldı** (404). En olgun çalışan klon **jawond/bird** (130⭐).
   enc0der-bird referans tutuldu (user-tweets/lists lib'i var ama CLI importu kırık).
2. **X 2026 kırılmaları** (hepsi bundle-extraction ile çözüldü):
   - query-id'ler değişti + jawond'un `graphql:update`'i regex ile YANLIŞ eşleştirmişti
   - featureSwitches 24→39, fieldToggles (8) artık zorunlu → 422 GRAPHQL_VALIDATION_FAILED
   - SearchTimeline GET→**POST** oldu → 404
   - screen_name/name `legacy`→`core` taşındı → "not found in response" (HTTP 200 ama parse patlar)
   - ListOwnerships gizli `isListMemberTargetUserId` variable ister
   - BookmarkSearchTimeline boş rawQuery reddeder → taftoloji `-filter:replies OR filter:replies`
3. **Şemayı gerçek yanıtla kilitle.** Parser'ı varsayımla yazıp göndermek = sessiz kırılma.
   Geçici raw-dump enjekte et, bir kez canlı çalıştır, şemayı sabitle, dump'ı sil.
4. **Cursor pagination:** timeline'ın son entry'si `TimelineTimelineCursor` (cursorType
   "Bottom"), value bir sonraki sayfanın cursor'ı. Tweet entry'lerini cursor'dan ayır.
5. **Bookmark ≠ analiz kaynağı.** 500 bookmark'ın 320 farklı yazardan, çoğu kripto-dışı
   (AI/dev). Küratörlü sanılan içerik genel ilgi arşivi çıktı → sinyal hattına sokma.
6. **Liste = çoğunlukla bot.** Crypto-Onchain listesinin %68'i whale_alert botu. Değerli
   olan gerçek-analist alt kümesi; veri-feed'leri (whale_alert/arkham/vb.) ayır.
7. **dist/ git'te yok** (build artifact) → yeni makinede `npm run build` şart.

---

## 8. Başka makineye taşıma

```bash
# 1. Repoyu kopyala/klonla (out/ ve node_modules taşınmaz — .gitignore'da)
git clone <repo-url> x-analyst-tracker   # veya rsync ile klasörü kopyala

# 2. Node ≥22 kur, sonra:
cd x-analyst-tracker/jawond-bird && npm install && npm run build

# 3. O makinedeki Chrome'da x.com'a login ol, profil adını bul:
ls ~/Library/Application\ Support/Google/Chrome/   # "Default", "Profile 1"...
node dist/index.js check --chrome-profile "<profil>"

# 4. Çalıştır
node dist/index.js user-tweets <handle> --json --chrome-profile "<profil>"
```
Linux/Windows'ta çerez okuma yolu farklı (jawond cross-platform çerez okumayı destekler;
gerekirse `--auth-token`/`--ct0` ile manuel ver).

**ChainWise'sız kullanım:** `bridge_to_chainwise.py`'yi görmezden gel. `out/*.json`
dosyaları standart tweet dizisi (`[{id,text,createdAt,author:{username,name},...}]`) —
kendi işleme hattına doğrudan besleyebilirsin.

---

## 9. Mevcut durum (2026-07-06)

- Çalışan komutlar: 13 (user-tweets, list-tweets, my-lists, bookmarks, user-articles,
  search, read, replies, thread, mentions, whoami, check, + tweet/reply).
- 11 GraphQL operation query-id'si bundle'dan doğrulandı.
- Canlı test edildi: 8+ analist + Crypto-Onchain listesi + bookmarks çekildi.
- `bridge_to_chainwise.py` → ChainWise'a 310 sinyal besledi (opsiyonel entegrasyon).
- Tek git repo, remote yok (yerel). Commit geçmişi temiz (bkz. `git log`).

**Bilinen sınırlar / açık işler:** HANDOFF.md §Roadmap.
