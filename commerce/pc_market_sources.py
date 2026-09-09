from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from .pc_market import MarketListing, PCFingerprint

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"

# Mainstream UK retailers/builders. Failures are isolated per source.
RETAILERS = {
    "Scan": "scan.co.uk",
    "Overclockers UK": "overclockers.co.uk",
    "Currys": "currys.co.uk",
    "AWD-IT": "awd-it.co.uk",
    "CCL": "cclonline.com",
    "HP UK": "hp.com",
    "PCSpecialist": "pcspecialist.co.uk",
    "Stormforce": "stormforcegaming.co.uk",
    "Build My Rig": "buildmyrig.uk",
    "PC36": "pc36.co.uk",
    "Highlander": "highlandercomputers.co.uk",
    "CACTi PCs": "cactipcs.com",
    "Utopia Computers": "utopiacomputers.co.uk",
    "Gladiator PC": "gladiatorpc.co.uk",
    "UK Gaming Computers": "ukgamingcomputers.co.uk",
    "Andromeda PC Gaming": "andromedagaming.co.uk",
}

LAST_DIAGNOSTICS: list[str] = []


def _fetch(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
    })
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _query(fp: PCFingerprint) -> str:
    terms = [x for x in (fp.cpu, fp.gpu, f"{fp.ram_gb}GB" if fp.ram_gb else "", "gaming PC") if x]
    return " ".join(terms)


def _same_domain(host: str, domain: str) -> bool:
    host = host.lower().split(":", 1)[0].removeprefix("www.")
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def _clean_candidate_url(raw: str, base_url: str, domain: str) -> str:
    raw = unescape(raw).replace("\\/", "/").strip().strip('"\'<>')
    if not raw or raw.startswith(("javascript:", "mailto:", "#")):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(base_url, raw)
    elif not raw.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(raw)
    if not _same_domain(parsed.netloc, domain):
        return ""
    # Strip fragments/tracking but keep useful product query strings.
    return parsed._replace(fragment="").geturl()


def _links_from_html(html: str, base_url: str, domain: str) -> list[str]:
    """Extract same-domain URLs from hrefs, canonical metadata and embedded JSON."""
    candidates: list[str] = []
    patterns = (
        r'href\s*=\s*["\']([^"\']+)["\']',
        r'content\s*=\s*["\']([^"\']+)["\']',
        r'["\'](?:url|canonical_url|productUrl|product_url)["\']\s*:\s*["\']([^"\']+)["\']',
        r'https?:\\?/\\?/(?:www\\?\.)?' + re.escape(domain).replace(r'\.', r'\\?\.') + r'[^"\'<>\\ ]+',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            clean = _clean_candidate_url(raw, base_url, domain)
            if clean and clean not in candidates:
                candidates.append(clean)
    return candidates


def _search_engine_links(html: str, domain: str) -> list[str]:
    """Decode Google/Bing redirect links instead of expecting naked retailer URLs."""
    found: list[str] = []
    for raw in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I):
        href = unescape(raw)
        possibilities = [href]
        if href.startswith("/url?") or "google.com/url?" in href:
            qs = parse_qs(urlparse(href).query)
            possibilities.extend(qs.get("q", [])); possibilities.extend(qs.get("url", []))
        # Bing frequently wraps the destination in query params too.
        qs = parse_qs(urlparse(href).query)
        for key in ("url", "u", "r"):
            possibilities.extend(qs.get(key, []))
        for candidate in possibilities:
            candidate = unquote(candidate)
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            if not candidate.startswith(("http://", "https://")):
                continue
            parsed = urlparse(candidate)
            if _same_domain(parsed.netloc, domain):
                clean = parsed._replace(fragment="").geturl()
                if clean not in found:
                    found.append(clean)
    # Also catch literal URLs that are present in result text/JSON.
    for match in re.findall(r'https?://(?:www\.)?' + re.escape(domain) + r'[^\s"\'<>]+', html, re.I):
        clean = unescape(match).split("&amp;")[0]
        if clean not in found:
            found.append(clean)
    return found


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
            if not isinstance(offers, dict):
                continue
            try:
                price = float(str(offers.get("price") or offers.get("lowPrice") or "").replace(",", ""))
            except (ValueError, TypeError):
                continue
            title = str(node.get("name") or "").strip()
            url = str(node.get("url") or offers.get("url") or page_url or "").strip()
            if url.startswith("/"):
                url = f"https://www.{domain}{url}"
            if title and 250 <= price <= 15000:
                found.append(MarketListing(retailer=retailer, title=title, price=price, url=url))
    return found


