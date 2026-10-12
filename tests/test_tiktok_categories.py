from commerce.tiktok import categories


def taxonomy_html():
    return """
    <html>
      <script>
      {
        "data": {
          "categories": [
            {
              "category_id": "100",
              "category_name": "Phones & Electronics",
              "category_name_en": "phones-electronics",
              "category_level": 1,
              "parent_category_id": "0",
              "is_leaf": false
            },
            {
              "category_id": "101",
              "category_name": "Phones",
              "category_name_en": "phones",
              "category_level": 2,
              "parent_category_id": "100",
              "is_leaf": true
            }
          ]
        }
      }
      </script>
    </html>
    """


def test_fetch_categories_reads_browser_owned_shop_html(monkeypatch):
    calls = []
    monkeypatch.setattr(
        categories,
        "read_tiktok_shop_html",
        lambda: calls.append(True) or taxonomy_html(),
    )

    result = categories.fetch_categories()

    assert calls == [True]
    assert [item.category_id for item in result] == ["100", "101"]
    assert [item.category_id for item in categories.roots(result)] == ["100"]
    assert [item.category_id for item in categories.children_of(result, "100")] == ["101"]


def test_fetch_categories_rejects_other_taxonomy_urls_before_browser_read(monkeypatch):
    monkeypatch.setattr(
        categories,
        "read_tiktok_shop_html",
        lambda: (_ for _ in ()).throw(AssertionError("browser must not be read")),
    )

    import pytest
    with pytest.raises(ValueError):
        categories.fetch_categories(
            "https://shop.tiktok.com/gb/c/phones-electronics/100"
        )
