from platforms.common.emoji_picker import apply_skin_tone, filter_emojis


def test_emoji_search_uses_unicode_names_and_aliases():
    assert "😂" in filter_emojis("SMILEYS", "laugh")
    assert "🔥" in filter_emojis("SMILEYS", "fire") or "🔥" in filter_emojis("ANIMALS", "fire")
    assert "⚽" in filter_emojis("ACTIVITY", "football")


def test_skin_tone_only_changes_supported_emoji():
    assert apply_skin_tone("👍", "MEDIUM") == "👍🏽"
    assert apply_skin_tone("❤️", "DARK") == "❤️"
    assert apply_skin_tone("👍", "DEFAULT") == "👍"
