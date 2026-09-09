from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from .pc_market import MarketListing, PCFingerprint, comparison_score, fingerprint_pc

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"
RETAILERS={"Gotraka / GTR Gaming":"gotraka.com","Scan":"scan.co.uk","Overclockers UK":"overclockers.co.uk","Currys":"currys.co.uk","AWD-IT":"awd-it.co.uk","CCL":"cclonline.com","HP UK":"hp.com","PCSpecialist":"pcspecialist.co.uk","Stormforce":"stormforcegaming.co.uk","Build My Rig":"buildmyrig.uk","PC36":"pc36.co.uk","Highlander":"highlandercomputers.co.uk","CACTi PCs":"cactipcs.com","Utopia Computers":"utopiacomputers.co.uk","Gladiator PC":"gladiatorpc.co.uk","UK Gaming Computers":"ukgamingcomputers.co.uk","Andromeda PC Gaming":"andromedagaming.co.uk"}
LAST_DIAGNOSTICS=[]
def market_diagnostics(): return list(LAST_DIAGNOSTICS)
def _fetch(url,timeout=15):
    req=Request(url,headers={"User-Agent":USER_AGENT,"Accept-Language":"en-GB,en;q=0.9","Accept":"text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5"})
    with urlopen(req,timeout=timeout) as r:return r.read().decode("utf-8",errors="replace")
def _query(fp):return " ".join(x for x in (fp.cpu,fp.gpu,f"{fp.ram_gb}GB" if fp.ram_gb else "","gaming PC") if x)
def _same_domain(host,domain):
    host=host.lower().split(":",1)[0].removeprefix("www.");domain=domain.lower().removeprefix("www.");return host==domain or host.endswith("."+domain)
def _clean_candidate_url(raw,base_url,domain):
    raw=unescape(raw).replace("\\/","/").strip().strip('"\'<>')
    if not raw or raw.startswith(("javascript:","mailto:","#")):return ""
    if raw.startswith("//"):raw="https:"+raw
    elif raw.startswith("/"):raw=urljoin(base_url,raw)
    elif not raw.startswith(("http://","https://")):return ""
    p=urlparse(raw)
    return p._replace(fragment="").geturl() if _same_domain(p.netloc,domain) else ""
def _links_from_html(html,base_url,domain):
    out=[]
    for pat in (r'href\s*=\s*["\']([^"\']+)["\']',r'content\s*=\s*["\']([^"\']+)["\']',r'["\'](?:url|canonical_url|productUrl|product_url)["\']\s*:\s*["\']([^"\']+)["\']'):
        for raw in re.findall(pat,html,re.I):
            clean=_clean_candidate_url(raw,base_url,domain)
            if clean and clean not in out:out.append(clean)
    return out
def _search_engine_links(html,domain):
    out=[]
    for raw in re.findall(r'href\s*=\s*["\']([^"\']+)["\']',html,re.I):
        href=unescape(raw);poss=[href];qs=parse_qs(urlparse(href).query)
        if href.startswith("/url?") or "google.com/url?" in href:poss+=qs.get("q",[])+qs.get("url",[])
        for key in ("url","u","r"):poss+=qs.get(key,[])
        for c in poss:
            c=unquote(c);c="https:"+c if c.startswith("//") else c
            if c.startswith(("http://","https://")) and _same_domain(urlparse(c).netloc,domain):
                clean=urlparse(c)._replace(fragment="").geturl()
                if clean not in out:out.append(clean)
    for m in re.findall(r'https?://(?:www\.)?'+re.escape(domain)+r'[^\s"\'<>]+',html,re.I):
        clean=unescape(m).split("&amp;")[0]
        if clean not in out:out.append(clean)
    return out
def _looks_like_search_or_listing(title,url):return any(x in (title+" "+url).lower() for x in ("search:","search results","results found for","search?","/search/","?q=","collections/all","collections/search"))
def _has_target_components(text,target):
    fp=fingerprint_pc(text)
    if not fp.cpu or not fp.gpu:return False
    score,tier,_=comparison_score(target,fp);return score>=75 and tier in {"EXACT","STRONG"}
def _jsonld_products(html,retailer,domain,page_url="",target=None):
    found=[]
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S):
        try:payload=json.loads(unescape(raw).strip())
        except (ValueError,TypeError):continue
        stack=payload if isinstance(payload,list) else [payload]
        while stack:
            node=stack.pop()
            if isinstance(node,list):stack.extend(node);continue
            if not isinstance(node,dict):continue
            stack.extend(v for v in node.values() if isinstance(v,(dict,list)))
            if str(node.get("@type","")).lower()!="product":continue
            offers=node.get("offers") or {};offers=offers[0] if isinstance(offers,list) and offers else offers
            if not isinstance(offers,dict):continue
            try:price=float(str(offers.get("price") or offers.get("lowPrice") or "").replace(",",""))
            except (ValueError,TypeError):continue
            title=str(node.get("name") or "").strip();url=str(node.get("url") or offers.get("url") or page_url or "").strip()
            if url.startswith("/"):url=f"https://www.{domain}{url}"
            if title and 250<=price<=15000 and not _looks_like_search_or_listing(title,url) and (not target or _has_target_components(title,target)):found.append(MarketListing(retailer,title,price,url))
    return found
