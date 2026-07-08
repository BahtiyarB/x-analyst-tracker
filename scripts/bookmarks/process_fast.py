"""Hızlandırılmış bookmark işleme:
- Link-only tweet'ler (t.co dışında hiç text yok) → 'links-only' kategorisine, LLM'siz
- Kural seti genişletildi (author + text)
- Paralel yürütme (thread pool)
- t.co çözme timeout kısaltıldı
- LLM çağrısı yalnız text ≥40 char + kural eşleşmedi
"""

import concurrent.futures as cf
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).parent
RAW = ROOT / "raw" / "bookmarks_20260708.json"

# regex kategoriler (yukarıdan aşağıya öncelik)
CATEGORIES = {
    "claude-optimization": r"\b(claude code|claude opus|claude sonnet|sonnet 5|fable[ -]?[45]|opus 4\.[89]|claude[- ]code|CLAUDE\.md|superpower|skill file|subagent|slash command|claude hook|/prompt |prompt inject|context window)\b",
    "hermes": r"\b(hermes[ -]?[34]|nous ?research|nousresearch|@Teknium|@NousResearch)\b",
    "local-models": r"\b(llama[ -]?\d|qwen[ -]?\d|mistral|phi[- ]?\d|gemma|deepseek|ollama|llama\.cpp|LM Studio|vLLM|MLX|gguf|quantiz|open ?source LLM|local (LLM|model|inference))\b",
    "cybersecurity": r"\b(CVE-|exploit\b|vulnerabilit|pwn|infosec|malware|ransomware|phishing|zero[- ]?day|reverse engineer|infostealer|red team|blue team|pentest|nmap|burp suite|OWASP|XSS|SQLi|RCE)\b",
    "crypto-onchain": r"\b(bitcoin|BTC[/ ]|ethereum|ETH[/ ]|MVRV|NUPL|SOPR|realized price|glassnode|checkonchain|whale|on[- ]?chain|halving|hash rate|blockchain analytic)\b",
    "crypto-market": r"\b(altcoin|memecoin|SOL[/ ]|solana|pump\.fun|airdrop|tokenomics|DeFi|yield farm|liquidity pool|MEV|arbitrage|hyperliquid|farcaster|kripto|coinbase|binance|kraken)\b",
    "trading-quant": r"\b(quant\b|backtest|hedge fund|trading bot|market maker|order flow|orderbook|latency arb|HFT|sharpe|drawdown|risk manag|options trading)\b",
    "ai-research": r"\b(RLHF|DPO|GRPO|attention mechanism|transformer|scaling law|emergence|benchmark|MMLU|GPQA|arxiv\.org|research paper|neurips|ICML|ICLR|fine[- ]?tun)\b",
    "ai-agents": r"\b(agent framework|autogen|langgraph|crewai|multi[- ]?agent|tool use|function calling|MCP\b|model context protocol|agent loop)\b",
    "ai-generic": r"\b(GPT[- ]?[45]|OpenAI|Anthropic|Gemini|prompt engineer|LLM\b|generative AI|AI generat|artificial intel|chatgpt|copilot|cursor\.com|windsurf)\b",
    "engineering-devtools": r"\b(rust\b|golang\b|typescript|python|docker\b|kubernetes|nix\b|homebrew|git\b|CI/CD|github action|terraform|neovim|vscode)\b",
    "product-startup": r"\b(YC\b|Y Combinator|startup|founder|MRR\b|ARR\b|SaaS|product[- ]?market fit|indie hack|bootstrap|pmf\b)\b",
    "life-philosophy": r"\b(meditation|stoic|philosophy|productivity|mental health|self[- ]?improve|journaling|habit\b|virüs|virolog|salgın|hastalık)\b",
    "turkish-content": r"\b(kripto|piyasa|yatırım|analiz|ekonomi|dolar|altın|borsa|hisse|Türkiye)\b",
}


def load_bookmarks() -> list[dict]:
    return json.loads(RAW.read_text())


TCO_RE = re.compile(r"https?://t\.co/\w+")
NON_URL_RE = re.compile(r"https?://\S+")


def is_link_only(text: str) -> bool:
    """Text tümüyle URL'lerden mi ibaret (kelime içermiyor)."""
    stripped = NON_URL_RE.sub("", text).strip()
    # 15 karakterden az anlamlı text var → link-only kabul
    return len(stripped) < 15


def categorize_rule(text: str, author: str) -> str | None:
    hay = text + " author:" + author
    for cat, pat in CATEGORIES.items():
        if re.search(pat, hay, re.IGNORECASE):
            return cat
    return None


LLM_URL = "http://localhost:1234/v1/chat/completions"
LLM_MODEL = "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive"
CATEGORY_LIST = list(CATEGORIES.keys()) + ["links-only", "misc"]


