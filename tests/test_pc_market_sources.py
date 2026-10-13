import json

from commerce.pc_market import fingerprint_pc
from commerce import pc_market_sources


def test_has_target_components_accepts_related_pc():
    target = fingerprint_pc(
        "Intel Core i5-12400F RTX 3050 16GB DDR4 1TB SSD"
    )

    assert pc_market_sources._has_target_components(
        "Intel Core i5-12400 RTX 3050 16GB DDR4 512GB SSD",
        target,
    )


def test_has_target_components_rejects_unrelated_pc():
    target = fingerprint_pc(
        "Intel Core i5-12400F RTX 3050 16GB DDR4 1TB SSD"
    )

    assert not pc_market_sources._has_target_components(
        "AMD Ryzen 9 7950X RTX 4090 64GB DDR5 4TB SSD",
        target,
    )


def test_gotraka_catalog_keeps_related_variant(monkeypatch):
    target = fingerprint_pc(
        "Intel Core i5-12400F RTX 3050 16GB DDR4 1TB SSD"
    )

    payload = {
        "products": [
            {
                "id": 123,
                "title": "GTR Gaming PC",
                "body_html": "<p>16GB DDR4 1TB SSD</p>",
                "handle": "gtr-gaming-pc",
                "variants": [
                    {
                        "id": 456,
                        "title": "Intel Core i5-12400 / RTX 3050",
                        "option1": "Intel Core i5-12400",
                        "option2": "RTX 3050",
                        "option3": "16GB DDR4 1TB SSD",
                        "sku": "GTR-12400-3050",
                        "price": "699.00",
                    }
                ],
            }
        ]
    }

    calls = []

    def fake_fetch(url, timeout=15):
        calls.append(url)
        if "page=1" in url:
            return json.dumps(payload)
        return json.dumps({"products": []})

    monkeypatch.setattr(pc_market_sources, "_fetch", fake_fetch)

    listings, diagnostic = pc_market_sources._gotraka_catalog(target)

    assert len(listings) == 1
    assert listings[0].price == 699.0
    assert "1 matching variants" in diagnostic
    assert "1 priced variants accepted" in diagnostic
