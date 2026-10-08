"""Tests for deterministic X profile intelligence classification."""

from platforms.x.profile_intelligence import (
    ALL_TOPIC,
    OTHER_TOPIC,
    classify_text,
    filter_inventory,
    inventory_counts,
    matches_search,
    matches_topic,
    ranked_inventory,
    search_terms,
)


def test_mufc_specific_topic_beats_generic_football():
    result = classify_text("Another Manchester United disaster at Old Trafford #MUFC football")
    assert result["topic"] == "mufc"
    assert "football" in result["topics"]
    assert result["confidence"] > 0.7


def test_nft_and_crypto_hashtags_classify_without_eth_substring_false_positive():
    assert classify_text("Minting this NFT on Ethereum #web3")["topic"] == "nft_crypto"
    assert classify_text("Whether this works is another question")["topic"] == OTHER_TOPIC


def test_politics_classification_handles_uk_terms():
    result = classify_text("Labour and Reform UK arguing in Parliament again")
    assert result["topic"] == "politics"


def test_pulse_tech_and_memes_are_separate_topics():
    assert classify_text("Pulse Social automation is running from Python on GitHub")["topic"] == "pulse_tech"
    assert classify_text("lol this meme is ridiculous #funny")["topic"] == "memes_humour"


def test_topic_matching_supports_all_and_secondary_topics():
    text = "Manchester United in the Premier League #MUFC"
    assert matches_topic(text, ALL_TOPIC)
    assert matches_topic(text, "mufc")
    assert matches_topic(text, "football")
    assert not matches_topic(text, "politics")


def test_inventory_counts_and_ranking():
    items = [
        {"topic": "politics"},
        {"topic": "mufc"},
        {"topic": "politics"},
        {},
    ]
    assert inventory_counts(items) == {"politics": 2, "mufc": 1, OTHER_TOPIC: 1}
    ranked = ranked_inventory(items)
    assert ranked[0] == ("politics", 2)


def test_search_supports_phrase_and_comma_separated_or_terms():
    assert search_terms("Old Trafford") == ["old trafford"]
    assert search_terms("nft, opensea, mint") == ["nft", "opensea", "mint"]
    assert matches_search("Watching United at Old Trafford", "old trafford")
    assert matches_search("Minted this on OpenSea", "nft, opensea, mint")
    assert not matches_search("Manchester United only", "nft, crypto")


def test_filter_inventory_combines_mode_topic_and_search_without_expanding_ids():
    items = [
        {"status_id": "1", "mode": "posts", "topic": "mufc", "text": "Glazers out at Old Trafford"},
        {"status_id": "2", "mode": "replies", "topic": "mufc", "text": "Glazers again"},
        {"status_id": "3", "mode": "posts", "topic": "politics", "text": "Glazers is not in this one"},
        {"status_id": "4", "mode": "posts", "topic": "mufc", "text": "Different United post"},
    ]
    result = filter_inventory(items, mode="posts", topic="mufc", query="glazers")
    assert [item["status_id"] for item in result] == ["1"]
