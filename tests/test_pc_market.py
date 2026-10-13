import unittest

from commerce.pc_market import MarketListing, comparison_score, fingerprint_pc, market_value


class PCMarketTests(unittest.TestCase):
    def test_fingerprint_pc(self):
        fp = fingerprint_pc("Gaming PC AMD Ryzen 7 7800X3D RTX 5070 Ti 32GB DDR5 1TB NVMe SSD")
        self.assertIn("7800X3D", fp.cpu.upper())
        self.assertEqual(fp.gpu, "RTX 5070 TI")
        self.assertEqual(fp.ram_gb, 32)
        self.assertEqual(fp.storage_tb, 1.0)

    def test_live_intel_tiktok_title(self):
        fp = fingerprint_pc("GTR Gaming PC | Intel Core i5-12400F | RX 9070 XT 16GB GDDR6 | 32GB DDR4 3600MHz RAM | 1TB NVMe SSD")
        self.assertIn("I5-12400F", fp.cpu.upper())
        self.assertEqual(fp.gpu, "RX 9070 XT")
        self.assertEqual(fp.gpu_vram_gb, 16)
        self.assertEqual(fp.ram_gb, 32)
        self.assertEqual(fp.storage_tb, 1.0)
        self.assertEqual(fp.confidence, 4)

    def test_intel_name_variants_compare(self):
        target = fingerprint_pc("Intel Core i9-12900KF RTX 5070 12GB GDDR7 32GB DDR5 1TB NVMe SSD")
        other = fingerprint_pc("Intel i9 12900KF RTX 5070 12GB GDDR7 32GB DDR5 1TB SSD")
        score, tier, _ = comparison_score(target, other)
        self.assertGreaterEqual(score, 90)
        self.assertEqual(tier, "EXACT")

    def test_gpu_vram_is_extracted_near_gpu(self):
        fp = fingerprint_pc("Ryzen 7 7800X3D RTX 5060 Ti 8GB GDDR7 32GB DDR5 1TB NVMe")
        self.assertEqual(fp.gpu, "RTX 5060 TI")
        self.assertEqual(fp.gpu_vram_gb, 8)
        self.assertEqual(fp.ram_gb, 32)

    def test_market_value_uses_matching_cpu_gpu(self):
        target = fingerprint_pc("Ryzen 7 7800X3D RTX 5070 Ti 32GB DDR5 1TB SSD")
        listings = [
            MarketListing("A", "Ryzen 7 7800X3D RTX 5070 Ti 32GB DDR5 1TB SSD", 2200),
            MarketListing("B", "Ryzen 7 7800X3D RTX 5070 Ti 32GB DDR5 2TB SSD", 2400),
            MarketListing("C", "Ryzen 7 7800X3D RTX 5070 32GB DDR5 1TB SSD", 1500),
        ]
        value = market_value(1900, target, listings)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(len(value["comparables"]), 2)
        self.assertEqual(value["typical_price"], 2300)
        self.assertGreater(value["saving_pct"], 17)
        self.assertEqual(value["verdict"], "MARKET DEAL")
        self.assertEqual(value["comparison_basis"], "STRONG")
        self.assertEqual(value["rejected_count"], 0)

    def test_gpu_variant_mismatch_is_related_not_like_for_like(self):
        target = fingerprint_pc("Ryzen 7 7800X3D RTX 5070 Ti 32GB DDR5 1TB SSD")
        other = fingerprint_pc("Ryzen 7 7800X3D RTX 5070 32GB DDR5 1TB SSD")
        score, tier, reasons = comparison_score(target, other)
        self.assertGreaterEqual(score, 60)
        self.assertEqual(tier, "RELATED")
        self.assertIn("GPU close variant", reasons)

    def test_lower_ram_can_still_be_strong_when_cpu_gpu_match(self):
        target = fingerprint_pc("Ryzen 7 7800X3D RTX 5060 Ti 32GB DDR5 1TB SSD")
        other = fingerprint_pc("Ryzen 7 7800X3D RTX 5060 Ti 16GB DDR5 1TB SSD")
        score, tier, reasons = comparison_score(target, other)
        self.assertGreaterEqual(score, 75)
        self.assertEqual(tier, "STRONG")
        self.assertIn("RAM lower", reasons)

    def test_invalid_modern_gtx_label_is_normalised_to_rtx(self):
        fp = fingerprint_pc("Gaming PC Intel Core i5-12400F GTX 3050 16GB DDR4 1TB SSD")
        self.assertEqual(fp.gpu, "RTX 3050")

    def test_market_value_falls_back_to_related_products(self):
        target = fingerprint_pc("Intel Core i5-12400F RTX 3050 16GB DDR4 1TB SSD")
        listings = [
            MarketListing("A", "Intel Core i5-12400 RTX 3050 16GB DDR4 1TB SSD", 699),
            MarketListing("B", "Intel Core i5-12400F RTX 3060 16GB DDR4 1TB SSD", 749),
        ]

        value = market_value(599, target, listings)

        self.assertEqual(value["status"], "OK")
        self.assertEqual(value["comparison_basis"], "RELATED_FALLBACK")
        self.assertEqual(value["related_count"], 2)
        self.assertEqual(len(value["comparables"]), 2)
        self.assertLessEqual(value["confidence"], 65)

    def test_ram_does_not_capture_following_ssd_capacity(self):
        fp = fingerprint_pc(
            "Savitar Neo White Gaming Tower only- Core i7 16GB Ram "
            "128GB SSD 1000GB HDD GTX 3050 6GB"
        )
        self.assertEqual(fp.ram_gb, 16)
        self.assertEqual(fp.storage_tb, 1.0)
        self.assertEqual(fp.gpu, "RTX 3050")

    def test_ram_accepts_frequency_between_capacity_and_ram(self):
        fp = fingerprint_pc(
            "GTR Gaming PC | Intel Core i5-12400F | Radeon RX 9070 XT | "
            "32GB 3600MHz RAM | 1TB NVMe SSD"
        )
        self.assertEqual(fp.ram_gb, 32)
        self.assertEqual(fp.storage_tb, 1.0)

    def test_small_ssd_and_hdd_capacities_are_recognised(self):
        fp = fingerprint_pc(
            "Core i5 PC 16GB RAM 128GB SSD 500GB HDD"
        )
        self.assertEqual(fp.ram_gb, 16)
        self.assertEqual(fp.storage_tb, 0.5)


if __name__ == "__main__":
    unittest.main()
