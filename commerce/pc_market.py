from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median


@dataclass(slots=True)
class PCFingerprint:
    cpu: str = ""
    gpu: str = ""
    ram_gb: int | None = None
    storage_tb: float | None = None
    gpu_vram_gb: int | None = None

    @property
    def confidence(self) -> int:
        return sum((bool(self.cpu), bool(self.gpu), self.ram_gb is not None, self.storage_tb is not None))


@dataclass(slots=True)
class MarketListing:
    retailer: str
    title: str
    price: float
    url: str = ""
    fingerprint: PCFingerprint | None = None


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _component_token(value: str) -> str:
    # Intel retailers mix "Core i5-12400F", "Intel i5 12400F" and "i5-12400F".
    token = _compact(value)
    token = re.sub(r"^(?:intel)?core", "", token)
    token = re.sub(r"^intel", "", token)
    return token


def _flatten_text(value, depth: int = 0) -> list[str]:
    if depth > 8 or value is None: return []
    if isinstance(value, str): return [value] if value.strip() else []
    if isinstance(value, (int, float, bool)): return [str(value)]
    if isinstance(value, dict):
        out=[]
        for key, child in value.items(): out.append(str(key).replace("_", " ")); out.extend(_flatten_text(child, depth+1))
        return out
    if isinstance(value, (list, tuple, set)):
        out=[]
        for child in value: out.extend(_flatten_text(child, depth+1))
        return out
    return []


def fingerprint_pc(title: str, specs: dict | None = None, raw: dict | None = None) -> PCFingerprint:
    parts=[title]
    if specs: parts.extend(_flatten_text(specs))
    if raw: parts.extend(_flatten_text(raw))
    lower=" ".join(parts).lower()

    # Keep the complete Intel model including the i5/i7/i9 family. The previous
    # regex accidentally captured only "Core i5" from titles such as i5-12400F.
    cpu_patterns=(
        r"(?:amd\s*)?ryzen\s*[3579]\s*[- ]?\d{4,5}[a-z0-9]*",
        r"(?:intel\s*)?core\s*i[3579]\s*[- ]?\d{4,5}[a-z]{0,3}",
        r"(?:intel\s*)?i[3579]\s*[- ]?\d{4,5}[a-z]{0,3}",
        r"(?:intel\s*)?core\s*ultra\s*[3579]\s*[- ]?\d{3}[a-z]{0,3}",
    )
    cpu=""
    for pattern in cpu_patterns:
        match=re.search(pattern,lower,re.I)
        if match:
            token=re.sub(r"\s+"," ",match.group(0)).strip().upper().replace("AMD ","")
            token=token.replace("RYZEN","Ryzen").replace("INTEL","Intel").replace("CORE","Core")
            cpu=token; break

    gpu=""; gpu_match=re.search(r"\b((?:rtx|gtx)\s*\d{3,4}(?:\s*ti|\s*super)?|rx\s*\d{4}(?:\s*xt|\s*gre)?)\b",lower,re.I)
    if gpu_match: gpu=re.sub(r"\s+"," ",gpu_match.group(1)).upper()

    ram=None; ram_values=[]
    for pattern in (r"(?:ram|memory)\D{0,18}(8|12|16|24|32|48|64|96|128)\s*gb",r"\b(8|12|16|24|32|48|64|96|128)\s*gb\s*ddr[345]\b",r"\b(8|12|16|24|32|48|64|96|128)\s*gb\s*(?:ram|memory)\b"):
        ram_values.extend(int(x) for x in re.findall(pattern,lower,re.I))
    if ram_values: ram=max(ram_values)

    storage=None; storage_tb=re.findall(r"\b(1|2|4|8)\s*tb\s*(?:nvme|m\.?2|ssd|storage|hard\s*drive)",lower,re.I)
    if storage_tb: storage=max(float(x) for x in storage_tb)
    else:
        storage_gb=re.findall(r"\b(256|512|1000|2000|4000)\s*gb\s*(?:nvme|m\.?2|ssd|storage)",lower,re.I)
        if storage_gb: storage=max(float(x)/1000 for x in storage_gb)

    gpu_vram=None
    if gpu_match:
        tail=lower[gpu_match.start():gpu_match.end()+55]; vm=re.search(r"\b(4|6|8|10|12|16|20|24|32)\s*gb\s*(?:gddr\d+x?|vram)\b",tail,re.I)
        if vm: gpu_vram=int(vm.group(1))
    return PCFingerprint(cpu=cpu,gpu=gpu,ram_gb=ram,storage_tb=storage,gpu_vram_gb=gpu_vram)


