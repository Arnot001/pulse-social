from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen

from .pc_market import MarketListing, PCFingerprint, fingerprint_pc

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"

# UK retailers/builders used as market references. We still require an explicit product price
# from the destination page; search snippets are discovery only, never admitted as market truth.
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
    "Highlander": "highlanderstore.co.uk",
    "CACTi PCs": "cactipcs.com",
}

LAST_DIAGNOSTICS: list[str] = []


def _fetch(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _query(fp: PCFingerprint) -> str:
    return " ".join(x for x in (fp.cpu, fp.gpu, f"{fp.ram_gb}GB" if fp.ram_gb else "", f"{fp.storage_tb:g}TB" if fp.storage_tb else "", "gaming PC") if x)


def _price_from_text(text: str) -> float | None:
    prices=[]
    for raw in re.findall(r"(?:£|GBP\s*)([1-9][0-9]{2,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", text, re.I):
        try:
            value=float(raw.replace(",",""))
            if 300 <= value <= 10000: prices.append(value)
        except ValueError: pass
    return min(prices) if prices else None


def _jsonld_products(html: str, retailer: str, base_url: str) -> list[MarketListing]:
    found=[]
    scripts=re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S)
    for raw in scripts:
        try: payload=json.loads(unescape(raw).strip())
        except (ValueError,TypeError): continue
        stack=payload if isinstance(payload,list) else [payload]
        while stack:
            node=stack.pop()
            if isinstance(node,list): stack.extend(node); continue
            if not isinstance(node,dict): continue
            stack.extend(v for v in node.values() if isinstance(v,(dict,list)))
            if str(node.get("@type","")).lower()!="product": continue
            offers=node.get("offers") or {}
            if isinstance(offers,list): offers=offers[0] if offers else {}
            try: price=float(str(offers.get("price") or offers.get("lowPrice") or "").replace(",",""))
            except (ValueError,TypeError): continue
            title=str(node.get("name") or "").strip(); url=urljoin(base_url,str(node.get("url") or offers.get("url") or "").strip())
            if title and price>0: found.append(MarketListing(retailer=retailer,title=title,price=price,url=url,fingerprint=fingerprint_pc(title)))
    return found


def _page_product(html: str, retailer: str, url: str, fp: PCFingerprint) -> MarketListing | None:
    products=_jsonld_products(html,retailer,url)
    if products: return products[0]
    title_match=re.search(r"<title[^>]*>(.*?)</title>",html,re.I|re.S)
    title=re.sub(r"<[^>]+>"," ",unescape(title_match.group(1))).strip() if title_match else ""
    page_fp=fingerprint_pc(title+" "+re.sub(r"<[^>]+>"," ",html[:300000]))
    # Only use visible-price fallback when CPU and GPU agree with the target.
    if fp.cpu and page_fp.cpu and re.sub(r"\W","",fp.cpu.lower())!=re.sub(r"\W","",page_fp.cpu.lower()): return None
    if fp.gpu and page_fp.gpu and re.sub(r"\W","",fp.gpu.lower())!=re.sub(r"\W","",page_fp.gpu.lower()): return None
    if not page_fp.cpu or not page_fp.gpu: return None
    price=_price_from_text(re.sub(r"<[^>]+>"," ",html[:300000]))
    return MarketListing(retailer=retailer,title=title or f"{fp.cpu} {fp.gpu} gaming PC",price=price,url=url,fingerprint=page_fp) if price else None


def _search_urls(domain: str, query: str) -> list[str]:
    urls=[]
    for engine in (
        f"https://www.google.com/search?q={quote_plus('site:'+domain+' '+query)}",
        f"https://www.bing.com/search?q={quote_plus('site:'+domain+' '+query)}",
    ):
        try: html=_fetch(engine)
        except Exception: continue
        patterns=[r'https?://(?:www\.)?'+re.escape(domain)+r'/[^&"<> ]+', r'https?://[^&"<> ]*'+re.escape(domain)+r'/[^&"<> ]+']
        for pattern in patterns:
            for raw in re.findall(pattern,html,re.I):
                clean=unescape(raw).replace("\\u0026","&").split("&")[0]
                clean=clean.rstrip(".,)\\")
                if clean not in urls: urls.append(clean)
    return urls[:8]


def collect_market_references(fp: PCFingerprint) -> list[MarketListing]:
    global LAST_DIAGNOSTICS
    LAST_DIAGNOSTICS=[]; query=_query(fp); results=[]; seen=set()
    for retailer,domain in RETAILERS.items():
        urls=_search_urls(domain,query)
        if not urls:
            LAST_DIAGNOSTICS.append(f"{retailer}: discovery returned 0 product URLs")
            continue
        accepted=0
        for url in urls:
            try: html=_fetch(url)
            except Exception as exc:
                LAST_DIAGNOSTICS.append(f"{retailer}: fetch blocked/failed ({type(exc).__name__})")
                continue
            item=_page_product(html,retailer,url,fp)
            if not item: continue
            key=(item.retailer,item.title.lower(),item.price)
            if key not in seen:
                seen.add(key); results.append(item); accepted+=1
        LAST_DIAGNOSTICS.append(f"{retailer}: {len(urls)} URLs discovered, {accepted} priced products accepted")
    return results


def market_diagnostics() -> list[str]:
    return list(LAST_DIAGNOSTICS)
