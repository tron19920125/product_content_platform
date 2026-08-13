from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from product_content_platform.adapters.font_catalog import FontCatalog


class FontLicenseAuditTests(unittest.TestCase):
    def test_every_shipped_font_has_a_binary_and_verified_redistribution_metadata(self) -> None:
        font_root = Path(__file__).resolve().parents[2] / "frontend" / "public" / "fonts"
        with TemporaryDirectory() as temporary:
            catalog = FontCatalog(Path(temporary), font_root)
            fonts = catalog.list()

            self.assertGreaterEqual(len(fonts), 16)
            self.assertTrue((font_root / "OFL-1.1.txt").is_file())
            for font in fonts:
                with self.subTest(font=font["id"]):
                    self.assertTrue(font["license_verified"])
                    self.assertEqual("OFL-1.1", font["license"])
                    self.assertTrue(font["license_url"].startswith("https://github.com/"))
                    self.assertTrue(font["commercial_use"])
                    self.assertTrue(font["preview_available"])
                    self.assertIn("再分发", font["redistribution"])
                    binary = catalog.path(font["id"], download=False)
                    self.assertIsNotNone(binary)
                    self.assertGreater(binary.stat().st_size, 16_000)


if __name__ == "__main__":
    unittest.main()
