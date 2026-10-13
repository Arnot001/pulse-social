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
    if gpu_match:
        gpu=re.sub(r"\s+"," ",gpu_match.group(1)).upper()
        modern_gtx=re.fullmatch(r"GTX\s+(\d{4})(.*)",gpu,re.I)
        if modern_gtx and int(modern_gtx.group(1)) >= 2000:
            gpu=f"RTX {modern_gtx.group(1)}{modern_gtx.group(2)}".strip()

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


def _cpu_similarity(left: str, right: str) -> tuple[int, str, bool]:
    a=_component_token(left); b=_component_token(right)
    if a==b:
        return 40,"CPU exact",True

    intel_a=re.fullmatch(r"i([3579])(\d{4,5})([a-z0-9]*)",a)
    intel_b=re.fullmatch(r"i([3579])(\d{4,5})([a-z0-9]*)",b)
    if intel_a and intel_b:
        class_a,model_a,suffix_a=intel_a.groups()
        class_b,model_b,suffix_b=intel_b.groups()
        if class_a==class_b and model_a==model_b:
            return 35,"CPU close variant",False
        gen_a=model_a[:2] if len(model_a)==5 else model_a[:1]
        gen_b=model_b[:2] if len(model_b)==5 else model_b[:1]
        if gen_a==gen_b and class_a==class_b:
            return 28,"CPU same generation/class",False
        if gen_a==gen_b and abs(int(class_a)-int(class_b)) <= 2:
            return 20,"CPU same generation",False
        return 0,"CPU mismatch",False

    amd_a=re.fullmatch(r"ryzen([3579])(\d{4,5})([a-z0-9]*)",a)
    amd_b=re.fullmatch(r"ryzen([3579])(\d{4,5})([a-z0-9]*)",b)
    if amd_a and amd_b:
        class_a,model_a,suffix_a=amd_a.groups()
        class_b,model_b,suffix_b=amd_b.groups()
        if class_a==class_b and model_a==model_b:
            return 35,"CPU close variant",False
        if model_a[:1]==model_b[:1] and class_a==class_b:
            return 28,"CPU same generation/class",False
        if model_a[:1]==model_b[:1] and abs(int(class_a)-int(class_b)) <= 2:
            return 20,"CPU same generation",False
        return 0,"CPU mismatch",False

    return 0,"CPU mismatch",False


def _gpu_similarity(left: str, right: str) -> tuple[int, str, bool]:
    a=_component_token(left); b=_component_token(right)
    if a==b:
        return 40,"GPU exact",True

    pattern=r"(rtx|gtx|rx)(\d{3,4})(ti|super|xt|gre)?"
    match_a=re.fullmatch(pattern,a)
    match_b=re.fullmatch(pattern,b)
    if not match_a or not match_b:
        return 0,"GPU mismatch",False

    family_a,model_a,suffix_a=match_a.groups()
    family_b,model_b,suffix_b=match_b.groups()
    if family_a != family_b:
        return 0,"GPU mismatch",False

    if model_a==model_b:
        return 32,"GPU close variant",False

    if len(model_a)==4 and len(model_b)==4 and model_a[:2]==model_b[:2]:
        delta=abs(int(model_a[-2:])-int(model_b[-2:]))
        if delta <= 10:
            return 24,"GPU adjacent tier",False
        if delta <= 20:
            return 18,"GPU nearby tier",False

    return 0,"GPU mismatch",False


