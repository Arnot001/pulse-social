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
    """Normalize CPU/GPU names without collapsing meaningful suffixes such as Ti/XT/GRE."""
    return _compact(value)


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

    gpu_vram = None
    if gpu_match:
        tail = lower[gpu_match.start():gpu_match.end() + 40]
        vm = re.search(r"\b(4|6|8|10|12|16|20|24|32)\s*gb\s*(?:gddr\d+x?)?\b", tail, re.I)
        if vm:
            gpu_vram = int(vm.group(1))

    return PCFingerprint(cpu=cpu, gpu=gpu, ram_gb=ram, storage_tb=storage, gpu_vram_gb=gpu_vram)


def comparison_score(target: PCFingerprint, other: PCFingerprint) -> tuple[int, str, list[str]]:
    """Return a conservative 0-100 hardware similarity score and match tier."""
    score = 0
    reasons: list[str] = []

    # CPU and GPU are mandatory for a trustworthy prebuilt-PC comparison.
    if not target.cpu or not target.gpu or not other.cpu or not other.gpu:
        return 0, "REJECT", ["missing CPU/GPU"]

    if _component_token(target.cpu) == _component_token(other.cpu):
        score += 40; reasons.append("CPU exact")
    else:
        return 0, "REJECT", ["CPU mismatch"]

    if _component_token(target.gpu) == _component_token(other.gpu):
        score += 40; reasons.append("GPU exact")
    else:
        return 0, "REJECT", ["GPU mismatch"]

    if target.gpu_vram_gb is not None and other.gpu_vram_gb is not None:
        if target.gpu_vram_gb == other.gpu_vram_gb:
            score += 5; reasons.append("VRAM exact")
        else:
            score -= 8; reasons.append("VRAM mismatch")

    if target.ram_gb is not None and other.ram_gb is not None:
        if target.ram_gb == other.ram_gb:
            score += 7; reasons.append("RAM exact")
        elif other.ram_gb > target.ram_gb:
            score += 4; reasons.append("RAM higher")
        else:
            score -= 8; reasons.append("RAM lower")

    if target.storage_tb is not None and other.storage_tb is not None:
        if abs(target.storage_tb - other.storage_tb) < 0.01:
            score += 5; reasons.append("storage exact")
        elif other.storage_tb > target.storage_tb:
            score += 3; reasons.append("storage higher")
        else:
            score -= 6; reasons.append("storage lower")

    # Exact CPU/GPU already earns 80. Missing secondary specs lower certainty but
    # should not throw away otherwise excellent market evidence.
    score = max(0, min(100, score))
    if score >= 90:
        tier = "EXACT"
    elif score >= 75:
        tier = "STRONG"
    elif score >= 60:
        tier = "RELATED"
    else:
        tier = "REJECT"
    return score, tier, reasons


def comparable(target: PCFingerprint, other: PCFingerprint) -> bool:
    score, tier, _ = comparison_score(target, other)
    return score >= 75 and tier in {"EXACT", "STRONG"}


def market_value(tiktok_price: float, target: PCFingerprint, listings: list[MarketListing]) -> dict:
    ranked: list[tuple[MarketListing, int, str, list[str]]] = []
    rejected = 0
    for listing in listings:
        fp = listing.fingerprint or fingerprint_pc(listing.title)
        listing.fingerprint = fp
        score, tier, reasons = comparison_score(target, fp)
        if score >= 75 and tier in {"EXACT", "STRONG"} and listing.price > 0:
            ranked.append((listing, score, tier, reasons))
        else:
            rejected += 1

    if not ranked:
        return {
            "status": "NO_COMPARABLES", "confidence": 0, "comparables": [],
            "ranked_comparables": [], "rejected_count": rejected,
        }

    # De-duplicate identical retailer/title/price results before calculating market value.
    deduped: list[tuple[MarketListing, int, str, list[str]]] = []
    seen: set[tuple[str, str, float]] = set()
    for row in sorted(ranked, key=lambda x: x[1], reverse=True):
        listing = row[0]
        key = (listing.retailer.lower(), _compact(listing.title), round(listing.price, 2))
        if key not in seen:
            seen.add(key); deduped.append(row)

    # Prefer exact matches when there are at least two; otherwise use exact + strong.
    exact = [row for row in deduped if row[2] == "EXACT"]
    used = exact if len(exact) >= 2 else deduped
    prices = [row[0].price for row in used]
    typical = float(median(prices))
    saving = typical - tiktok_price
    saving_pct = saving / typical * 100 if typical else 0.0
    avg_match = sum(row[1] for row in used) / len(used)
    confidence = min(100, round(30 + min(len(used), 5) * 8 + avg_match * 0.3))

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
        "comparables": [row[0] for row in used],
        "ranked_comparables": [
            {"listing": row[0], "match_score": row[1], "match_tier": row[2], "match_reasons": row[3]}
            for row in used
        ],
        "exact_count": sum(1 for row in used if row[2] == "EXACT"),
        "strong_count": sum(1 for row in used if row[2] == "STRONG"),
        "rejected_count": rejected,
    }
