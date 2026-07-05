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
- [X kirilganligi ve query-id onarimi](#x-kirilganligi-ve-query-id-onarimi)
- [ChainWise entegrasyonu](#chainwise-entegrasyonu)
- [Ayri proje olarak kullanim](#ayri-proje-olarak-kullanim)
- [Dizin yapisi](#dizin-yapisi)

## Ne ise yarar

Bu proje su akisi otomatiklestirir:

1. `analysts.yaml` icinde takip edilecek kripto analistlerinin X handle'lari
   tanimlanir (onchain analistler, TR/EN karisik olabilir).
2. `fetch_analysts.sh`, her analist icin `bird search "from:<handle>"`
   komutunu calistirip son N tweet'i JSON olarak `out/` klasorune yazar.
3. `bridge_to_chainwise.py` (opsiyonel), bu JSON dosyalarini okuyup her
   tweet'i normalize eder (id, handle, created_at, text, url) ve ChainWise'in
   `ingest_articles` tablosuna yazar — boylece ChainWise'in mevcut metin
   sinyal cikarma hatti (bkz. asagida) tweetleri de bir "makale" gibi isleyip
   trade sinyaline (entry/exit/outlook/level_watch) cevirebilir.

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

Tek bir analistin son tweetlerini cekmek:

```bash
node jawond-bird/dist/index.js search "from:glassnode" -n 50 --json
```

Tum `analysts.yaml` listesini toplu cekmek:

```bash
./fetch_analysts.sh 20260706
```

(Tarih argumani opsiyoneldir; verilmezse bugunun tarihi `YYYYMMDD` olarak
kullanilir.) Cikti: `out/tweets_<handle>_<tarih>.json`. Bir analist
basarisiz olursa (auth hatasi, handle degismis, rate-limit vb.) script
o hatayi loglayip diger analistlerle devam eder; hata detayi
`out/tweets_<handle>_<tarih>.err` dosyasina yazilir.

## X kirilganligi ve query-id onarimi

X, GraphQL sorgu ID'lerini (`query-id`) periyodik olarak degistirir; bu
yuzden `search` gibi komutlar zamanla `HTTP 404`/`422` hatasi vermeye
baslayabilir. Bu durumda:

```bash
cd jawond-bird
npm run graphql:update
npm run build
```

Bu komut, X'in web bundle'larindan guncel query-id'leri cekip
`src/lib/query-ids.json` dosyasini tazeler (kullanilan endpoint:
`x.com/i/api/graphql`, ilgili sorgu adi `SearchTimeline`). Sonrasinda
yeniden derleme (`npm run build`) gereklidir.

## ChainWise entegrasyonu

`bridge_to_chainwise.py`, `out/tweets_*.json` dosyalarini okuyup her tweeti
ChainWise'in `ingest_articles` tablosuna (`src.common.models.Article`) yazan
bir kopru scriptidir:

```bash
python3 bridge_to_chainwise.py \
  --chainwise-repo /Users/ahmet/Projects/ChainWise/repo \
  --input-dir ./out \
  [--dry-run]
```

Alan eslemesi:

| x-analyst-tracker | ingest_articles |
|---|---|
| `handle` | `source = f"x:{handle}"`, `author` |
| tweet id + handle | `url = f"https://x.com/{handle}/status/{id}"` |
| tweet metni | `content_text` |
| tweet zaman damgasi | `published_at` |
| sha256(content_text) | `content_hash` |

Bu tabloya yazilan tweetler, ChainWise'in **mevcut** metin sinyal
cikarma hattindan gecer — yeni bir hat kurulmuyor:

- `prompts/extract_text.md` — LLM'e tweet/makale metninden entry/exit/
  outlook/level_watch turunde committed claim cikarma talimati verir.
- `scripts/extract_articles.py` (veya `scripts/load_text_signals.py`) —
  `status='new'` olan `ingest_articles` satirlarini alip ayni prompt ile
  isler ve `status='extracted'` yapar.

Yani akis: `bird search` -> `out/tweets_*.json` -> `bridge_to_chainwise.py`
-> `ingest_articles(source="x:<handle>")` -> ChainWise'in var olan
`extract_articles.py` calistirmasi -> sinyal.

**Onemli — dogrulanmamis kisimlar:** `bridge_to_chainwise.py` icindeki
tweet JSON semasi (id/text/created_at alan adlari) jawond-bird'in gercek
cookie ile calistirilmis bir `search --json` ciktisiyla henuz
KARSILASTIRILMADI (bu calisma agla istegi atmadan yapildi). Script
icinde ilgili noktalar `TODO(cookie-dogrulama)` etiketiyle isaretlendi;
ilk gercek cookie testinden sonra bu TODO'lar gozden gecirilip
duzeltilmeli.

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
├── jawond-bird/          # secilen CLI temeli (calisan bird klonu)
├── enc0der-bird/         # referans klon (CLI importu kirik, kutuphaneler icin bakilir)
├── analysts.yaml         # takip edilen analist listesi (operator dogrulamali)
├── fetch_analysts.sh     # toplu cekim scripti
├── bridge_to_chainwise.py# ChainWise ingest_articles koprusu (iskelet)
├── out/                  # cekilen tweet JSON'lari (git'e girmez)
└── .gitignore
```
