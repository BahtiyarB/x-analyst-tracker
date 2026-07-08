"""x_articles_raw/*.json'dan article body çıkar, md'ye ekle, reclassify."""

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
RAW_DIR = ROOT / "x_articles_raw"
LINKS_ONLY = ROOT / "links-only"

TEXT_CATEGORIES = {
    "claude-optimization": r"\b(claude code|claude opus|claude sonnet|sonnet 5|fable[ -]?[45]|opus 4\.[89]|CLAUDE\.md|superpower|skill file|subagent|slash command|prompt cach|hook file)\b",
    "hermes": r"\b(hermes[ -]?[34]|nous ?research|nousresearch|Teknium)\b",
    "local-models": r"\b(llama[ -]?\d|qwen[ -]?\d|mistral|phi[- ]?\d|gemma|deepseek|ollama|llama\.cpp|LM Studio|vLLM|MLX|gguf|quantiz|local (LLM|model|inference))\b",
    "cybersecurity": r"\b(CVE-|exploit|vulnerabilit|infosec|malware|phishing|zero[- ]?day|reverse engineer|red team|pentest|nmap|OWASP|RCE|SQLi)\b",
    "crypto-onchain": r"\b(bitcoin|BTC|ethereum|ETH|MVRV|NUPL|SOPR|realized price|glassnode|checkonchain|whale|on[- ]?chain|halving)\b",
    "crypto-market": r"\b(altcoin|memecoin|solana|SOL|pump\.fun|airdrop|tokenomics|DeFi|MEV|arbitrage|hyperliquid|farcaster)\b",
    "trading-quant": r"\b(quant\b|backtest|hedge fund|trading bot|order flow|orderbook|HFT|sharpe|drawdown|risk manag)\b",
    "ai-research": r"\b(RLHF|DPO|GRPO|attention|transformer|scaling law|MMLU|GPQA|arxiv|research paper|fine[- ]?tun|neurips|ICLR)\b",
    "ai-agents": r"\b(agent framework|autogen|langgraph|crewai|multi[- ]?agent|tool use|function calling|MCP\b|model context protocol|agent loop|swarm)\b",
    "ai-generic": r"\b(GPT[- ]?[45]|OpenAI|Anthropic|Gemini|prompt engineer|LLM\b|generative AI|chatgpt|copilot|cursor|windsurf|vibe cod)\b",
    "engineering-devtools": r"\b(rust\b|golang\b|typescript|python|docker\b|kubernetes|nix\b|git\b|CI/CD|github action|terraform|neovim|vscode)\b",
    "product-startup": r"\b(YC\b|Y Combinator|startup|founder|MRR\b|ARR\b|SaaS|product[- ]?market fit|indie hack|bootstrap)\b",
    "life-philosophy": r"\b(meditation|stoic|philosophy|productivity|mental health|self[- ]?improve|journaling|habit)\b",
    "turkish-content": r"\b(kripto|piyasa|yatırım|analiz|ekonomi|dolar|altın|borsa|hisse|Türkiye)\b",
}


def extract_article(raw: dict) -> dict | None:
    try:
        instructions = raw["data"]["threaded_conversation_with_injections_v2"]["instructions"]
        for inst in instructions:
            if "entries" not in inst:
                continue
            for entry in inst["entries"]:
                tr = entry.get("content", {}).get("itemContent", {}).get("tweet_results", {}).get("result")
                if not tr:
                    continue
                art = tr.get("article", {}).get("article_results", {}).get("result")
                if not art:
                    tr2 = tr.get("tweet") or {}
                    art = tr2.get("article", {}).get("article_results", {}).get("result")
                if not art:
                    continue
                blocks = art.get("content_state", {}).get("blocks", [])
                body_lines = []
                for b in blocks:
                    text = b.get("text", "")
                    btype = b.get("type", "unstyled")
                    if btype.startswith("header-"):
                        suffix = btype.split("-")[-1]
                        level = int(suffix) if suffix.isdigit() else 2
                        body_lines.append(f"{'#' * level} {text}")
                    elif btype == "unordered-list-item":
                        body_lines.append(f"- {text}")
                    elif btype == "ordered-list-item":
                        body_lines.append(f"1. {text}")
                    else:
                        body_lines.append(text)
                return {
                    "title": art.get("title", ""),
                    "preview": art.get("preview_text", ""),
                    "body": "\n\n".join(body_lines),
                }
    except Exception as e:
        print(f"  parse error: {e}", file=sys.stderr)
    return None


def classify(text: str) -> str:
    for cat, pat in TEXT_CATEGORIES.items():
        if re.search(pat, text, re.IGNORECASE):
            return cat
    return "misc"


def main():
    raw_files = list(RAW_DIR.glob("*.json"))
    print(f"{len(raw_files)} article JSON")
    stats = {"parsed": 0, "no_article": 0, "moved": {}, "misc": 0}
    for raw_path in raw_files:
        aid = raw_path.stem
        try:
            raw = json.loads(raw_path.read_text())
        except Exception:
            continue
        art = extract_article(raw)
        if not art:
            stats["no_article"] += 1
            continue
        stats["parsed"] += 1
        md = None
        for cand in ROOT.glob(f"*/{aid}.md"):
            md = cand
            break
        if not md:
            continue
        existing = md.read_text(encoding="utf-8", errors="replace")
        if "## Article İçeriği" not in existing:
            content_md = "\n\n## Article İçeriği\n\n"
            if art["title"]:
                content_md += f"### {art['title']}\n\n"
            content_md += art["body"]
            md.write_text(existing.rstrip() + content_md + "\n", encoding="utf-8")
        classify_text = (art["title"] or "") + " " + (art["body"] or "")
        new_cat = classify(classify_text)
        if new_cat == "misc":
            stats["misc"] += 1
            continue
        current_cat = md.parent.name
        if current_cat == new_cat:
            continue
        if current_cat != "links-only":
            continue
        dest = ROOT / new_cat
        dest.mkdir(exist_ok=True)
        shutil.move(str(md), str(dest / md.name))
        m_src = LINKS_ONLY / "_media" / aid
        if m_src.exists():
            (dest / "_media").mkdir(exist_ok=True)
            shutil.move(str(m_src), str(dest / "_media" / aid))
        stats["moved"][new_cat] = stats["moved"].get(new_cat, 0) + 1
    print("\n=== PARSE + RECLASSIFY ===")
    print(f"  parsed: {stats['parsed']}, no_article: {stats['no_article']}")
    print(f"  hâlâ misc: {stats['misc']}")
    print("  taşınan:")
    for cat, n in sorted(stats["moved"].items(), key=lambda x: -x[1]):
        if n > 0:
            print(f"    {cat:30s} +{n}")


if __name__ == "__main__":
    main()
