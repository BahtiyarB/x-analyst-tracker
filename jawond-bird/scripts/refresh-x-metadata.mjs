#!/usr/bin/env node
/**
 * refresh-x-metadata.mjs — bundle-tabanlı otomatik query-id + feature/toggle
 * tazeleyici.
 *
 * NEDEN: Onceki `graphql:update` (scripts/update-query-ids.ts) query-id'leri
 * "en yakin operationName<->queryId ciftini regex ile eslestirerek" cikariyordu.
 * Bu yaklasim 2026-07-06'da YANLIS eslestirmeye yol acti: x.com'un guncel
 * main.*.js bundle'inda CreateTweet'in gercek queryId'si "R5EPiGHgSqbTYFyozd-gFw"
 * iken, eski script bu degeri yanlislikla CreateRetweet'e atamisti (ve
 * CreateTweet'e farkli/eski bir deger kalmisti). Kok neden: regex,
 * `operationName:"X"` ile `queryId:"Y"` arasindaki en yakin ciftlesmeyi ariyordu,
 * ama minified bundle'da queryId HER ZAMAN operationName'den ONCE gelir
 * (`{queryId:"...",operationName:"OP",operationType:...,metadata:{featureSwitches:[...],fieldToggles:[...]}}`
 * bloklari ardisik olarak siralidir) ve bir onceki operation'in queryId'si
 * bir sonrakinin operationName'ine "yakin" gorunebiliyordu.
 *
 * Bu script onun yerini alir: her hedef operation icin TUM blogu
 * (`{queryId:"...",operationName:"OP",...featureSwitches:[...],fieldToggles:[...]}`)
 * TEK bir regex ile, siralamayi (queryId ONCE, operationName SONRA) sabit
 * kabul ederek cikarir. Boylece yanlis eslestirme riski ortadan kalkar.
 *
 * MANTIK:
 *   1. https://x.com/?lang=en HTML'ini cek.
 *   2. HTML icinde `abs.twimg.com/responsive-web/client-web/main.*.js`
 *      bundle URL'ini bul (tek, guncel ana bundle).
 *   3. Bundle'i indir.
 *   4. Her hedef operation (CreateTweet, CreateRetweet, FavoriteTweet,
 *      TweetDetail, SearchTimeline, UserTweets, UserByScreenName) icin
 *      `{queryId:"...",operationName:"OP",operationType:"...",metadata:{
 *        featureSwitches:[...],fieldToggles:[...]}}` seklindeki tam blogu
 *      regex ile cikar.
 *   5. queryId'leri src/lib/query-ids.json'a yaz (mevcut format/siralama
 *      korunarak).
 *   6. featureSwitches + fieldToggles'i AYRI bir dosyaya, src/lib/x-features.json,
 *      su sekilde yaz: { "OperationName": { "features": [...], "toggles": [...] } }
 *
 * NOT (kapsam siniri): twitter-client.ts su an TWEET_FEATURES /
 * TWEET_FIELD_TOGGLES / USER_BY_SCREEN_NAME_FEATURES / ... degiskenlerini
 * HARD-CODED tutuyor. Bu script SADECE query-ids.json'i guncelliyor ve
 * x-features.json'i URETIYOR; twitter-client.ts'i x-features.json OKUYACAK
 * sekilde refactor ETMIYOR. twitter-client entegrasyonu opsiyonel sonraki
 * bir adimdir (once bu script'in urettigi x-features.json'in birkac
 * calistirmada kararli/dogru oldugu gozlemlenmeli, sonra istenirse
 * twitter-client.ts bu dosyayi okuyacak sekilde degistirilebilir).
 *
 * Bagimlilik: sadece global fetch + regex + node:fs (Node >= 18 fetch, bu
 * proje Node >= 22 hedefliyor). Ekstra npm paketi gerekmez.
 *
 * Kullanim:
 *   node scripts/refresh-x-metadata.mjs
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '..');
const QUERY_IDS_PATH = path.join(PROJECT_ROOT, 'src/lib/query-ids.json');
const FEATURES_PATH = path.join(PROJECT_ROOT, 'src/lib/x-features.json');

const TARGET_OPERATIONS = [
  'CreateTweet',
  'CreateRetweet',
  'FavoriteTweet',
  'TweetDetail',
  'SearchTimeline',
  'UserTweets',
  'UserByScreenName',
];

const DISCOVERY_PAGE = 'https://x.com/?lang=en';

const BUNDLE_URL_REGEX =
  /https:\/\/abs\.twimg\.com\/responsive-web\/client-web\/main\.[A-Za-z0-9]+\.js/;

const HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
  Accept: 'text/html,application/json;q=0.9,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
};

async function fetchText(url) {
  const response = await fetch(url, { headers: HEADERS });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`HTTP ${response.status} for ${url}: ${body.slice(0, 200)}`);
  }
  return response.text();
}

async function discoverBundleUrl() {
  const html = await fetchText(DISCOVERY_PAGE);
  const match = html.match(BUNDLE_URL_REGEX);
  if (!match) {
    throw new Error(
      `No main.*.js bundle URL found in ${DISCOVERY_PAGE}; x.com layout may have changed.`,
    );
  }
  return match[0];
}

/**
 * Verilen operationName icin bundle icindeki TAM blogu cikarir. queryId,
 * operationName'den ONCE gelir (bundle'daki sabit sira); bu yuzden regex
 * `queryId` ile baslar ve `operationName:"OP"` ile devam eder, ardindan
 * metadata.featureSwitches / fieldToggles dizilerini yakalar.
 *
 * String dizisi elemanlari basit `"..."` seklinde (icinde ozel karakter/kacis
 * yok, X'in kendi feature-flag isimleri alfanumerik+alt cizgi), bu yuzden
 * `\[([^\]]*)\]` ile guvenle yakalanabilir.
 */
