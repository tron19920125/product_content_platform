from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from product_content_platform.adapters import LocalAssetStore
from product_content_platform.domain import DomainValidationError


class LocalAssetStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LocalAssetStore(Path(self.temp_dir.name), max_bytes=1024)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_uses_controlled_unique_directory(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        content = buffer.getvalue()
        relative_path = self.store.save("../product.png", content)
        resolved = self.store.resolve(relative_path)

        self.assertEqual("product.png", resolved.name)
        self.assertEqual(content, resolved.read_bytes())
        self.assertEqual(Path(self.temp_dir.name).resolve(), resolved.parents[1])

    def test_rejects_empty_and_oversized_files(self) -> None:
        with self.assertRaises(DomainValidationError):
            self.store.save("empty.png", b"")
        with self.assertRaises(DomainValidationError):
            self.store.save("large.png", b"x" * 1025)
        with self.assertRaises(DomainValidationError):
            self.store.save("fake.png", b"not-an-image")


if __name__ == "__main__":
    unittest.main()
