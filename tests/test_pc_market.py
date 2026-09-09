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
        self.assertEqual(value["rejected_count"], 1)

    def test_gpu_variant_mismatch_is_rejected(self):
        target = fingerprint_pc("Ryzen 7 7800X3D RTX 5070 Ti 32GB DDR5 1TB SSD")
        other = fingerprint_pc("Ryzen 7 7800X3D RTX 5070 32GB DDR5 1TB SSD")
        score, tier, reasons = comparison_score(target, other)
        self.assertEqual(score, 0)
        self.assertEqual(tier, "REJECT")
        self.assertIn("GPU mismatch", reasons)

    def test_lower_ram_is_not_used_as_strong_comparable(self):
        target = fingerprint_pc("Ryzen 7 7800X3D RTX 5060 Ti 32GB DDR5 1TB SSD")
        other = fingerprint_pc("Ryzen 7 7800X3D RTX 5060 Ti 16GB DDR5 1TB SSD")
        score, tier, _ = comparison_score(target, other)
        self.assertLess(score, 75)
        self.assertEqual(tier, "REJECT")


if __name__ == "__main__":
    unittest.main()
