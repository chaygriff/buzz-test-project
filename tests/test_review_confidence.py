import unittest

from app.review.confidence import score_relationship_confidence


class ReviewConfidenceTests(unittest.TestCase):
    def test_scores_strong_sourced_profile_as_high_confidence(self):
        score = score_relationship_confidence(
            person={"profile_urls": ["https://example.edu/alice"]},
            relationship={
                "verification_status": "source_roster_verified",
                "confidence": 0.9,
                "source_affiliation_raw": "Stanford University",
                "relationship_type": "phd_student",
                "status": "current",
                "start_year": 2022,
                "degree": "PhD",
            },
            evidence={
                "evidence_text": "Alice Example, Stanford University, PhD student",
                "source_url": "https://example.edu/lab",
                "source_section": "Students",
            },
            enrichment={
                "verification_status": "verified",
                "personal_website_url": "https://example.edu/alice",
                "github_url": "https://github.com/alice",
                "google_scholar_url": "https://scholar.google.com/citations?user=alice",
                "linkedin_url": "https://www.linkedin.com/in/alice",
                "short_biography": "PhD student at Stanford.",
                "homepage_claimed_name": "Alice Example",
            },
            review_decision=None,
            reconciliation_decision=None,
            backfill_candidate=None,
        )

        self.assertEqual(score["confidence_bucket"], "high")
        self.assertGreaterEqual(score["confidence_score"], 80)
        self.assertIn("has_personal_website", score["confidence_reasons"])
        self.assertEqual(score["confidence_penalties"], [])

    def test_missing_profile_and_backfill_lower_confidence(self):
        score = score_relationship_confidence(
            person={"profile_urls": []},
            relationship={
                "verification_status": "parsed",
                "confidence": 0.7,
                "relationship_type": "visitor",
                "status": "alumni",
            },
            evidence={"evidence_text": "Same Name, visitor"},
            enrichment=None,
            review_decision=None,
            reconciliation_decision=None,
            backfill_candidate={"priority_bucket": "medium"},
        )

        self.assertEqual(score["confidence_bucket"], "low")
        self.assertIn("missing_profile_url", score["confidence_penalties"])
        self.assertIn("profile_backfill_queued", score["confidence_penalties"])

    def test_review_decision_overrides_bucket(self):
        score = score_relationship_confidence(
            person={"profile_urls": ["https://example.edu/alice"]},
            relationship={
                "verification_status": "source_roster_verified",
                "confidence": 1.0,
                "source_affiliation_raw": "Stanford University",
                "relationship_type": "phd_student",
                "status": "current",
                "start_year": 2022,
                "degree": "PhD",
            },
            evidence={
                "evidence_text": "Alice Example, Stanford University, PhD student",
                "source_url": "https://example.edu/lab",
                "source_section": "Students",
            },
            enrichment={
                "verification_status": "verified",
                "personal_website_url": "https://example.edu/alice",
                "google_scholar_url": "https://scholar.google.com/citations?user=alice",
                "linkedin_url": "https://www.linkedin.com/in/alice",
            },
            review_decision={"review_status": "needs_review"},
            reconciliation_decision=None,
            backfill_candidate=None,
        )

        self.assertEqual(score["confidence_bucket"], "needs_review")
        self.assertIn("relationship_review_needed", score["confidence_penalties"])


if __name__ == "__main__":
    unittest.main()
