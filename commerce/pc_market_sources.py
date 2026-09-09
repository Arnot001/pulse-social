from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from .pc_market import MarketListing, PCFingerprint

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"

RETAILERS = {
    "Scan": "scan.co.uk",
    "Overclockers UK": "overclockers.co.uk",
    "Currys": "currys.co.uk",
    "AWD-IT": "awd-it.co.uk",
    "CCL": "cclonline.com",
}

# Direct retailer search routes are preferred. Google is only a fallback because its
# result markup changes frequently and can return no crawlable product links.
SEARCH_URLS = {
    "Scan": "https://www.scan.co.uk/search?q={query}",
    "Overclockers UK": "https://www.overclockers.co.uk/search?q={query}",
    "Currys": "https://www.currys.co.uk/search?q={query}",
    "AWD-IT": "https://www.awd-it.co.uk/catalogsearch/result/?q={query}",
    "CCL": "https://www.cclonline.com/search/?q={query}",
}


def _fetch(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _query(fp: PCFingerprint) -> str:
    terms = [x for x in (fp.cpu, fp.gpu, f"{fp.ram_gb}GB" if fp.ram_gb else "", "gaming PC") if x]
    return " ".join(terms)


def _jsonld_products(html: str, retailer: str, domain: str, page_url: str = "") -> list[MarketListing]:
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
                price = float(str(offers.get("price") or offers.get("lowPrice") or "").replace("£", "").replace(",", ""))
            except ValueError:
                continue
            title = str(node.get("name") or "").strip()
            url = str(node.get("url") or offers.get("url") or page_url or "").strip()
            if url:
                url = urljoin(f"https://www.{domain}/", url)
            if title and price > 0:
                found.append(MarketListing(retailer=retailer, title=title, price=price, url=url))
    return found


def _retailer_links(html: str, base_url: str, domain: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r'href=["\']([^"\'#]+)', html, re.I):
        url = urljoin(base_url, unescape(href))
        host = urlparse(url).netloc.lower()
        if domain not in host:
            continue
        # Avoid obvious account/help/category assets while allowing retailer-specific product routes.
        low = url.lower()
        if any(x in low for x in ("javascript:", "/account", "/login", "/help", "/basket", "/cart", ".jpg", ".png", ".svg")):
            continue
        if url not in seen:
            seen.add(url); links.append(url)
    return links


def collect_market_references(fp: PCFingerprint) -> list[MarketListing]:
    """Best-effort zero-paid-API UK retail comparison collector.

    Search each mainstream retailer directly, then inspect candidate pages for explicit
    Product JSON-LD. No search-snippet prices are accepted as market truth.
    """
    query = _query(fp)
    encoded = quote_plus(query)
    results: list[MarketListing] = []
    seen: set[tuple[str, str, float]] = set()

    for retailer, domain in RETAILERS.items():
        candidate_urls: list[str] = []
        try:
            search_url = SEARCH_URLS[retailer].format(query=encoded)
            search_html = _fetch(search_url)
            # Some retailer search pages themselves contain Product JSON-LD.
            for item in _jsonld_products(search_html, retailer, domain, search_url):
                key = (item.retailer, item.title.lower(), item.price)
                if key not in seen:
                    seen.add(key); results.append(item)
            candidate_urls.extend(_retailer_links(search_html, search_url, domain)[:20])
        except Exception:
            pass

        # Fallback discovery if the retailer search route is blocked or client-rendered.
        if not candidate_urls:
            try:
                google_url = f"https://www.google.com/search?q={quote_plus('site:' + domain + ' ' + query)}"
                google_html = _fetch(google_url)
                candidate_urls.extend(re.findall(r'https?://(?:www\.)?' + re.escape(domain) + r'/[^&"<> ]+', google_html, re.I)[:10])
            except Exception:
                pass

        for url in candidate_urls[:12]:
            try:
                html = _fetch(url)
            except Exception:
                continue
            for item in _jsonld_products(html, retailer, domain, url):
                key = (item.retailer, item.title.lower(), item.price)
                if key not in seen:
                    seen.add(key); results.append(item)
    return results