def _visible_product(html,retailer,page_url,target=None):
    m=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S);title=re.sub(r'<[^>]+>',' ',unescape(m.group(1))).strip() if m else ""
    if not title or _looks_like_search_or_listing(title,page_url):return []
    body=re.sub(r'<[^>]+>',' ',unescape(html));evidence=title+" "+body[:30000]
    if target and not _has_target_components(evidence,target):return []
    prices=[]
    for raw in re.findall(r'£\s*([0-9]{3,5}(?:,[0-9]{3})*(?:\.\d{2})?)',body):
        try:v=float(raw.replace(',',''))
        except ValueError:continue
        if 250<=v<=15000:prices.append(v)
    return [MarketListing(retailer,title[:300],min(prices),page_url)] if prices else []

def _gotraka_catalog(target):
    """Scan the complete public Shopify catalogue and match at variant level.

    A Gotraka product can contain many CPU/GPU variants. The old collector fingerprinted
    only the parent product title/body and stopped after six pages (1500 products), so
    valid SKUs such as 7800X3D + 5070 Ti could be invisible even though Gotraka sells them.
    """
    accepted=[];scanned=0;matching=0;pages=0
    for page in range(1,41):
        try:payload=json.loads(_fetch(f"https://www.gotraka.com/products.json?limit=250&page={page}",15))
        except Exception as exc:return accepted,f"Gotraka catalog error after {scanned} products ({type(exc).__name__})"
        products=payload.get("products") if isinstance(payload,dict) else None
        if not isinstance(products,list) or not products:break
        pages+=1
        for product in products:
            scanned+=1;title=str(product.get("title") or "").strip();body=re.sub(r'<[^>]+>',' ',unescape(str(product.get("body_html") or "")));handle=str(product.get("handle") or "").strip();pid=str(product.get("id") or "")
            variants=product.get("variants") if isinstance(product.get("variants"),list) else []
            for variant in variants or [{}]:
                # Variant titles/options frequently carry the actual CPU/GPU selection.
                option_text=" ".join(str(variant.get(k) or "") for k in ("title","option1","option2","option3","sku"))
                evidence=" ".join((title,option_text,body))
                vfp=fingerprint_pc(evidence)
                score,tier,_=comparison_score(target,vfp)
                if score<75 or tier not in {"EXACT","STRONG"}:continue
                matching+=1
                try:price=float(str(variant.get("price") or "0").replace(",",""))
                except (ValueError,TypeError):continue
                if not 250<=price<=15000:continue
                sku=str(variant.get("sku") or "").strip();vid=str(variant.get("id") or "").strip();identity=" | ".join(x for x in (f"PID {pid}" if pid else "",f"SKU {sku}" if sku else "",f"VID {vid}" if vid else "") if x)
                display=f"{title} [{identity}]" if identity else title
                accepted.append(MarketListing("Gotraka / GTR Gaming",display,price,f"https://www.gotraka.com/products/{handle}" if handle else "",vfp))
        if len(products)<250:break
    return accepted,f"Gotraka catalog: {scanned} products across {pages} pages, {matching} matching variants, {len(accepted)} priced variants accepted"

def _retailer_search_urls(domain,query):
    q=quote_plus(query);return [f"https://www.{domain}/search?q={q}",f"https://www.{domain}/search?query={q}",f"https://www.{domain}/search/{q}",f"https://{domain}/search?q={q}"]
def _discover_urls(domain,query):
    urls=[];notes=[]
    for search_url in _retailer_search_urls(domain,query):
        try:html=_fetch(search_url,10)
        except Exception as exc:notes.append(f"native {type(exc).__name__}");continue
        for link in _links_from_html(html,search_url,domain):
            if link not in urls and link.rstrip('/')!=search_url.rstrip('/'):urls.append(link)
        if urls:break
    for search_url in (f"https://www.google.com/search?q={quote_plus('site:'+domain+' '+query)}",f"https://www.bing.com/search?q={quote_plus('site:'+domain+' '+query)}"):
        try:html=_fetch(search_url,10)
        except Exception as exc:notes.append(f"engine {type(exc).__name__}");continue
        for link in _search_engine_links(html,domain):
            if link not in urls:urls.append(link)
    return urls,notes
def collect_market_references(fp):
    LAST_DIAGNOSTICS.clear();query=_query(fp);results=[];seen=set();gotraka,diag=_gotraka_catalog(fp);LAST_DIAGNOSTICS.append(diag)
    for item in gotraka:
        key=(item.retailer,item.title.lower(),item.price)
        if key not in seen:seen.add(key);results.append(item)
    for retailer,domain in RETAILERS.items():
        if retailer=="Gotraka / GTR Gaming":continue
        urls,notes=_discover_urls(domain,query)
        if not urls:
            detail=f" ({', '.join(notes[-2:])})" if notes else "";LAST_DIAGNOSTICS.append(f"{retailer}: discovery returned 0 product URLs{detail}");continue
        accepted=fetched=rejected=0
        for url in urls[:12]:
            if _looks_like_search_or_listing("",url):rejected+=1;continue
            try:html=_fetch(url,12);fetched+=1
            except Exception:continue
            items=_jsonld_products(html,retailer,domain,url,fp) or _visible_product(html,retailer,url,fp)
            if not items:rejected+=1
            for item in items:
                key=(item.retailer,item.title.lower(),item.price)
                if key not in seen:seen.add(key);results.append(item);accepted+=1
        LAST_DIAGNOSTICS.append(f"{retailer}: {len(urls)} URLs discovered, {fetched} product pages fetched, {accepted} matching products accepted, {rejected} rejected")
    return results
