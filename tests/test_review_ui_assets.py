import json
import unittest
from pathlib import Path


UI_DIR = Path("app/review/ui")
DATA_DIR = UI_DIR / "data"


class ReviewUiAssetTests(unittest.TestCase):
    def test_review_ui_files_exist(self):
        for relative_path in ["index.html", "styles.css", "app.js", "README.md"]:
            self.assertTrue((UI_DIR / relative_path).exists(), relative_path)

    def test_bundled_jsonl_data_is_parseable(self):
        expected_files = [
            "people.jsonl",
            "relationships.jsonl",
            "organizations.jsonl",
            "evidence_sources.jsonl",
            "resolution_decisions.jsonl",
            "profile_enrichments.jsonl",
        ]

        for filename in expected_files:
            path = DATA_DIR / filename
            self.assertTrue(path.exists(), filename)
            with self.subTest(filename=filename):
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertGreater(len(rows), 0)

    def test_wetzstein_sample_counts_match_expected_pipeline_shape(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        relationships = read_jsonl(DATA_DIR / "relationships.jsonl")
        decisions = read_jsonl(DATA_DIR / "resolution_decisions.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")

        self.assertEqual(len(people), 87)
        self.assertEqual(len(relationships), 88)
        self.assertEqual(len(decisions), 2)
        self.assertEqual(len(enrichments), 51)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
