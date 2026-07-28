import json
import unittest
from pathlib import Path

from app.review.bundle import build_review_bundle


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

    def test_bundled_review_bundle_is_parseable(self):
        path = DATA_DIR / "review_bundle.json"
        self.assertTrue(path.exists())

        bundle = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(bundle["metadata"]["dataset_label"], "Wetzstein seed")
        self.assertEqual(len(bundle["people"]), 87)
        self.assertEqual(len(bundle["relationships"]), 88)
        self.assertEqual(len(bundle["profile_enrichments"]), 51)
        self.assertEqual(len(bundle["backfill_candidates"]), 35)

    def test_wetzstein_sample_counts_match_expected_pipeline_shape(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        relationships = read_jsonl(DATA_DIR / "relationships.jsonl")
        decisions = read_jsonl(DATA_DIR / "resolution_decisions.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")

        self.assertEqual(len(people), 87)
        self.assertEqual(len(relationships), 88)
        self.assertEqual(len(decisions), 2)
        self.assertEqual(len(enrichments), 51)

    def test_review_bundle_matches_jsonl_inputs(self):
        expected = build_review_bundle(DATA_DIR)
        actual = json.loads((DATA_DIR / "review_bundle.json").read_text(encoding="utf-8"))

        self.assertEqual(actual, expected)

    def test_review_bundle_tracks_backfill_and_reconciliation_cases(self):
        bundle = json.loads((DATA_DIR / "review_bundle.json").read_text(encoding="utf-8"))
        backfill_names = {candidate["person_name"] for candidate in bundle["backfill_candidates"]}
        reconciliation_pairs = {
            (decision["person_name"], decision["enrichment_person_name"])
            for decision in bundle["profile_reconciliation_decisions"]
        }

        self.assertIn("Jackie Yang", backfill_names)
        self.assertNotIn("Michael Broxton", backfill_names)
        self.assertIn(("Yang Zhen", "Yang Zheng"), reconciliation_pairs)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
