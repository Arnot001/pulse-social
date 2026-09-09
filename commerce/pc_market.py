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


def fingerprint_pc(title: str, specs: dict | None = None) -> PCFingerprint:
    specs = specs or {}
    text = " ".join([title] + [f"{k} {v}" for k, v in specs.items()])
    lower = text.lower()

    cpu_patterns = (
        r"ryzen\s*[3579]\s*[- ]?(\d{4,5}[a-z0-9]*)",
        r"(?:intel\s*)?core\s*(?:ultra\s*)?[3579]\s*[- ]?(\d{4,5}[a-z0-9]*)",
    )
    cpu = ""
    for pattern in cpu_patterns:
        match = re.search(pattern, lower, re.I)
        if match:
            token = match.group(0)
            cpu = re.sub(r"\s+", " ", token).strip().upper().replace("RYZEN", "Ryzen").replace("CORE", "Core").replace("INTEL", "Intel")
            break

    gpu = ""
    gpu_match = re.search(r"\b((?:rtx|gtx)\s*\d{3,4}(?:\s*ti|\s*super)?|rx\s*\d{4}(?:\s*xt|\s*gre)?)\b", lower, re.I)
    if gpu_match:
        gpu = re.sub(r"\s+", " ", gpu_match.group(1)).upper()

    ram = None
    ram_matches = re.findall(r"\b(8|12|16|24|32|48|64|96|128)\s*gb\s*(?:ddr[345])?\b", lower, re.I)
    if ram_matches:
        ram = max(int(x) for x in ram_matches)

    storage = None
    tb = re.findall(r"\b(1|2|4|8)\s*tb\s*(?:nvme|m\.?2|ssd)?\b", lower, re.I)
    if tb:
        storage = max(float(x) for x in tb)
    else:
        gb = re.findall(r"\b(256|512|1000|2000|4000)\s*gb\s*(?:nvme|m\.?2|ssd)\b", lower, re.I)
        if gb:
            storage = max(float(x) / 1000 for x in gb)

    return PCFingerprint(cpu=cpu, gpu=gpu, ram_gb=ram, storage_tb=storage)


def comparable(target: PCFingerprint, other: PCFingerprint) -> bool:
    if target.confidence < 2 or other.confidence < 2:
        return False
    if target.cpu and other.cpu and _compact(target.cpu) != _compact(other.cpu):
        return False
    if target.gpu and other.gpu and _compact(target.gpu) != _compact(other.gpu):
        return False
    if target.ram_gb and other.ram_gb and other.ram_gb < target.ram_gb:
        return False
    return True


def market_value(tiktok_price: float, target: PCFingerprint, listings: list[MarketListing]) -> dict:
    matches = []
    for listing in listings:
        fp = listing.fingerprint or fingerprint_pc(listing.title)
        if comparable(target, fp):
            matches.append(listing)
    prices = [x.price for x in matches if x.price > 0]
    if not prices:
        return {"status": "NO_COMPARABLES", "confidence": 0, "comparables": []}
    typical = float(median(prices))
    saving = typical - tiktok_price
    saving_pct = saving / typical * 100 if typical else 0.0
    confidence = min(100, 35 + len(prices) * 15 + min(target.confidence, 4) * 5)
    if saving_pct >= 20:
        verdict = "EXCEPTIONAL MARKET VALUE"
    elif saving_pct >= 10:
        verdict = "MARKET DEAL"
    elif saving_pct >= 3:
        verdict = "GOOD VALUE"
    elif saving_pct <= -10:
        verdict = "ABOVE MARKET"
    else:
        verdict = "AROUND MARKET"
    return {
        "status": "OK",
        "typical_price": typical,
        "market_low": min(prices),
        "market_high": max(prices),
        "saving": saving,
        "saving_pct": saving_pct,
        "verdict": verdict,
        "confidence": confidence,
        "comparables": matches,
    }