def comparison_score(target: PCFingerprint, other: PCFingerprint) -> tuple[int,str,list[str]]:
    score=0; reasons=[]
    if not target.cpu or not target.gpu or not other.cpu or not other.gpu: return 0,"REJECT",["missing CPU/GPU"]
    if _component_token(target.cpu)==_component_token(other.cpu): score+=40; reasons.append("CPU exact")
    else: return 0,"REJECT",["CPU mismatch"]
    if _component_token(target.gpu)==_component_token(other.gpu): score+=40; reasons.append("GPU exact")
    else: return 0,"REJECT",["GPU mismatch"]
    if target.gpu_vram_gb is not None and other.gpu_vram_gb is not None:
        if target.gpu_vram_gb==other.gpu_vram_gb: score+=5; reasons.append("VRAM exact")
        elif other.gpu_vram_gb<target.gpu_vram_gb: return 0,"REJECT",["VRAM lower"]
        else: score+=2; reasons.append("VRAM higher")
    if target.ram_gb is not None and other.ram_gb is not None:
        if other.ram_gb<target.ram_gb: return 0,"REJECT",["RAM lower"]
        if target.ram_gb==other.ram_gb: score+=7; reasons.append("RAM exact")
        else: score+=4; reasons.append("RAM higher")
    if target.storage_tb is not None and other.storage_tb is not None:
        if other.storage_tb<target.storage_tb: return 0,"REJECT",["storage lower"]
        if abs(target.storage_tb-other.storage_tb)<0.01: score+=5; reasons.append("storage exact")
        else: score+=3; reasons.append("storage higher")
    score=max(0,min(100,score)); tier="EXACT" if score>=90 else "STRONG" if score>=75 else "RELATED" if score>=60 else "REJECT"
    return score,tier,reasons


def comparable(target: PCFingerprint,other: PCFingerprint)->bool:
    score,tier,_=comparison_score(target,other); return score>=75 and tier in {"EXACT","STRONG"}


def market_value(tiktok_price:float,target:PCFingerprint,listings:list[MarketListing])->dict:
    ranked=[]; rejected=0
    for listing in listings:
        fp=listing.fingerprint or fingerprint_pc(listing.title); listing.fingerprint=fp; score,tier,reasons=comparison_score(target,fp)
        if score>=75 and tier in {"EXACT","STRONG"} and listing.price>0: ranked.append((listing,score,tier,reasons))
        else: rejected+=1
    if not ranked: return {"status":"NO_COMPARABLES","confidence":0,"comparables":[],"ranked_comparables":[],"rejected_count":rejected}
    deduped=[]; seen=set()
    for row in sorted(ranked,key=lambda x:x[1],reverse=True):
        listing=row[0]; key=(listing.retailer.lower(),_compact(listing.title),round(listing.price,2))
        if key not in seen: seen.add(key); deduped.append(row)
    exact=[r for r in deduped if r[2]=="EXACT"]; used=exact if len(exact)>=2 else deduped; prices=[r[0].price for r in used]
    typical=float(median(prices)); saving=typical-tiktok_price; saving_pct=saving/typical*100 if typical else 0; avg=sum(r[1] for r in used)/len(used); confidence=min(100,round(30+min(len(used),5)*8+avg*.3))
    verdict="EXCEPTIONAL MARKET VALUE" if saving_pct>=20 else "MARKET DEAL" if saving_pct>=10 else "GOOD VALUE" if saving_pct>=3 else "ABOVE MARKET" if saving_pct<=-10 else "AROUND MARKET"
    return {"status":"OK","typical_price":typical,"market_low":min(prices),"market_high":max(prices),"saving":saving,"saving_pct":saving_pct,"verdict":verdict,"confidence":confidence,"comparables":[r[0] for r in used],"ranked_comparables":[{"listing":r[0],"match_score":r[1],"match_tier":r[2],"match_reasons":r[3]} for r in used],"exact_count":sum(1 for r in used if r[2]=="EXACT"),"strong_count":sum(1 for r in used if r[2]=="STRONG"),"rejected_count":rejected}
