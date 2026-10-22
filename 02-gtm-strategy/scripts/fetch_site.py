#!/usr/bin/env python3
"""Fetch a company website and save readable text for the strategy prompt.

Reads the homepage plus common pages (pricing, about, customers, case
studies, product) and writes site_notes.md. Read only, no keys needed.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import requests  # noqa: E402
from gtm_common import BROWSER_UA, log  # noqa: E402

PAGE_HINTS = ("pricing", "about", "customer", "case-stud", "case_stud", "product",
              "solution", "platform", "features", "testimonial", "results")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|tr|section)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    return "\n".join(l for l in lines if len(l) > 2)


def find_links(base: str, raw: str, limit: int) -> list[str]:
    host = urlparse(base).netloc
    seen, out = set(), []
    for href in re.findall(r'href=["\']([^"\'#]+)', raw):
        url = urljoin(base, href)
        u = urlparse(url)
        if u.netloc != host or url in seen:
            continue
        if any(h in u.path.lower() for h in PAGE_HINTS):
            seen.add(url)
            out.append(url)
    return out[:limit]


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=30)
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", help="company website, e.g. https://acme.example")
    p.add_argument("--max-pages", type=int, default=6)
    p.add_argument("--max-chars", type=int, default=6000, help="per page")
    p.add_argument("--out", default="site_notes.md")
    a = p.parse_args(argv)
    url = a.url if a.url.startswith("http") else "https://" + a.url
    home = fetch(url)
    parts = [f"# Site notes for {url}\n", f"## {url}\n", html_to_text(home)[:a.max_chars]]
    for link in find_links(url, home, a.max_pages):
        try:
            parts += [f"\n## {link}\n", html_to_text(fetch(link))[:a.max_chars]]
        except requests.RequestException as e:
            log(f"skip {link}: {e}")
    Path(a.out).write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"Saved {len(parts) // 2} pages -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