def comparison_score(target: PCFingerprint, other: PCFingerprint) -> tuple[int,str,list[str]]:
    if not target.cpu or not target.gpu or not other.cpu or not other.gpu:
        return 0,"REJECT",["missing CPU/GPU"]

    cpu_score,cpu_reason,cpu_exact=_cpu_similarity(target.cpu,other.cpu)
    gpu_score,gpu_reason,gpu_exact=_gpu_similarity(target.gpu,other.gpu)
    if cpu_score == 0:
        return 0,"REJECT",[cpu_reason]
    if gpu_score == 0:
        return 0,"REJECT",[gpu_reason]

    score=cpu_score+gpu_score
    reasons=[cpu_reason,gpu_reason]

    if target.gpu_vram_gb is not None and other.gpu_vram_gb is not None:
        if target.gpu_vram_gb==other.gpu_vram_gb:
            score+=5; reasons.append("VRAM exact")
        elif other.gpu_vram_gb>target.gpu_vram_gb:
            score+=3; reasons.append("VRAM higher")
        else:
            score+=1; reasons.append("VRAM lower")

    if target.ram_gb is not None and other.ram_gb is not None:
        if target.ram_gb==other.ram_gb:
            score+=8; reasons.append("RAM exact")
        elif other.ram_gb>target.ram_gb:
            score+=5; reasons.append("RAM higher")
        elif other.ram_gb >= target.ram_gb/2:
            score+=3; reasons.append("RAM lower")
        else:
            reasons.append("RAM much lower")

    if target.storage_tb is not None and other.storage_tb is not None:
        if abs(target.storage_tb-other.storage_tb)<0.01:
            score+=7; reasons.append("storage exact")
        elif other.storage_tb>target.storage_tb:
            score+=4; reasons.append("storage higher")
        elif other.storage_tb >= target.storage_tb/2:
            score+=2; reasons.append("storage lower")
        else:
            reasons.append("storage much lower")

    score=max(0,min(100,score))

    # Exact means the core components match and every target supporting spec
    # that we know can also be verified as equal on the retailer listing.
    # Different/missing RAM, storage or VRAM may still be a strong comparable,
    # but must never masquerade as an exact like-for-like machine.
    core_exact=cpu_exact and gpu_exact
    supporting_exact=True

    for target_value, other_value in (
        (target.gpu_vram_gb, other.gpu_vram_gb),
        (target.ram_gb, other.ram_gb),
        (target.storage_tb, other.storage_tb),
    ):
        if target_value is not None:
            if other_value is None or abs(float(target_value)-float(other_value)) >= 0.01:
                supporting_exact=False
                break

    if core_exact and supporting_exact and score>=90:
        tier="EXACT"
    elif core_exact and score>=75:
        tier="STRONG"
    elif score>=60:
        tier="RELATED"
    else:
        tier="REJECT"

    return score,tier,reasons

def comparable(target: PCFingerprint,other: PCFingerprint)->bool:
    score,tier,_=comparison_score(target,other); return score>=75 and tier in {"EXACT","STRONG"}


def market_value(tiktok_price:float,target:PCFingerprint,listings:list[MarketListing])->dict:
    ranked=[]; rejected=0
    for listing in listings:
        fp=listing.fingerprint or fingerprint_pc(listing.title); listing.fingerprint=fp; score,tier,reasons=comparison_score(target,fp)
        if score>=60 and tier in {"EXACT","STRONG","RELATED"} and listing.price>0:
            ranked.append((listing,score,tier,reasons))
        else:
            rejected+=1

    if not ranked:
        return {
            "status":"NO_COMPARABLES",
            "confidence":0,
            "comparables":[],
            "ranked_comparables":[],
            "rejected_count":rejected,
        }

    deduped=[]; seen=set()
    for row in sorted(ranked,key=lambda x:x[1],reverse=True):
        listing=row[0]; key=(listing.retailer.lower(),_compact(listing.title),round(listing.price,2))
        if key not in seen:
            seen.add(key); deduped.append(row)

    exact=[r for r in deduped if r[2]=="EXACT"]
    strong=[r for r in deduped if r[2] in {"EXACT","STRONG"}]

    if len(exact)>=2:
        used=exact
        basis="EXACT"
    elif len(strong)>=2:
        used=strong
        basis="STRONG"
    else:
        used=deduped[:5]
        basis="RELATED_FALLBACK"

    prices=[r[0].price for r in used]
    typical=float(median(prices))
    saving=typical-tiktok_price
    saving_pct=saving/typical*100 if typical else 0
    avg=sum(r[1] for r in used)/len(used)
    confidence=min(100,round(30+min(len(used),5)*8+avg*.3))

    if basis=="RELATED_FALLBACK":
        confidence=min(confidence,65)

    verdict="EXCEPTIONAL MARKET VALUE" if saving_pct>=20 else "MARKET DEAL" if saving_pct>=10 else "GOOD VALUE" if saving_pct>=3 else "ABOVE MARKET" if saving_pct<=-10 else "AROUND MARKET"

    return {
        "status":"OK",
        "typical_price":typical,
        "market_low":min(prices),
        "market_high":max(prices),
        "saving":saving,
        "saving_pct":saving_pct,
        "verdict":verdict,
        "confidence":confidence,
        "comparison_basis":basis,
        "comparables":[r[0] for r in used],
        "ranked_comparables":[
            {"listing":r[0],"match_score":r[1],"match_tier":r[2],"match_reasons":r[3]}
            for r in used
        ],
        "exact_count":sum(1 for r in used if r[2]=="EXACT"),
        "strong_count":sum(1 for r in used if r[2]=="STRONG"),
        "related_count":sum(1 for r in used if r[2]=="RELATED"),
        "rejected_count":rejected,
    }
