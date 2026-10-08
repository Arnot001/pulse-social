"""Local, deterministic topic classification for X profile intelligence."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

ALL_TOPIC = "all"
OTHER_TOPIC = "other"

TOPIC_LABELS = {
    ALL_TOPIC: "ALL TOPICS",
    "mufc": "MUFC / Manchester United",
    "nft_crypto": "NFT / Crypto",
    "politics": "Politics",
    "football": "Football (other)",
    "pulse_tech": "Pulse / Tech",
    "memes_humour": "Memes / Humour",
    OTHER_TOPIC: "Other / Unclassified",
}

# Ordered deliberately: specific categories win ties against broad categories.
TOPIC_RULES = (
    (
        "mufc",
        (
            "#mufc", "#manutd", "#manchesterunited", "@manutd",
            "manchester united", "man utd", "man united", "old trafford",
            "red devils", "the reds",
        ),
    ),
    (
        "nft_crypto",
        (
            "#nft", "#crypto", "#bitcoin", "#btc", "#ethereum", "#eth", "#web3",
            "nft", "crypto", "bitcoin", "btc", "ethereum", "eth", "web3",
            "opensea", "mint", "minting", "token", "blockchain", "wallet",
        ),
    ),
    (
        "politics",
        (
            "#politics", "#labour", "#tories", "#reform", "#maga",
            "politics", "political", "labour", "tory", "tories", "conservative",
            "reform uk", "parliament", "prime minister", "election", "government",
            "starmer", "farage", "trump", "biden", "mp",
        ),
    ),
    (
        "football",
        (
            "#football", "#epl", "#premierleague", "#ucl", "#mancity",
            "football", "soccer", "premier league", "champions league", "epl",
            "arsenal", "liverpool", "chelsea", "manchester city", "man city",
            "mancity", "tottenham", "spurs", "newcastle", "everton",
        ),
    ),
    (
        "pulse_tech",
        (
            "#ai", "#tech", "#python", "#openai", "#chatgpt",
            "pulse", "pulse social", "pdh", "ai", "openai", "chatgpt",
            "codex", "python", "github", "software", "automation", "app",
        ),
    ),
    (
        "memes_humour",
        (
            "#meme", "#memes", "#funny", "#comedy", "#darkhumour",
            "meme", "memes", "funny", "comedy", "dark humour", "darkhumour",
            "lmao", "lol", "gif",
        ),
    ),
)

_WORD_RE = re.compile(r"[a-z0-9_']+")
_HASHTAG_RE = re.compile(r"#([a-z0-9_]+)", re.IGNORECASE)


def _normalise(text: str) -> str:
    return " ".join((text or "").casefold().replace("’", "'").split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def topic_scores(text: str) -> dict[str, int]:
    """Return deterministic category scores for one status body."""
    clean = _normalise(text)
    if not clean:
        return {}
    hashtags = {match.casefold() for match in _HASHTAG_RE.findall(clean)}
    tokens = set(_WORD_RE.findall(clean))
    scores: dict[str, int] = {}

    for key, terms in TOPIC_RULES:
        score = 0
        for raw_term in terms:
            term = raw_term.casefold()
            if term.startswith("#"):
                if term[1:] in hashtags:
                    score += 4
            elif term.startswith("@"):
                if _contains_phrase(clean, term):
                    score += 4
            elif " " in term:
                if _contains_phrase(clean, term):
                    score += 3
            elif term in tokens:
                score += 2
        if score:
            scores[key] = score
    return scores


def classify_text(text: str) -> dict:
    """Return primary topic, confidence, matched topics and raw scores."""
    scores = topic_scores(text)
    if not scores:
        return {
            "topic": OTHER_TOPIC,
            "label": TOPIC_LABELS[OTHER_TOPIC],
            "confidence": 0.50,
            "topics": [OTHER_TOPIC],
            "scores": {},
        }

    priority = {key: index for index, (key, _terms) in enumerate(TOPIC_RULES)}
    ranked = sorted(scores, key=lambda key: (-scores[key], priority.get(key, 999)))
    primary = ranked[0]
    best = scores[primary]
    confidence = min(0.98, 0.58 + (best * 0.06))
    return {
        "topic": primary,
        "label": TOPIC_LABELS[primary],
        "confidence": round(confidence, 2),
        "topics": ranked,
        "scores": scores,
    }


def matches_topic(text: str, topic: str) -> bool:
    if topic == ALL_TOPIC:
        return True
    result = classify_text(text)
    return topic == result["topic"] or topic in result["topics"]


def search_terms(query: str) -> list[str]:
    """Return case-folded search terms. Commas mean OR; otherwise text is one phrase."""
    clean = (query or "").strip().casefold()
    if not clean:
        return []
    if "," in clean:
        return [term.strip() for term in clean.split(",") if term.strip()]
    return [clean]


def matches_search(text: str, query: str) -> bool:
    """Case-insensitive literal word/phrase search across scanned status text."""
    terms = search_terms(query)
    if not terms:
        return True
    haystack = _normalise(text)
    return any(term in haystack for term in terms)


def filter_inventory(
    items: Iterable[dict],
    *,
    mode: str | None = None,
    topic: str = ALL_TOPIC,
    query: str = "",
) -> list[dict]:
    """Filter the saved scan without ever inventing or expanding status IDs."""
    matches = []
    for item in items:
        if mode and item.get("mode") != mode:
            continue
        if topic != ALL_TOPIC and item.get("topic") != topic:
            continue
        if not matches_search(str(item.get("text") or ""), query):
            continue
        matches.append(item)
    return matches


def inventory_counts(items: Iterable[dict]) -> dict[str, int]:
    counter = Counter(str(item.get("topic") or OTHER_TOPIC) for item in items)
    return dict(counter)


def ranked_inventory(items: Iterable[dict]) -> list[tuple[str, int]]:
    counts = inventory_counts(items)
    return sorted(
        counts.items(),
        key=lambda pair: (-pair[1], TOPIC_LABELS.get(pair[0], pair[0]).casefold()),
    )
