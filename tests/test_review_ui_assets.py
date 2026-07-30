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
            "backfill_candidates.jsonl",
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

        self.assertEqual(
            bundle["metadata"]["dataset_label"],
            "Stanford faculty pilots: Gordon Wetzstein + Jiajun Wu + Maneesh Agrawala",
        )
        self.assertEqual(len(bundle["people"]), 183)
        self.assertEqual(len(bundle["relationships"]), 184)
        self.assertEqual(len(bundle["profile_enrichments"]), 155)
        self.assertEqual(len(bundle["backfill_candidates"]), 25)

    def test_review_ui_labels_distinguish_enrichment_and_profile_urls(self):
        index_html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("Manual enrichments", index_html)
        self.assertIn("Profile URLs found", index_html)
        self.assertIn("Professor", index_html)
        self.assertIn("All professors", index_html)
        self.assertIn("Has profile URL", index_html)
        self.assertIn("professorFilter", app_js)
        self.assertIn("professorName(record)", app_js)
        self.assertIn("renderMetrics(records)", app_js)
        self.assertIn("filteredDecisionCount(personIds)", app_js)
        self.assertIn("filteredProfileEnrichmentCount(personIds)", app_js)
        self.assertIn("filteredPeopleWithProfileUrls(personIds)", app_js)
        self.assertIn("filteredBackfillCount(personIds)", app_js)
        self.assertIn("renderBundleMetrics()", app_js)
        self.assertIn("Review relationship", app_js)
        self.assertIn("renderRelationshipReviewCard(reviewDecision)", app_js)
        self.assertIn("renderEmptyPersonDetail()", app_js)
        self.assertIn("profileLinkKind(url, label)", app_js)
        self.assertIn("profileLinkIcon(profileKind)", app_js)
        self.assertIn("Google Scholar", app_js)
        self.assertIn("PhD Student", app_js)
        self.assertIn("Alumni - Role Unknown", app_js)
        self.assertIn("Single source", app_js)

    def test_combined_sample_counts_match_expected_pipeline_shape(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        relationships = read_jsonl(DATA_DIR / "relationships.jsonl")
        decisions = read_jsonl(DATA_DIR / "resolution_decisions.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")

        self.assertEqual(len(people), 183)
        self.assertEqual(len(relationships), 184)
        self.assertEqual(len(decisions), 3)
        self.assertEqual(len(enrichments), 155)
        self.assertEqual(
            {relationship["professor_name"] for relationship in relationships},
            {"Gordon Wetzstein", "Jiajun Wu", "Maneesh Agrawala"},
        )

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

        self.assertNotIn("Jackie Yang", backfill_names)
        self.assertIn("Julie Chang", backfill_names)
        self.assertIn("Keenan Molner", backfill_names)
        self.assertNotIn("Kimo Johnson", backfill_names)
        self.assertNotIn("Hayato Ikoma", backfill_names)
        self.assertNotIn("Michael Broxton", backfill_names)
        self.assertIn(("Yang Zhen", "Yang Zheng"), reconciliation_pairs)

    def test_hayato_ikoma_manual_enrichment_is_imported(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")

        hayato = next(person for person in people if person["display_name"] == "Hayato Ikoma")
        enrichment = next(item for item in enrichments if item["person_name"] == "Hayato Ikoma")

        self.assertIn("https://hayatoikoma.github.io/", hayato["profile_urls"])
        self.assertEqual(enrichment["personal_website_url"], "https://hayatoikoma.github.io/")
        self.assertEqual(enrichment["linkedin_url"], "https://www.linkedin.com/in/hayato-ikoma-78b39b57/")

    def test_qa_safe_enrichments_are_imported_without_linkedin_holdouts(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")
        backfill_names = {candidate["person_name"] for candidate in read_jsonl(DATA_DIR / "backfill_candidates.jsonl")}

        enrichments_by_name = {item["person_name"]: item for item in enrichments}
        people_by_name = {person["display_name"]: person for person in people}

        self.assertEqual(enrichments_by_name["Ana Serrano"]["final_url"], "https://ana-serrano.github.io/")
        self.assertEqual(enrichments_by_name["Shikhar Shrestha"]["final_url"], "https://www.ambient.ai/ai-info")
        self.assertIn("https://ana-serrano.github.io/", people_by_name["Ana Serrano"]["profile_urls"])
        self.assertNotIn("Julie Chang", enrichments_by_name)
        self.assertNotIn("Keenan Molner", enrichments_by_name)
        self.assertIn("Julie Chang", backfill_names)
        self.assertIn("Keenan Molner", backfill_names)

    def test_jiajun_wu_roster_bundle_is_active_and_deduped(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        relationships = read_jsonl(DATA_DIR / "relationships.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")

        jiajun_relationships = [
            relationship
            for relationship in relationships
            if relationship["professor_name"] == "Jiajun Wu"
        ]
        eric = [person for person in people if person["display_name"] == "Eric Ryan Chan"]

        self.assertEqual(len(jiajun_relationships), 40)
        self.assertEqual(len(eric), 1)
        self.assertEqual(eric[0]["resolution_status"], "cross_dataset_profile_url_merge")
        self.assertIn(
            "person:dc86baaea3c7176d",
            {relationship["person_id"] for relationship in jiajun_relationships},
        )
        self.assertIn("Raven Huang", {item["person_name"] for item in enrichments})

    def test_maneesh_agrawala_roster_bundle_is_active_and_deduped(self):
        people = read_jsonl(DATA_DIR / "people.jsonl")
        relationships = read_jsonl(DATA_DIR / "relationships.jsonl")
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")
        backfills = read_jsonl(DATA_DIR / "backfill_candidates.jsonl")

        maneesh_relationships = [
            relationship
            for relationship in relationships
            if relationship["professor_name"] == "Maneesh Agrawala"
        ]
        maneesh_names = {
            person["display_name"]
            for relationship in maneesh_relationships
            for person in people
            if person["person_id"] == relationship["person_id"]
        }

        self.assertEqual(len(maneesh_relationships), 56)
        self.assertIn("Maty Bohacek", maneesh_names)
        self.assertIn("R. Kenny Jones", maneesh_names)
        self.assertIn("Ross Daly", maneesh_names)
        self.assertEqual(sum(1 for person in people if person["display_name"] == "R. Kenny Jones"), 1)
        self.assertIn("https://rkjones4.github.io/", next(person for person in people if person["display_name"] == "R. Kenny Jones")["profile_urls"])
        self.assertIn("Jean-Peïc Chou", {item["person_name"] for item in enrichments})
        self.assertIn("Ross Daly", {item["person_name"] for item in backfills})
        self.assertIn("Anh Truong", {item["person_name"] for item in backfills})

    def test_maneesh_agrawala_outbound_profile_links_are_imported(self):
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")
        enrichments_by_name = {item["person_name"]: item for item in enrichments}

        jihyeon = enrichments_by_name["Jihyeon Je"]
        colorado = enrichments_by_name["Colorado Reed"]

        self.assertEqual(jihyeon["source_type"], "outbound_profile_homepage_pass")
        self.assertEqual(jihyeon["personal_website_url"], "https://jihyeonje.com/")
        self.assertEqual(jihyeon["linkedin_url"], "https://www.linkedin.com/in/jihyeon-je")
        self.assertIn("WJpB3cAAAAAJ", jihyeon["google_scholar_url"])
        self.assertIn("homepage footer exposes Google Scholar and LinkedIn", jihyeon["evidence_text"])
        self.assertEqual(colorado["github_url"], "https://github.com/cjrd")
        self.assertIn("o6LlkNMAAAAJ", colorado["google_scholar_url"])
        self.assertEqual(enrichments_by_name["Sean Arietta"]["candidate_url"], "https://sarietta.com/")
        self.assertEqual(enrichments_by_name["Nicholas Kong"]["candidate_url"], "https://www.linkedin.com/in/kongn")
        self.assertEqual(enrichments_by_name["Terrell Ibanez"]["candidate_url"], "https://www.linkedin.com/in/ibnzterrell")
        self.assertNotIn("Anh Truong", enrichments_by_name)

    def test_jiajun_wu_outbound_profile_links_are_imported(self):
        enrichments = read_jsonl(DATA_DIR / "profile_enrichments.jsonl")
        yue_gao = next(item for item in enrichments if item["person_name"] == "Yue Gao")

        self.assertEqual(yue_gao["source_type"], "outbound_profile_homepage_pass")
        self.assertEqual(yue_gao["personal_website_url"], "https://yuegao.me/")
        self.assertEqual(yue_gao["github_url"], "https://github.com/ueoo")
        self.assertEqual(yue_gao["linkedin_url"], "https://www.linkedin.com/in/yuegaocs/")
        self.assertIn("XPB9hGwAAAAJ", yue_gao["google_scholar_url"])
        self.assertIn("microsoft.com/en-us/research/people/yuegao", yue_gao["evidence_text"])

    def test_eric_chan_relationship_status_conflict_is_marked_for_review(self):
        decisions = read_jsonl(DATA_DIR / "resolution_decisions.jsonl")
        conflicts = [
            decision
            for decision in decisions
            if decision["rule_name"] == "cross_dataset_current_alumni_status_conflict"
        ]

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["person_id"], "person:dc86baaea3c7176d")
        self.assertEqual(conflicts[0]["review_status"], "needs_review")
        self.assertIn("Gordon Wetzstein: phd_student / current", conflicts[0]["candidate_keys"])
        self.assertIn("Jiajun Wu: alumni / alumni", conflicts[0]["candidate_keys"])


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
