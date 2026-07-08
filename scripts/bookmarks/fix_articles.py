"""İçerik iyileştirme (gap-fill):
- GitHub repo URL'leri → raw README fetch (JS render sorununu bypass)
- github.com/*/blob/* → raw dosya içeriği
- Google Docs/Sheets → not "auth-required"
- Twitter thread linkleri → skip (kaynak zaten twitter'dan geldi)
- Küçük dosyalar (< 5KB HTML) → readable text extraction, boyut kontrolü
Sonuç: her _articles klasöründe hem .html (orijinal) hem .md (readable/ham içerik).
"""

import re
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).parent


def github_repo_readme(url: str, client: httpx.Client) -> str | None:
    """github.com/OWNER/REPO → raw README.md."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)/?$", url.rstrip("/"))
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    for branch in ("main", "master"):
        for name in ("README.md", "readme.md", "README", "README.rst"):
            r = client.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{name}",
                           timeout=10, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 200:
                return r.text
    return None


def github_blob_raw(url: str, client: httpx.Client) -> str | None:
    """github.com/OWNER/REPO/blob/BRANCH/PATH → raw dosya."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", url)
    if not m:
        return None
    owner, repo, branch, path = m.groups()
    r = client.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
                   timeout=15, follow_redirects=True)
    if r.status_code == 200:
        return r.text
    return None


AUTH_MARKERS = [
    "accounts.google.com/v3/signin",
    "login.microsoftonline.com",
    "www.linkedin.com/login",
    "twitter.com/i/flow/login",
    "medium.com/m/signin",
    "notion.so/login",
]


def is_auth_page(html_path: Path) -> bool:
    """HTML dosya yolu bir auth/login sayfası mı?"""
    name = html_path.name.lower()
    return any(marker.replace("/", "_").lower() in name for marker in AUTH_MARKERS)


def readable_text_from_html(html: str) -> str:
    """Ham HTML'den okunabilir text (basit — no dep)."""
    # script, style, nav, footer, header sil
    text = re.sub(r"<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", "",
                  html, flags=re.DOTALL | re.IGNORECASE)
    # tag'ları temizle
    text = re.sub(r"<[^>]+>", " ", text)
    # HTML entity
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_original_url_from_md(md_path: Path) -> str | None:
    """Bookmark .md dosyasında '## Linkler' altındaki ilk URL'yi bul."""
    txt = md_path.read_text(encoding="utf-8", errors="replace")
    for line in txt.splitlines():
        m = re.match(r"^- (https?://\S+)$", line.strip())
        if m and "t.co" not in m.group(1):
            return m.group(1)
    return None


def enrich_articles():
    """Her kategori/_articles altında iyileştirme yap."""
    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"})
    stats = {"github_readme": 0, "github_raw": 0, "auth_gated": 0, "unchanged": 0, "text_extracted": 0, "total": 0}

    for art_dir in ROOT.glob("*/_articles"):
        for html in art_dir.glob("*.html"):
            stats["total"] += 1
            sz = html.stat().st_size

            # 1) auth gated?
            if is_auth_page(html):
                (html.with_suffix(".AUTH_GATED")).touch()
                stats["auth_gated"] += 1
                continue

            # 2) github.com sayfası mı? → raw versiyon çek
            name = html.stem
            if name.startswith("github.com_"):
                # rekonstrukte URL
                url = "https://" + name.replace("_", "/", 1).replace("_", "/")
                # önce blob mu repo mu — dosya adı içinde "blob" var mı
                if "_blob_" in name:
                    raw = github_blob_raw(url, client)
                    if raw:
                        html.with_suffix(".raw").write_text(raw, encoding="utf-8", errors="replace")
                        stats["github_raw"] += 1
                        continue
                else:
                    readme = github_repo_readme(url, client)
                    if readme:
                        html.with_suffix(".README.md").write_text(readme, encoding="utf-8")
                        stats["github_readme"] += 1
                        continue

            # 3) küçük ise (<5KB) — text extract dene
            if sz < 5000:
                text = readable_text_from_html(html.read_text(encoding="utf-8", errors="replace"))
                if len(text) > 200:
                    html.with_suffix(".txt").write_text(text, encoding="utf-8")
                    stats["text_extracted"] += 1
                    continue

            stats["unchanged"] += 1

    print("\n=== ARTICLE ENRICHMENT ===")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")

    client.close()


if __name__ == "__main__":
    enrich_articles()