function extractOperationBlock(bundleContents, operationName) {
  const re = new RegExp(
    'queryId:"([^"]+)",operationName:"' +
      operationName +
      '",operationType:"(query|mutation)",metadata:\\{featureSwitches:\\[([^\\]]*)\\],fieldToggles:\\[([^\\]]*)\\]\\}',
  );
  const match = bundleContents.match(re);
  if (!match) return null;

  const [, queryId, operationType, featuresRaw, togglesRaw] = match;
  const parseStringArray = (raw) =>
    raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => s.replace(/^"|"$/g, ''));

  return {
    queryId,
    operationType,
    features: parseStringArray(featuresRaw),
    toggles: parseStringArray(togglesRaw),
  };
}

async function readExistingQueryIds() {
  try {
    const contents = await fs.readFile(QUERY_IDS_PATH, 'utf8');
    return JSON.parse(contents);
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.warn('[warn] Failed to read existing query-ids.json:', error.message);
    }
    return {};
  }
}

async function main() {
  console.log('[info] Discovering x.com main bundle URL…');
  const bundleUrl = await discoverBundleUrl();
  console.log(`[info] Bundle: ${bundleUrl}`);

  console.log('[info] Downloading bundle…');
  const bundleContents = await fetchText(bundleUrl);
  console.log(`[info] Bundle size: ${bundleContents.length} bytes`);

  const existingIds = await readExistingQueryIds();

  const nextIds = { ...existingIds };
  const featuresOut = {};
  const notFound = [];

  for (const op of TARGET_OPERATIONS) {
    const block = extractOperationBlock(bundleContents, op);
    if (!block) {
      notFound.push(op);
      continue;
    }
    nextIds[op] = block.queryId;
    featuresOut[op] = {
      features: block.features,
      toggles: block.toggles,
    };
  }

  if (Object.keys(featuresOut).length === 0) {
    throw new Error(
      'No operations extracted; bundle format may have changed (check OPERATION regex).',
    );
  }

  // query-ids.json'i mevcut anahtar sirasini koruyarak yaz (TARGET_OPERATIONS
  // sirasi, mevcut dosyadaki sirayla ayni tutulmustur).
  const orderedIds = {};
  for (const op of TARGET_OPERATIONS) {
    if (nextIds[op]) orderedIds[op] = nextIds[op];
  }
  await fs.mkdir(path.dirname(QUERY_IDS_PATH), { recursive: true });
  await fs.writeFile(QUERY_IDS_PATH, `${JSON.stringify(orderedIds, null, 2)}\n`, 'utf8');

  await fs.mkdir(path.dirname(FEATURES_PATH), { recursive: true });
  await fs.writeFile(FEATURES_PATH, `${JSON.stringify(featuresOut, null, 2)}\n`, 'utf8');

  console.log('---');
  for (const op of TARGET_OPERATIONS) {
    const previous = existingIds[op];
    const current = nextIds[op];
    if (!current) {
      console.warn(`not found (bundle blogu eslesmedi, eski deger korunuyor varsa): ${op}`);
      continue;
    }
    if (previous && previous !== current) {
      console.log(`${op}: ${previous} -> ${current} (DEGISTI)`);
    } else if (previous) {
      console.log(`${op}: ${current} (degismedi)`);
    } else {
      console.log(`${op}: ${current} (yeni)`);
    }
  }
  if (notFound.length > 0) {
    console.warn(`[warn] Bulunamayan operationlar: ${notFound.join(', ')}`);
  }
  console.log('---');
  console.log(`[info] Updated ${QUERY_IDS_PATH}`);
  console.log(`[info] Updated ${FEATURES_PATH}`);
  console.log(
    '[info] twitter-client entegrasyonu opsiyonel sonraki adim: twitter-client.ts su an ' +
      'TWEET_FEATURES/TWEET_FIELD_TOGGLES vb. degiskenleri hard-coded tutuyor; bu script ' +
      'sadece x-features.json uretiyor, twitter-client.ts bu dosyayi henuz okumuyor.',
  );
}

main().catch((error) => {
  console.error('[error]', error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
