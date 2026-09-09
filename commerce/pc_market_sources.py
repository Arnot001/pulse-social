from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from .pc_market import MarketListing, PCFingerprint, fingerprint_pc

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"

RETAILERS = {
    "Scan": "scan.co.uk", "Overclockers UK": "overclockers.co.uk", "Currys": "currys.co.uk",
    "AWD-IT": "awd-it.co.uk", "CCL": "cclonline.com", "HP UK": "hp.com",
    "PCSpecialist": "pcspecialist.co.uk", "Stormforce": "stormforcegaming.co.uk",
    "Build My Rig": "buildmyrig.uk", "PC36": "pc36.co.uk", "Highlander": "highlandercomputers.co.uk",
    "CACTi PCs": "cactipcs.com", "Utopia Computers": "utopiacomputers.co.uk",
    "Gladiator PC": "gladiatorpc.co.uk", "UK Gaming Computers": "ukgamingcomputers.co.uk",
    "Andromeda PC Gaming": "andromedagaming.co.uk",
}
LAST_DIAGNOSTICS: list[str] = []


def market_diagnostics() -> list[str]: return list(LAST_DIAGNOSTICS)

def _fetch(url: str, timeout: int = 15) -> str:
    req=Request(url,headers={"User-Agent":USER_AGENT,"Accept-Language":"en-GB,en;q=0.9","Accept":"text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5"})
    with urlopen(req,timeout=timeout) as response: return response.read().decode("utf-8",errors="replace")

def _query(fp: PCFingerprint) -> str: return " ".join(x for x in (fp.cpu,fp.gpu,f"{fp.ram_gb}GB" if fp.ram_gb else "","gaming PC") if x)

def _same_domain(host: str,domain: str)->bool:
    host=host.lower().split(":",1)[0].removeprefix("www."); domain=domain.lower().removeprefix("www."); return host==domain or host.endswith("."+domain)

def _clean_candidate_url(raw:str,base_url:str,domain:str)->str:
    raw=unescape(raw).replace("\\/","/").strip().strip('"\'<>')
    if not raw or raw.startswith(("javascript:","mailto:","#")): return ""
    if raw.startswith("//"): raw="https:"+raw
    elif raw.startswith("/"): raw=urljoin(base_url,raw)
    elif not raw.startswith(("http://","https://")): return ""
    parsed=urlparse(raw)
    if not _same_domain(parsed.netloc,domain): return ""
    return parsed._replace(fragment="").geturl()

def _links_from_html(html:str,base_url:str,domain:str)->list[str]:
    candidates=[]
    for pattern in (r'href\s*=\s*["\']([^"\']+)["\']',r'content\s*=\s*["\']([^"\']+)["\']',r'["\'](?:url|canonical_url|productUrl|product_url)["\']\s*:\s*["\']([^"\']+)["\']'):
        for raw in re.findall(pattern,html,re.I):
            clean=_clean_candidate_url(raw,base_url,domain)
            if clean and clean not in candidates: candidates.append(clean)
    return candidates

def _search_engine_links(html:str,domain:str)->list[str]:
    found=[]
    for raw in re.findall(r'href\s*=\s*["\']([^"\']+)["\']',html,re.I):
        href=unescape(raw); possibilities=[href]; qs=parse_qs(urlparse(href).query)
        if href.startswith("/url?") or "google.com/url?" in href: possibilities+=qs.get("q",[])+qs.get("url",[])
        for key in ("url","u","r"): possibilities+=qs.get(key,[])
        for candidate in possibilities:
            candidate=unquote(candidate)
            if candidate.startswith("//"): candidate="https:"+candidate
            if candidate.startswith(("http://","https://")) and _same_domain(urlparse(candidate).netloc,domain):
                clean=urlparse(candidate)._replace(fragment="").geturl()
                if clean not in found: found.append(clean)
    for match in re.findall(r'https?://(?:www\.)?'+re.escape(domain)+r'[^\s"\'<>]+',html,re.I):
        clean=unescape(match).split("&amp;")[0]
        if clean not in found: found.append(clean)
    return found

def _looks_like_search_or_listing(title:str,url:str)->bool:
    text=(title+" "+url).lower()
    bad=("search:","search results","results found for","search?","/search/","?q=","collections/all","collections/search")
    return any(x in text for x in bad)

def _has_target_components(text:str,target:PCFingerprint)->bool:
    fp=fingerprint_pc(text)
    # Product evidence must contain both target CPU and GPU. This prevents a search
    # page mentioning the query in its title from ever becoming a market price.
    if not fp.cpu or not fp.gpu: return False
    from .pc_market import comparison_score
    score,tier,_=comparison_score(target,fp)
    return score>=75 and tier in {"EXACT","STRONG"}

