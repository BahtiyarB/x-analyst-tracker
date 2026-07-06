# x-analyst-tracker

Kripto analistlerinin X (Twitter) hesaplarindan tweet toplayip
sinyal-siniflama (signal classification) icin yapilandirilmis JSON'a
ceviren, kendi basina calisabilen bir arac. ChainWise'in metin-sinyal
hattina (`prompts/extract_text.md`, `ingest_articles` tablosu) opsiyonel
bir kopru (`bridge_to_chainwise.py`) uzerinden besleme yapar, ama bu repo
ChainWise'dan bagimsiz kullanilabilir.

## Icindekiler

- [Ne ise yarar](#ne-ise-yarar)
- [Neden bird tabanli / hangi klon secildi](#neden-bird-tabanli--hangi-klon-secildi)
- [Kurulum](#kurulum)
- [Auth (kimlik dogrulama)](#auth-kimlik-dogrulama)
- [Kullanim](#kullanim)
- [X kirilganligi ve onarim](#x-kirilganligi-ve-onarim)
- [ChainWise entegrasyonu](#chainwise-entegrasyonu)
- [Ayri proje olarak kullanim](#ayri-proje-olarak-kullanim)
- [Dizin yapisi](#dizin-yapisi)

## Ne ise yarar

Bu proje su akisi otomatiklestirir (calisir durumda, uctan uca canli
dogrulandi):

1. `analysts.yaml` icinde takip edilecek kripto analistlerinin X handle'lari
   tanimlanir (onchain analistler, TR/EN karisik olabilir).
2. `fetch_analysts.sh`, her analist icin `bird user-tweets <handle>` komutunu
   calistirip son N tweet'i JSON olarak `out/` klasorune yazar. Cookie,
   Chrome "Profile 2" profilinden otomatik okunur (`--chrome-profile`).
3. `bridge_to_chainwise.py` (opsiyonel), bu JSON dosyalarini okuyup her
   tweet'i normalize eder (id, handle, created_at, text, url, is_retweet) ve
   ChainWise'in `ingest_articles` tablosuna yazar — boylece ChainWise'in
   mevcut metin sinyal cikarma hatti (bkz. asagida) tweetleri de bir "makale"
   gibi isleyip trade sinyaline (entry/exit/outlook/level_watch) cevirebilir.
   Retweet'ler `--skip-retweets` ile atlanabilir (retweet bir analist gorusu
   degildir).

Amac: analistlerin acik/kapali pozisyon cagrilarini, seviye takiplerini ve
piyasa yorumlarini elle takip etmek yerine otomatik toplayip yapilandirmak.

## Neden bird tabanli / hangi klon secildi

Bu depo iki `bird` (X/Twitter CLI) klonunun karsilastirilmasindan sonra
olusturuldu:

- **jawond-bird** (SECILEN, bu repoda `jawond-bird/` altinda) — calisir
  durumda, `npm run build` sorunsuz `dist/` uretiyor, komut seti tam
  (tweet/reply/read/replies/thread/search/mentions/whoami/check).
  Cookie tabanli GraphQL auth veya Sweetistics API key ile calisiyor.
  Bu, 100+ fork'lu bir `bird` ekosisteminin en olgun/en fazla fork'a sahip
  hattindan geliyor ve `npm install && npm run build` sonrasi dogrudan
  calistigi dogrulandi (`node dist/index.js --help`).
- **enc0der-bird** (REFERANS, `enc0der-bird/` altinda) — `user-tweets`,
  `timelines`, `lists` gibi ek kutuphaneler icerdigi icin referans olarak
  tutuluyor, ama CLI importu kirik (dogrudan calistirilamiyor). Ileride
  jawond-bird'e ozellik tasima (timeline/list okuma gibi) icin bakilabilir.
- **steipete/bird** — bu proje icin degerlendirilip **kaldirildi**. Bu isim,
  ayni "bird" ekosisteminin 104-fork'lu bir baska klonuna (upstream/origin
  hatti) isaret ediyordu; jawond-bird zaten ayni fonksiyonlari saglayip
  derlemesi sorunsuz oldugu icin ayrica tutulmadi.

Sonuc: **jawond-bird** bu projenin CLI temeli olarak kullanilir
(`jawond-bird/dist/index.js`), enc0der-bird sadece referans/inceleme
amacli depoda kalir.

## Kurulum

Gereksinim: Node.js >= 22 (jawond-bird `engines.node` alaninda `>=20`
yaziyor olsa da, guncel X GraphQL semasiyla test edilen surum >=22'dir).

```bash
cd jawond-bird
npm install
npm run build
```

Basari kontrolu:

```bash
node dist/index.js --help
```

Bu komut calisirsa (versiyon, komut listesi vb. basarsa) kurulum tamamdir.
**Not:** `--help` cikisi icin X'e agla istegi atilmaz, cookie/auth GEREKMEZ.

## Auth (kimlik dogrulama)

**Onemli:** Login'siz kullanim MUMKUN DEGIL. X, misafir (guest) token ile
okuma erisimini kapatti; bu yuzden `search`/`read`/`replies` gibi komutlar
bile gecerli bir X hesabina baglı cookie ya da ucretli bir ucuncu-taraf API
(Sweetistics) gerektirir.

### (a) Browser cookie (auth_token + ct0) — onerilen, ucretsiz

1. Herhangi bir tarayicida (Chrome/Firefox) x.com'a normal sekilde giris
   yapin.
2. DevTools'u acin (Chrome: Cmd+Option+I) -> **Application** sekmesi ->
   **Cookies** -> `https://x.com`.
3. Iki degeri kopyalayin:
   - `auth_token` — 40 haneli hex string.
   - `ct0` — CSRF token (uzun alfanumerik string).
4. Bu degerleri ortam degiskeni olarak veya CLI argumani olarak verin:

```bash
export AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export CT0="yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
node jawond-bird/dist/index.js whoami
```

veya:

```bash
node jawond-bird/dist/index.js --auth-token "xxx" --ct0 "yyy" whoami
```

Alternatif env adlari da desteklenir: `TWITTER_AUTH_TOKEN`,
`TWITTER_CT0`.

**Otomatik tarayici cookie okuma:** jawond-bird, Chrome veya Firefox
profilinizden cookie'leri otomatik okuyabilir (macOS'ta `sqlite3` ve
`security` CLI araclarini kullanarak):

```bash
# Chrome'daki x.com cookie'lerini otomatik kullan
node jawond-bird/dist/index.js --chrome-profile Default whoami

# Firefox
node jawond-bird/dist/index.js --firefox-profile default-release whoami
```

Bu durumda `.env` veya cookie dosyasi OLUSTURMANIZA gerek yoktur; sadece
tarayicida x.com oturumunuzun acik olmasi yeterlidir. Oncelik sirasi:
CLI argumanlari > env degiskenleri > tarayici cookie'leri (Firefox varsayilan
olarak Chrome'dan once denenir, `--chrome-profile`/`--firefox-profile` ile
degistirilebilir).

**Guvenlik notu:** `auth_token` ve `ct0` degerlerini asla repo'ya, log
dosyasina veya paylasilan bir yere yazmayin. Bu repo'daki `.gitignore`
`.env`, `cookies*.json`, `*.session` desenlerini zaten disliyor.

### (b) Sweetistics API key (ucretli, ucuncu-taraf)

[Sweetistics](https://sweetistics.com), X'e dogrudan login gerektirmeyen
ucretli bir SaaS API'dir. Bir hesap/odeme gerektirir ama browser cookie
yonetimini ortadan kaldirir:

```bash
export SWEETISTICS_API_KEY="sweet-..."
node jawond-bird/dist/index.js --engine sweetistics search "from:glassnode" -n 20 --json
```

`--engine auto` verilirse, Sweetistics anahtari varsa o kullanilir, yoksa
GraphQL/cookie yoluna dusulur.

## Kullanim

Tek bir analistin son tweetlerini cekmek (ana kullanim — canli dogrulandi):

```bash
node jawond-bird/dist/index.js user-tweets glassnode -n 50 --json --chrome-profile "Profile 2"
```

Cikti KESIN sema: ust duzey JSON bir DIZI, her eleman
`{id, text, createdAt, replyCount, retweetCount, likeCount, conversationId,
author: {username, name}}` seklindedir. `createdAt` klasik Twitter/RFC2822
formatindadir (ornek: `"Thu Jul 02 19:15:02 +0000 2026"`).

(Eskiden `search "from:<handle>"` kullaniliyordu; `user-tweets` handle'a
dogrudan baglandigi icin daha saglam/guvenilir bulundu ve hem
`fetch_analysts.sh` hem yukaridaki ornek bu komuta gecirildi.)

Tum `analysts.yaml` listesini toplu cekmek:

```bash
./fetch_analysts.sh 20260706
# farkli bir Chrome profili kullanmak icin:
CHROME_PROFILE="Profile 2" ./fetch_analysts.sh 20260706
```

(Tarih argumani opsiyoneldir; verilmezse bugunun tarihi `YYYYMMDD` olarak
kullanilir.) Cikti: `out/tweets_<handle>_<tarih>.json`. Bir analist
basarisiz olursa (auth hatasi, handle degismis, rate-limit vb.) script
o hatayi loglayip diger analistlerle devam eder; hata detayi
`out/tweets_<handle>_<tarih>.err` dosyasina yazilir. Sonunda toplam/basarisiz
sayisi ozetlenir.

## X kirilganligi ve onarim

X, GraphQL sorgu ID'lerini (`query-id`) VE gerekli `featureSwitches`/
`fieldToggles` setlerini periyodik olarak degistirir; bu yuzden `user-tweets`/
`search` gibi komutlar zamanla `HTTP 404`/`422 GRAPHQL_VALIDATION_FAILED`
hatasi vermeye baslayabilir.

### 2026-07-06 gercek onarim vakasi

Bu tarihte tam olarak bu kirilma yasandi ve iki ayri sorun tespit edilip
duzeltildi:

1. **Query-id yanlis eslestirme**: Eski `npm run graphql:update`
   (`jawond-bird/scripts/update-query-ids.ts`) bundle icinde
   `operationName` <-> `queryId` ciftlerini "en yakin eslesme" mantigiyla
   regex'le buluyordu. Ancak minified bundle'da `queryId` HER ZAMAN
   `operationName`'den ONCE, ayni obje icinde gelir; "en yakin" mantigi bir
   onceki operation'in queryId'sini bir sonrakine kaydirabiliyordu. Sonuc:
   `CreateTweet` ve `CreateRetweet` query-id'leri BIRBIRINE KARISMISTI
   (CreateTweet'e aslinda CreateRetweet'in id'si atanmisti, tersi de gecerliydi).
2. **Eksik/yanlis feature setleri**: `TweetDetail`/`SearchTimeline`/
   `UserTweets` gibi okuma operationlari icin X, 2026'da 39 adet
   `featureSwitches` (grok/*, payments, premium_content, jetfuel,
   profile_label, rweb_video_screen gibi yeni bayraklar dahil) ve 8 adet
   `fieldToggles` gondermeyi zorunlu kildi; eksik/eski bir set
   `422 GRAPHQL_VALIDATION_FAILED` ile sonuclaniyordu. Ayrica `SearchTimeline`
   artik GET degil **POST** olarak cagrilmali (query-string yerine JSON body).

Bu onarim `jawond-bird/src/lib/twitter-client.ts` icindeki
`TWEET_FEATURES`/`TWEET_FIELD_TOGGLES` sabitlerine islendi (39 feature + 8
toggle) ve `SearchTimeline` cagrisi POST'a cevrildi.

### Yeni yontem: bundle-extraction (`refresh-x-metadata.mjs`)

Query-id yanlis-eslestirme sorununu kokten cozmek icin eski
`update-query-ids.ts`'in yerini `jawond-bird/scripts/refresh-x-metadata.mjs`
alir:

```bash
cd jawond-bird
node scripts/refresh-x-metadata.mjs
npm run build   # query-ids.json dist/'e yansisin diye
```

Mantik: `x.com/?lang=en` HTML'inden guncel
`abs.twimg.com/responsive-web/client-web/main.*.js` bundle URL'ini bulur,
indirir, ve her hedef operation (`CreateTweet`, `CreateRetweet`,
`FavoriteTweet`, `TweetDetail`, `SearchTimeline`, `UserTweets`,
`UserByScreenName`) icin **TAM blogu**
(`{queryId:"...",operationName:"OP",operationType:"...",metadata:{
featureSwitches:[...],fieldToggles:[...]}}`) tek bir regex'le, sabit
siralamayi (`queryId` her zaman `operationName`'den once) esas alarak
cikarir — boylece eski scriptteki "en yakin eslesme" hatasi tekrar
edilmez. Sonuclar iki dosyaya yazilir:

- `src/lib/query-ids.json` — operation -> queryId (jawond-bird'in zaten
  kullandigi format/dosya).
- `src/lib/x-features.json` — operation -> `{features: [...], toggles: [...]}`
  (yeni dosya; su an SADECE uretiliyor, `twitter-client.ts` tarafindan
  henuz OKUNMUYOR — twitter-client entegrasyonu opsiyonel sonraki bir adim
  olarak birakildi).

Sadece `fetch` + regex + `node:fs` kullanir, ekstra npm paketi gerekmez
(Node >= 22). Calistirildiginda dogrulanan sonuc: `TweetDetail` query-id'si
`jd3V43oDY9cY7obs1YMfbQ` (mevcut dogru degerle birebir eslesiyor), ve
`CreateTweet`/`CreateRetweet`/`FavoriteTweet` icin eski dosyadaki yanlis
eslesme tespit edilip duzeltildi.

## ChainWise entegrasyonu

`bridge_to_chainwise.py`, `out/tweets_*.json` dosyalarini okuyup her tweeti
ChainWise'in `ingest_articles` tablosuna (`src.common.models.Article`) yazan
bir kopru scriptidir. ChainWise kendi ayri sqlalchemy/uv ortamina sahip
oldugu icin bu script **ChainWise repo'sunda `uv run` ile** calistirilmalidir:

```bash
cd /Users/ahmet/Projects/ChainWise/repo
uv run python /Users/ahmet/Projects/x-analyst-tracker/bridge_to_chainwise.py \
  /Users/ahmet/Projects/x-analyst-tracker/out/tweets_KardesBaris_*.json \
  --skip-retweets
```

Sadece normalize edip sayilarini gormek (DB'ye YAZMADAN) icin `--dry-run`:

```bash
cd /Users/ahmet/Projects/ChainWise/repo
uv run python /Users/ahmet/Projects/x-analyst-tracker/bridge_to_chainwise.py \
  /Users/ahmet/Projects/x-analyst-tracker/out/tweets_KardesBaris_*.json \
  --dry-run --skip-retweets
```

`--chainwise-repo` argumaninin varsayilani zaten
`/Users/ahmet/Projects/ChainWise/repo`'dur; farkli bir yerde calisiyorsaniz
override edin. Belirli dosya(lar) yerine tum `out/` klasorunu islemek icin
`--input-dir ./out` kullanilabilir (dosya argumani verilmezse varsayilan
budur).

Alan eslemesi (canli `user-tweets --json` ciktisina gore, DOGRULANDI):

| jawond-bird `user-tweets --json` alani | ingest_articles |
|---|---|
| `id` | tweet id (url'de kullanilir) |
| `author.username` | `source = f"x:{handle}"`, `author` |
| `id` + `author.username` | `url = f"https://x.com/{handle}/status/{id}"` |
| `text` | `content_text`, `title` (ilk 120 karakter) |
| `createdAt` (RFC2822, `email.utils.parsedate_to_datetime` ile parse) | `published_at` (UTC) |
| sha256(`text`) | `content_hash` |
| `text.startswith("RT @")` | retweet tespiti — `--skip-retweets` ile atlanir |

Bu tabloya yazilan tweetler, ChainWise'in **mevcut** metin sinyal
cikarma hattindan gecer — yeni bir hat kurulmuyor:

- `prompts/extract_text.md` — LLM'e tweet/makale metninden entry/exit/
  outlook/level_watch turunde committed claim cikarma talimati verir.
- `scripts/extract_articles.py` (veya `scripts/load_text_signals.py`) —
  `status='new'` olan `ingest_articles` satirlarini alip ayni prompt ile
  isler ve `status='extracted'` yapar.

Yani akis: `bird user-tweets` -> `out/tweets_*.json` ->
`bridge_to_chainwise.py --skip-retweets` -> `ingest_articles(source="x:<handle>")`
-> ChainWise'in var olan `extract_articles.py` calistirmasi -> sinyal.

Idempotency: `Article.url` UNIQUE kisitina dayanir (`ON CONFLICT (url) DO
NOTHING`); ayni tweet ikinci kez calistirildiginda atlanir.

**Dogrulama durumu:** Tweet JSON semasi (id/text/createdAt/author alan
adlari) jawond-bird `user-tweets --json` komutunun canli, cookie ile
dogrulanmis gercek ciktisiyla karsilastirilarak kesinlestirildi (bkz.
yukaridaki "Kullanim" bolumundeki ornek cikti). Script artik iskelet/TODO
degil, tamamlanmis haldedir.

## Ayri proje olarak kullanim

Bu depo, ChainWise'a bagimli olmadan da kullanilabilir: sadece
`jawond-bird` + `analysts.yaml` + `fetch_analysts.sh` yeterlidir, cikti
`out/*.json` dosyalari olarak kalir ve baska bir sinyal/analiz hattina
(ornegin farkli bir proje, basit bir Excel/CSV donusturucu, veya baska bir
LLM pipeline'i) manuel olarak baglanabilir. `bridge_to_chainwise.py`
sadece ChainWise'a bagli calismak istendiginde gereklidir ve
`--chainwise-repo` argumani disinda hicbir ChainWise dosyasina sabit
(hardcoded) bagimlilik icermez.

## Dizin yapisi

```
x-analyst-tracker/
├── jawond-bird/                          # secilen CLI temeli (calisan bird klonu)
│   ├── scripts/refresh-x-metadata.mjs    # bundle-tabanli query-id + feature/toggle tazeleyici
│   └── src/lib/query-ids.json            # guncel query-id'ler (jawond-bird build'ine dahil)
├── enc0der-bird/         # referans klon (CLI importu kirik, kutuphaneler icin bakilir)
├── analysts.yaml         # takip edilen analist listesi (operator dogrulamali)
├── fetch_analysts.sh     # toplu cekim scripti (user-tweets tabanli)
├── bridge_to_chainwise.py# ChainWise ingest_articles koprusu (tamamlandi, canli dogrulandi)
├── out/                  # cekilen tweet JSON'lari (git'e girmez)
└── .gitignore
```
