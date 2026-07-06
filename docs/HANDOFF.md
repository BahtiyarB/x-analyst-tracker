# x-analyst-tracker — Geliştirme Handoff & Port Rehberi

> Bu doküman, **başka bir ajanın/geliştiricinin** aracı kaldığı yerden geliştirmesi
> veya başka bir dile (Go, Rust, Python) port etmesi için gereken HER ŞEYİ içerir.
> Önce `docs/PROJECT.md` (aracın ne olduğu) okunmalı. Bu doküman "nasıl devam edilir"e odaklanır.

---

## 0. 30 saniyede durum

- Çalışan bir X/Twitter okuma CLI'ı var (TypeScript, `jawond-bird/`), cookie-auth,
  X'in iç GraphQL'ini kullanır. 13 komut, 11 operation, canlı doğrulanmış.
- X sürekli değişir; ayakta kalma mekanizması: `refresh-x-metadata.mjs` (bundle'dan
  metadata çıkarır). Kırıldığında ilk yapılacak bu.
- Kod temiz commit'li, `npm run build` yeşil. Test: `node dist/index.js check --chrome-profile <p>`.

---

## 1. Kod haritası (nereye bakılır)

| Dosya | Sorumluluk |
|---|---|
| `jawond-bird/src/index.ts` | Komut tanımları (commander). Yeni komut buraya. |
| `jawond-bird/src/lib/twitter-client.ts` | **Kalp.** GraphQL istekleri: query-id + features + toggles + response parse. Yeni operation metodu buraya. |
| `jawond-bird/src/lib/query-ids.json` | 11 operation'ın query-id'si (bundle'dan) |
| `jawond-bird/src/lib/x-features.json` | feature/toggle setleri (refresh çıktısı) |
| `jawond-bird/src/lib/cookies.ts` | Chrome/Firefox çerez okuma |
| `jawond-bird/scripts/refresh-x-metadata.mjs` | X bundle'ından metadata tazeleyici ⭐ |
| `enc0der-bird/` | Referans klon — yeni operation eklerken lib'ine bak (user-tweets/lists/media var) |

`twitter-client.ts`'teki sabitler (kritik):
- `QUERY_IDS` (query-ids.json'dan yüklenir + FALLBACK)
- `TWEET_FEATURES` (39 flag) — tweet-listeleyen op'lar için
- `TWEET_FIELD_TOGGLES` (8 flag)
- `USER_BY_SCREEN_NAME_FEATURES` (13 flag) — profil op'u için

---

## 2. Yeni bir X operation eklemek (adım adım)

Örn. "bir kullanıcının takipçileri" (`Followers`) eklemek istersen:

1. **Metadata'yı bundle'dan çıkar:**
   ```bash
   curl -s "https://x.com/?lang=en" -H "User-Agent: Mozilla/5.0" \
     | grep -oE "main\.[a-f0-9]+\.js" | head -1   # bundle adı
   curl -s "https://abs.twimg.com/responsive-web/client-web/main.<hash>.js" -o /tmp/x.js
   python3 -c "
   import re; s=open('/tmp/x.js').read()
   m=re.search(r'queryId:\"([^\"]+)\",operationName:\"Followers\"(.{0,2600}?featureSwitches:\[(.*?)\])',s)
   print(m.group(1)); print(re.findall(r'\"([^\"]+)\"',m.group(3)))"
   ```
2. `query-ids.json` + FALLBACK_QUERY_IDS'e query-id ekle.
3. `twitter-client.ts`'e `getFollowers(userId, cursor?)` metodu — mevcut `getUserTweets`
   desenini kopyala (features, cursor pagination, response parse).
4. **Response şemasını CANLI yakala** (varsayma): metoda geçici
   `require('node:fs').writeFileSync('/tmp/raw.json', await response.clone().text())`
   ekle, bir kez çalıştır, `/tmp/raw.json`'dan gerçek path'i oku, parse'ı kodla, dump'ı sil.
5. `index.ts`'e komut ekle. `npm run build`. Canlı test.

**GET mi POST mu?** Çoğu op GET+querystring. SearchTimeline POST+JSON body. Yeni op 404
veriyorsa POST dene.

---

## 3. Kırıldığında onarım akışı (status koduna göre)

- **404** → query-id yanlış/eskimiş VEYA op POST'a geçmiş. Önce `refresh-x-metadata.mjs`
  çalıştır + `npm run build`. Hâlâ 404 ise GET→POST dene.
- **422 GRAPHQL_VALIDATION_FAILED** → eksik feature/toggle veya eksik variable. Bundle'dan
  featureSwitches/fieldToggles'ı tazele. 422 hangi alanın eksik olduğunu SÖYLEMEZ (400 söyler).
- **HTTP 200 ama "not found in response"** → response şeması değişti. Ham 200'ü yakala,
  parse path'ini güncelle. (2026'da screen_name legacy→core taşındı.)
- **401/403** → çerez geçersiz/expired. `check` ile doğrula, tarayıcıda yeniden login.
- **429** → rate limit. Bekle (dakikalar), sayfa arası gecikmeyi artır.

Bu reçetenin tam hali: Claude Code skill `x-graphql-recovery` (repoda
`../ChainWise/repo/docs/skills/x-graphql-recovery.SKILL.md` yedeği de var).

---

## 4. Roadmap / açık işler (öncelik sırasıyla)

1. **Yazma op'larını doğrula** (opsiyonel): CreateTweet/CreateRetweet query-id'leri
   bundle'dan geldi ama CANLI test edilmedi (proje okuma-odaklı). Yazma gerekirse doğrula.
2. **Periyodik çekme:** şu an manuel/fetch_analysts.sh. Cron/launchd ile günlük otomatik
   çekim + rate-limit-farkında sıralama (analistler arası soğuma). ChainWise'ın
   `docs/skills` altındaki launchd kalıbına bakılabilir.
3. **Incremental/dedup:** her çekimde tüm geçmiş yerine "son çekimden beri" (since_id).
   `out/` yerine küçük bir state (son görülen tweet id/analist).
4. **UserTweetsAndReplies:** şu an user-tweets replies'i içermez. Reply-yoğun analistler
   için ayrı op (bundle'da mevcut).
5. **Media/görsel:** tweet'lerdeki grafik görselleri (analistlerin chart'ları) — X media
   URL'leri response'ta var, indirilebilir. On-chain grafik analizi için değerli olabilir.
6. **Cross-platform çerez:** Linux/Windows çerez okuma test edilmedi (macOS'ta çalışıyor).

---

## 5. Başka dile PORT (Go / Rust / Python)

Aracın **taşınabilir çekirdeği dile bağlı değil** — X GraphQL protokolüdür. Port ederken
TypeScript'e özgü hiçbir şey yok; gereken tüm bilgi bu repoda veri olarak duruyor.

**Portun ihtiyaç duyduğu 5 şey (hepsi mevcut):**
1. **query-ids** → `jawond-bird/src/lib/query-ids.json` (11 operation). Doğrudan kopyala.
2. **feature/toggle setleri** → `jawond-bird/src/lib/x-features.json` (+ twitter-client.ts'teki
   TWEET_FEATURES/TWEET_FIELD_TOGGLES/USER_BY_SCREEN_NAME_FEATURES sabitleri).
3. **İstek şekli** → her op için: `GET https://x.com/i/api/graphql/{queryId}/{OpName}?
   variables={...}&features={...}&fieldToggles={...}` (SearchTimeline POST+body).
   Header'lar (twitter-client.ts `getHeaders()`'ten):
   - `authorization: Bearer AAAAAAA...` (X'in sabit public web bearer'ı — bundle'da/koddadır)
   - `x-csrf-token: <ct0>`, `x-twitter-auth-type: OAuth2Session`, `x-twitter-active-user: yes`
   - `cookie: auth_token=<>; ct0=<>`, sahte Chrome `user-agent`, `origin/referer: https://x.com`
4. **Response parse path'leri** → twitter-client.ts'teki parse fonksiyonları. Ana yol:
   `data.<op-özel>.timeline.timeline.instructions[] → TimelineAddEntries → entries[].content.
   itemContent.tweet_results.result` (legacy.full_text, core.screen_name). Cursor:
   `TimelineTimelineCursor` entry, cursorType "Bottom".
5. **Çerez okuma** → dile göre: Go/Rust'ta Chrome çerez DB'sini (SQLite + macOS Keychain
   AES çözme) okuyan kütüphaneler var (ör. Go: `kooky`, Rust: `rookie`). VEYA en basit:
   çerezi env/arg ile ver, tarayıcı okumayı atla.

**Önerilen port stratejisi:**
- **Go:** hızlı, tek binary, `net/http` + `encoding/json` yeter. Çerez için `kooky`.
  Concurrency ile paralel analist çekimi kolay. Rate-limit için token-bucket.
- **Rust:** `reqwest` + `serde_json`. En performanslı; enc0der-bird zaten benzer yapıda
  değil ama X protokolü aynı. `rookie` çerez için.
- **Python:** en hızlı prototip; `httpx` + stdlib. `browser_cookie3` çerez için. (twscrape
  gibi olgun Python X-scraper'ları referans alınabilir — feature setleri onlarda da güncel.)

**Port'ta KRİTİK:** query-id/feature/toggle'ları HARDCODE ETME — `refresh-x-metadata.mjs`
mantığını da porta taşı (veya query-ids.json/x-features.json'ı runtime'da oku). X ayda
birkaç kez değişir; bundle-extraction olmadan port birkaç haftada ölür.

**Port'ta DEĞİŞMEYECEK:** protokol (GET/POST + variables/features/toggles), header seti,
response instruction şeması, cursor mantığı, auth (cookie), rate-limit davranışı. Bunlar
X'in web client'ının davranışı — dilden bağımsız.

---

## 6. Test / doğrulama

```bash
cd jawond-bird && npm run build
node dist/index.js check --chrome-profile "<profil>"          # oturum
node dist/index.js user-tweets <handle> -n 3 --json --chrome-profile "<profil>"  # okuma
node scripts/refresh-x-metadata.mjs                            # metadata tazele (X değişince)
```
Birim test yok (araç X'e canlı bağımlı); doğrulama canlı-çağrı + göz. Port'ta parse
fonksiyonları için kaydedilmiş JSON fixture'larla birim test eklenebilir.

---

## 7. Bağımlılıklar & lisans

- jawond-bird: MIT (jawond/bird fork'u), bağımlılıklar: commander, devalue, json5, kleur.
- enc0der-bird: referans, çalıştırılmıyor.
- bridge_to_chainwise.py: ChainWise'a bağımlı (opsiyonel).
- Etik/yasal: X ToS'u unofficial API kullanımını kısıtlar; kişisel/düşük-hacim kullanım
  için düşük risk ama sıfır değil. Burner hesap + makul hız önerilir.