def _visible_product(html: str, retailer: str, page_url: str) -> list[MarketListing]:
    """Conservative fallback for product pages without JSON-LD.

    Requires PC-ish title content and a plausible GBP price. This is deliberately not used
    on search-engine pages, so snippet prices never become market truth.
    """
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    title = re.sub(r'<[^>]+>', ' ', unescape(title_match.group(1))).strip() if title_match else ""
    body = re.sub(r'<[^>]+>', ' ', unescape(html))
    if not title or not re.search(r'(?i)(gaming\s*pc|desktop|computer|ryzen|geforce|radeon|rtx|rx\s*\d)', title + " " + body[:15000]):
        return []
    prices = []
    for raw in re.findall(r'£\s*([0-9]{3,5}(?:,[0-9]{3})*(?:\.\d{2})?)', body):
        try:
            value = float(raw.replace(',', ''))
        except ValueError:
            continue
        if 250 <= value <= 15000:
            prices.append(value)
    if not prices:
        return []
    return [MarketListing(retailer=retailer, title=title[:300], price=min(prices), url=page_url)]


def _retailer_search_urls(domain: str, query: str) -> list[str]:
    q = quote_plus(query)
    return [
        f"https://www.{domain}/search?q={q}",
        f"https://www.{domain}/search?query={q}",
        f"https://www.{domain}/search/{q}",
        f"https://{domain}/search?q={q}",
    ]


def _discover_urls(domain: str, query: str) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    notes: list[str] = []
    # First try retailer-native search. Many sites return product links even when their
    # search route differs; failures are expected and isolated.
    for search_url in _retailer_search_urls(domain, query):
        try:
            html = _fetch(search_url, timeout=10)
        except Exception as exc:
            notes.append(f"native {type(exc).__name__}")
            continue
        links = _links_from_html(html, search_url, domain)
        for link in links:
            if link not in urls and link.rstrip('/') != search_url.rstrip('/'):
                urls.append(link)
        if urls:
            break
    # Search-engine fallback. Decode redirect URLs rather than looking only for naked URLs.
    engine_queries = [
        f"https://www.google.com/search?q={quote_plus('site:' + domain + ' ' + query)}",
        f"https://www.bing.com/search?q={quote_plus('site:' + domain + ' ' + query)}",
    ]
    for search_url in engine_queries:
        try:
            html = _fetch(search_url, timeout=10)
        except Exception as exc:
            notes.append(f"engine {type(exc).__name__}")
            continue
        for link in _search_engine_links(html, domain):
            if link not in urls:
                urls.append(link)
    return urls, notes


def collect_market_references(fp: PCFingerprint) -> list[MarketListing]:
    """Best-effort zero-API UK retail comparison collector with diagnostics."""
    LAST_DIAGNOSTICS.clear()
    query = _query(fp)
    results: list[MarketListing] = []
    seen: set[tuple[str, str, float]] = set()
    for retailer, domain in RETAILERS.items():
        urls, notes = _discover_urls(domain, query)
        if not urls:
            detail = f" ({', '.join(notes[-2:])})" if notes else ""
            LAST_DIAGNOSTICS.append(f"{retailer}: discovery returned 0 product URLs{detail}")
            continue
        accepted = 0
        fetched = 0
        for url in urls[:12]:
            try:
                html = _fetch(url, timeout=12)
                fetched += 1
            except Exception:
                continue
            items = _jsonld_products(html, retailer, domain, url)
            if not items:
                items = _visible_product(html, retailer, url)
            for item in items:
                key = (item.retailer, item.title.lower(), item.price)
                if key not in seen:
                    seen.add(key); results.append(item); accepted += 1
        LAST_DIAGNOSTICS.append(f"{retailer}: {len(urls)} URLs discovered, {fetched} fetched, {accepted} priced products accepted")
    return results