def categorize_llm(text: str, client: httpx.Client) -> str:
    prompt = (
        "Classify tweet. Reply ONE category only:\n"
        + ", ".join(CATEGORY_LIST)
        + f"\n\nTweet: {text[:400]}\n\nCategory:"
    )
    try:
        r = client.post(
            LLM_URL,
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 12,
            },
            timeout=20,
        )
        if r.status_code != 200:
            return "misc"
        ans = r.json()["choices"][0]["message"]["content"].strip().lower()
        for c in CATEGORY_LIST:
            if c in ans:
                return c
    except Exception:
        pass
    return "misc"


def resolve_url(short: str, client: httpx.Client) -> str | None:
    try:
        r = client.head(short, follow_redirects=False, timeout=5)
        return r.headers.get("location")
    except Exception:
        return None


def is_article_url(url: str) -> bool:
    p = urlparse(url)
    if p.netloc in ("t.co", "x.com", "twitter.com"):
        return False
    ext = Path(p.path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".webp", ".webm"):
        return False
    return bool(p.netloc)


def download_article(url: str, dest_dir: Path, client: httpx.Client) -> str | None:
    try:
        r = client.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 500:
            return None
        p = urlparse(str(r.url))
        stem = re.sub(r"[^a-zA-Z0-9._-]", "_",
                      p.netloc + "_" + p.path.strip("/").replace("/", "_"))[:100] or "article"
        target = dest_dir / f"{stem}.html"
        if not target.exists():
            target.write_text(r.text, encoding="utf-8", errors="replace")
        return target.name
    except Exception:
        return None


# thread-local httpx client
def worker_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": "Mozilla/5.0"})


def process_one(bm: dict) -> tuple[str, str, list[str]]:
    """Tek bookmark: kategorize + link çöz + makale indir. Dönüş: (id, category, resolved_urls)."""
    text = bm.get("text", "")
    author = (bm.get("author") or {}).get("username", "unknown")

    # 1) link-only mi?
    if is_link_only(text):
        cat = "links-only"
    else:
        # 2) kural?
        cat = categorize_rule(text, author) or ""
        if not cat:
            # 3) LLM (yalnız yeterli text varsa)
            with worker_client() as c:
                cat = categorize_llm(text, c)

    # kategori klasörü yaz
    cat_dir = ROOT / cat
    cat_dir.mkdir(exist_ok=True)

    tweet_url = f"https://x.com/{author}/status/{bm['id']}"
    # linkleri çöz + makale indir
    resolved = []
    art_dir = cat_dir / "_articles"
    with worker_client() as c:
        for short in TCO_RE.findall(text):
            real = resolve_url(short, c)
            if real:
                resolved.append(real)
                if is_article_url(real):
                    art_dir.mkdir(exist_ok=True)
                    download_article(real, art_dir, c)

    md_lines = [
        f"# @{author} — {(bm.get('author') or {}).get('name','')}",
        "",
        f"**Tarih:** {bm.get('createdAt','')}",
        f"**URL:** {tweet_url}",
        f"**Metrikler:** ❤️{bm.get('likeCount',0)} / 🔁{bm.get('retweetCount',0)} / 💬{bm.get('replyCount',0)}",
        "",
        "## İçerik",
        "",
        text or "*(sadece medya)*",
    ]
    if resolved:
        md_lines += ["", "## Linkler", ""] + [f"- {u}" for u in resolved]

    (cat_dir / f"{bm['id']}.md").write_text("\n".join(md_lines), encoding="utf-8")
    return bm["id"], cat, resolved


def main():
    bookmarks = load_bookmarks()
    limit = int(os.environ.get("LIMIT", "0")) or len(bookmarks)
    print(f"toplam {len(bookmarks)} bookmark; işlenecek: {limit}")
    workers = int(os.environ.get("WORKERS", "8"))

    stats = {"by_cat": {}}
    start = time.time()

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(process_one, bm) for bm in bookmarks[:limit]]
        done = 0
        for f in cf.as_completed(futures):
            try:
                _id, cat, urls = f.result()
                stats["by_cat"][cat] = stats["by_cat"].get(cat, 0) + 1
            except Exception as e:
                print(f"  hata: {str(e)[:80]}", file=sys.stderr)
            done += 1
            if done % 30 == 0:
                el = time.time() - start
                rate = done / el
                eta = (limit - done) / rate if rate > 0 else 0
                print(f"  [{done}/{limit}] {rate:.1f}/sn, ETA {eta/60:.1f} dk", flush=True)

    print("\n=== ÖZET ===")
    for cat, n in sorted(stats["by_cat"].items(), key=lambda x: -x[1]):
        print(f"  {cat:30s} {n:4d}")
    print(f"\ntoplam süre: {(time.time()-start)/60:.1f} dk")
    (ROOT / "summary.json").write_text(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