def _jsonld_products(html:str,retailer:str,domain:str,page_url:str="",target:PCFingerprint|None=None)->list[MarketListing]:
    found=[]
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S):
        try: payload=json.loads(unescape(raw).strip())
        except (ValueError,TypeError): continue
        stack=payload if isinstance(payload,list) else [payload]
        while stack:
            node=stack.pop()
            if isinstance(node,list): stack.extend(node); continue
            if not isinstance(node,dict): continue
            stack.extend(v for v in node.values() if isinstance(v,(dict,list)))
            if str(node.get("@type","")).lower()!="product": continue
            offers=node.get("offers") or {}; offers=offers[0] if isinstance(offers,list) and offers else offers
            if not isinstance(offers,dict): continue
            try: price=float(str(offers.get("price") or offers.get("lowPrice") or "").replace(",",""))
            except (ValueError,TypeError): continue
            title=str(node.get("name") or "").strip(); url=str(node.get("url") or offers.get("url") or page_url or "").strip()
            if url.startswith("/"): url=f"https://www.{domain}{url}"
            if not title or not 250<=price<=15000 or _looks_like_search_or_listing(title,url): continue
            if target and not _has_target_components(title,target): continue
            found.append(MarketListing(retailer=retailer,title=title,price=price,url=url))
    return found

def _visible_product(html:str,retailer:str,page_url:str,target:PCFingerprint|None=None)->list[MarketListing]:
    title_match=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S); title=re.sub(r'<[^>]+>',' ',unescape(title_match.group(1))).strip() if title_match else ""
    if not title or _looks_like_search_or_listing(title,page_url): return []
    body=re.sub(r'<[^>]+>',' ',unescape(html)); evidence=(title+" "+body[:30000])
    if target and not _has_target_components(evidence,target): return []
    prices=[]
    for raw in re.findall(r'£\s*([0-9]{3,5}(?:,[0-9]{3})*(?:\.\d{2})?)',body):
        try: value=float(raw.replace(',',''))
        except ValueError: continue
        if 250<=value<=15000: prices.append(value)
    # Visible-page fallback is deliberately conservative. Product JSON-LD is preferred;
    # if we must use visible text, only a genuine product page with matching hardware qualifies.
    return [MarketListing(retailer=retailer,title=title[:300],price=min(prices),url=page_url)] if prices else []

def _retailer_search_urls(domain:str,query:str)->list[str]:
    q=quote_plus(query); return [f"https://www.{domain}/search?q={q}",f"https://www.{domain}/search?query={q}",f"https://www.{domain}/search/{q}",f"https://{domain}/search?q={q}"]

def _discover_urls(domain:str,query:str)->tuple[list[str],list[str]]:
    urls=[]; notes=[]
    for search_url in _retailer_search_urls(domain,query):
        try: html=_fetch(search_url,timeout=10)
        except Exception as exc: notes.append(f"native {type(exc).__name__}"); continue
        for link in _links_from_html(html,search_url,domain):
            if link not in urls and link.rstrip('/')!=search_url.rstrip('/'): urls.append(link)
        if urls: break
    for search_url in (f"https://www.google.com/search?q={quote_plus('site:'+domain+' '+query)}",f"https://www.bing.com/search?q={quote_plus('site:'+domain+' '+query)}"):
        try: html=_fetch(search_url,timeout=10)
        except Exception as exc: notes.append(f"engine {type(exc).__name__}"); continue
        for link in _search_engine_links(html,domain):
            if link not in urls: urls.append(link)
    return urls,notes

def collect_market_references(fp:PCFingerprint)->list[MarketListing]:
    LAST_DIAGNOSTICS.clear(); query=_query(fp); results=[]; seen=set()
    for retailer,domain in RETAILERS.items():
        urls,notes=_discover_urls(domain,query)
        if not urls:
            detail=f" ({', '.join(notes[-2:])})" if notes else ""; LAST_DIAGNOSTICS.append(f"{retailer}: discovery returned 0 product URLs{detail}"); continue
        accepted=0; fetched=0; rejected=0
        for url in urls[:12]:
            if _looks_like_search_or_listing("",url): rejected+=1; continue
            try: html=_fetch(url,timeout=12); fetched+=1
            except Exception: continue
            items=_jsonld_products(html,retailer,domain,url,fp) or _visible_product(html,retailer,url,fp)
            if not items: rejected+=1
            for item in items:
                key=(item.retailer,item.title.lower(),item.price)
                if key not in seen: seen.add(key); results.append(item); accepted+=1
        LAST_DIAGNOSTICS.append(f"{retailer}: {len(urls)} URLs discovered, {fetched} product pages fetched, {accepted} matching products accepted, {rejected} rejected")
    return results
