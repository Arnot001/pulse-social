"""Tests for deterministic X profile intelligence classification."""

from platforms.x.profile_intelligence import (
    ALL_TOPIC,
    OTHER_TOPIC,
    classify_text,
    inventory_counts,
    matches_topic,
    ranked_inventory,
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
