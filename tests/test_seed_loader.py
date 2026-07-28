import tempfile
import unittest
from pathlib import Path

from app.crawler.seeds import load_faculty_seeds


class SeedLoaderTests(unittest.TestCase):
    def test_loads_valid_seed_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seeds.csv"
            path.write_text(
                "faculty_name,faculty_institution,faculty_homepage\n"
                "Ada Lovelace,Example University,https://example.edu/ada\n",
                encoding="utf-8",
            )

            seeds = load_faculty_seeds(path)

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].faculty_name, "Ada Lovelace")

    def test_rejects_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seeds.csv"
            path.write_text("faculty_name\nAda Lovelace\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_faculty_seeds(path)


if __name__ == "__main__":
    unittest.main()

