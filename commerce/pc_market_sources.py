from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .pc_market import MarketListing, PCFingerprint

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"

# Search-engine discovery is deliberately restricted to mainstream UK PC retailers.
RETAILERS = {
    "Scan": "scan.co.uk",
    "Overclockers UK": "overclockers.co.uk",
    "Currys": "currys.co.uk",
    "AWD-IT": "awd-it.co.uk",
    "CCL": "cclonline.com",
}


def _fetch(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _query(fp: PCFingerprint) -> str:
    terms = [x for x in (fp.cpu, fp.gpu, f"{fp.ram_gb}GB" if fp.ram_gb else "", "gaming PC") if x]
    return " ".join(terms)


def _jsonld_products(html: str, retailer: str, domain: str) -> list[MarketListing]:
    found: list[MarketListing] = []
    scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    for raw in scripts:
        try:
            payload = json.loads(unescape(raw).strip())
        except (ValueError, TypeError):
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node); continue
            if not isinstance(node, dict):
                continue
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            typ = str(node.get("@type", "")).lower()
            if typ != "product":
                continue
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            try:
                price = float(str(offers.get("price") or offers.get("lowPrice") or "").replace(",", ""))
            except ValueError:
                continue
            title = str(node.get("name") or "").strip()
            url = str(node.get("url") or offers.get("url") or "").strip()
            if url.startswith("/"):
                url = f"https://www.{domain}{url}"
            if title and price > 0:
                found.append(MarketListing(retailer=retailer, title=title, price=price, url=url))
    return found


def collect_market_references(fp: PCFingerprint) -> list[MarketListing]:
    """Best-effort zero-API UK retail comparison collector.

    Retailer pages change frequently, so failures are isolated per source. We only return
    explicit Product JSON-LD prices; no guessed/snippet prices are admitted as market truth.
    """
    query = _query(fp)
    results: list[MarketListing] = []
    seen: set[tuple[str, str, float]] = set()
    for retailer, domain in RETAILERS.items():
        try:
            search_url = f"https://www.google.com/search?q={quote_plus('site:' + domain + ' ' + query)}"
            search_html = _fetch(search_url)
            urls = re.findall(r'https?://(?:www\.)?' + re.escape(domain) + r'/[^&"<> ]+', search_html, re.I)
            for url in urls[:4]:
                clean = unescape(url).split("&")[0]
                try:
                    html = _fetch(clean)
                except Exception:
                    continue
                for item in _jsonld_products(html, retailer, domain):
                    key = (item.retailer, item.title.lower(), item.price)
                    if key not in seen:
                        seen.add(key); results.append(item)
        except Exception:
            continue
    return results
