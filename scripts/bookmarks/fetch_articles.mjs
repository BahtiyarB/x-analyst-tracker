// Bird cookies + TweetDetail GraphQL (withArticlePlainText=true) — X Article body cekimi.
// Ortak istemci: x_tweetdetail.mjs (cookie extraction + fetchTweetDetail). Bu dosya yalniz
// article-toplu-cekme moduna (--file) + tekil debug moduna (--id) odaklanir.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createClient } from './x_tweetdetail.mjs';

const client = await createClient('Profile 2');
console.error('cookies OK');

const arg = process.argv.slice(2);
if (arg[0] === '--id') {
  const r = await client.fetchTweetDetail(arg[1]);
  if (!r.ok) { console.error(JSON.stringify(r)); process.exit(2); }
  console.log(JSON.stringify(r.data, null, 2));
} else if (arg[0] === '--file') {
  const ids = (await fs.readFile(arg[1], 'utf8')).trim().split('\n').filter(Boolean);
  const outDir = arg[2] || 'x_articles_raw';
  await fs.mkdir(outDir, { recursive: true });
  console.error(`${ids.length} id işlenecek → ${outDir}/`);
  let ok = 0, fail = 0, skipped = 0;
  for (const id of ids) {
    const dest = path.join(outDir, `${id}.json`);
    try { await fs.access(dest); skipped++; ok++; continue; } catch {}
    const r = await client.fetchTweetDetail(id);
    if (r.ok) {
      await fs.writeFile(dest, JSON.stringify(r.data));
      ok++;
    } else {
      await fs.writeFile(dest + '.err', JSON.stringify({ status: r.status, error: r.error }));
      fail++;
    }
    if ((ok + fail) % 20 === 0) {
      console.error(`  [${ok+fail}/${ids.length}] ok=${ok} skip=${skipped} fail=${fail}`);
    }
    await new Promise(r => setTimeout(r, 400));
  }
  console.error(`\nBitti: ok=${ok} skip=${skipped} fail=${fail}`);
} else {
  console.error('Usage: --id <tweet_id>  OR  --file <ids.txt> [out_dir]');
  process.exit(1);
}
