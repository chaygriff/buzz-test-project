import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.enrichment.outbound import (
    EnrichmentConfig,
    OutboundFetchResult,
    build_backfill_candidates,
    build_enrichment_candidates,
    classify_url,
    enrich_candidates,
    import_manual_profile_research,
)
from app.models.records import EvidenceLink, RelationshipRecord


def relationship(
    person_name: str = "Boyang Deng",
    *,
    links: list[EvidenceLink] | None = None,
    profile_url: str | None = None,
) -> RelationshipRecord:
    return RelationshipRecord(
        faculty_name="Gordon Wetzstein",
        faculty_institution="Stanford University",
        faculty_homepage="https://web.stanford.edu/~gordonwz/",
        person_name=person_name,
        person_profile_url=profile_url,
        raw_relationship="PhD",
        normalized_relationship="phd_student",
        status="current",
        degree="PhD",
        start_year=2022,
        end_year=None,
        graduation_year=None,
        co_advisor=None,
        fellowship=None,
        current_destination=None,
        source_url="https://web.stanford.edu/~gordonwz/",
        page_section="Students supervised > PhD",
        evidence_text=f"{person_name}, Stanford University (CS), 2022-",
        confidence=0.75,
        verification_status="parsed",
        retrieved_at=None,
        source_links=links or [],
    )


def postdoc_without_link(person_name: str = "Michael Broxton") -> RelationshipRecord:
    return RelationshipRecord(
        faculty_name="Gordon Wetzstein",
        faculty_institution="Stanford University",
        faculty_homepage="https://web.stanford.edu/~gordonwz/",
        person_name=person_name,
        person_profile_url=None,
        raw_relationship="Postdocs",
        normalized_relationship="postdoc",
        status="alumni",
        degree=None,
        start_year=2017,
        end_year=2018,
        graduation_year=None,
        co_advisor=None,
        fellowship=None,
        current_destination="Research Scientist at Google",
        source_url="https://web.stanford.edu/~gordonwz/",
        page_section="Students supervised > Postdocs",
        evidence_text=f"{person_name}, Stanford University, Postdoc 2017-2018, now Research Scientist at Google",
        confidence=0.75,
        verification_status="parsed",
        retrieved_at=None,
        source_links=[],
    )


class OutboundEnrichmentTests(unittest.TestCase):
    def test_classifies_supported_and_identifier_only_urls(self):
        self.assertEqual(classify_url("https://boyangdeng.com/"), "personal_website")
        self.assertEqual(classify_url("https://gunyeal.github.io/"), "github_pages")
        self.assertEqual(classify_url("https://scholar.google.com/citations?user=abc"), "google_scholar")
        self.assertEqual(classify_url("https://www.linkedin.com/in/example/"), "linkedin")
        self.assertEqual(classify_url("https://github.com/example"), "github_profile")
        self.assertEqual(classify_url("https://example.com/cv.pdf"), "pdf")

    def test_builds_person_matched_candidates_with_per_person_cap(self):
        candidates = build_enrichment_candidates(
            [
                relationship(
                    links=[
                        EvidenceLink(text="Boyang Deng", url="https://boyangdeng.com/"),
                        EvidenceLink(text="Boyang Deng", url="https://scholar.google.com/citations?user=abc"),
                        EvidenceLink(text="Unrelated Lab", url="https://lab.example.edu/"),
                    ]
                )
            ],
            max_candidates_per_person=1,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].person_name, "Boyang Deng")
        self.assertEqual(candidates[0].source_type, "personal_website")

    def test_identifier_only_sources_are_not_fetched(self):
        candidates = build_enrichment_candidates(
            [
                relationship(
                    links=[EvidenceLink(text="Boyang Deng", url="https://www.linkedin.com/in/boyang-deng/")]
                )
            ]
        )

        records = enrich_candidates(candidates)

        self.assertEqual(records[0].fetch_status, "identifier_only")
        self.assertEqual(records[0].skip_reason, "stored_as_external_identifier")
        self.assertEqual(records[0].linkedin_url, "https://www.linkedin.com/in/boyang-deng/")

    def test_builds_prioritized_backfill_candidates_for_people_without_links(self):
        candidates = build_backfill_candidates(
            [
                postdoc_without_link(),
                relationship(
                    person_name="Boyang Deng",
                    links=[EvidenceLink(text="Boyang Deng", url="https://boyangdeng.com/")],
                ),
            ],
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].person_name, "Michael Broxton")
        self.assertEqual(candidates[0].relationship_type, "postdoc")
        self.assertEqual(candidates[0].priority_bucket, "high")
        self.assertIn("has_seed_current_destination", candidates[0].priority_reasons)
        self.assertIn("Michael Broxton", candidates[0].search_query)
        self.assertIn("Gordon Wetzstein", candidates[0].search_query)
        self.assertIn("Research Scientist at Google", candidates[0].search_query)
        self.assertIn("Run people-research", candidates[0].research_guidance[0])
        self.assertIn("Stanford University", candidates[0].research_guidance[1])
        self.assertIn("Gordon Wetzstein", candidates[0].research_guidance[1])
        self.assertIn("web.stanford.edu", candidates[0].research_guidance[1])
        self.assertEqual(candidates[0].verification_status, "needs_people_research")

    def test_backfill_candidates_exclude_already_enriched_people(self):
        person_id = build_backfill_candidates([postdoc_without_link()])[0].person_id

        candidates = build_backfill_candidates(
            [postdoc_without_link()],
            existing_enriched_person_ids={person_id},
        )

        self.assertEqual(candidates, [])

    @patch("app.enrichment.outbound.fetch_candidate")
    @patch("app.enrichment.outbound.RobotsPolicy")
    def test_fetches_allowed_depth_zero_html_and_extracts_bio(self, robots_policy, fetch_candidate):
        robots_policy.for_url.return_value.can_fetch.return_value = True
        fetch_candidate.return_value = OutboundFetchResult(
            final_url="https://boyangdeng.com/",
            status_code=200,
            content_type="text/html",
            html="""
            <html>
              <head>
                <title>Boyang Deng</title>
                <meta name="description" content="Boyang Deng is a PhD student at Stanford working on AI and graphics.">
              </head>
              <body><p>Boyang Deng is a PhD student at Stanford.</p></body>
            </html>
            """,
        )
        candidates = build_enrichment_candidates(
            [relationship(links=[EvidenceLink(text="Boyang Deng", url="https://boyangdeng.com/")])]
        )

        records = enrich_candidates(candidates, config=EnrichmentConfig(max_fetches_per_seed=1))

        self.assertEqual(records[0].fetch_status, "fetched")
        self.assertEqual(records[0].profile_title, "Boyang Deng")
        self.assertEqual(records[0].homepage_claimed_name, "Boyang Deng")
        self.assertIn("PhD student at Stanford", records[0].short_biography)

    @patch("app.enrichment.outbound.RobotsPolicy")
    def test_records_robots_skip_reason(self, robots_policy):
        robots_policy.for_url.return_value.can_fetch.return_value = False
        candidates = build_enrichment_candidates(
            [relationship(links=[EvidenceLink(text="Boyang Deng", url="https://boyangdeng.com/")])]
        )

        records = enrich_candidates(candidates)

        self.assertEqual(records[0].fetch_status, "skipped")
        self.assertEqual(records[0].skip_reason, "robots_disallowed")

    @patch("app.enrichment.outbound.fetch_candidate")
    @patch("app.enrichment.outbound.RobotsPolicy")
    def test_records_fetch_errors_as_skips(self, robots_policy, fetch_candidate):
        robots_policy.for_url.return_value.can_fetch.return_value = True
        fetch_candidate.side_effect = ValueError("unsupported content type: application/pdf")
        candidates = build_enrichment_candidates(
            [relationship(links=[EvidenceLink(text="Boyang Deng", url="https://boyangdeng.com/")])]
        )

        records = enrich_candidates(candidates)

        self.assertEqual(records[0].fetch_status, "skipped")
        self.assertIn("unsupported content type", records[0].skip_reason)

    def test_imports_manual_profile_research_markdown_payload(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.md"
            path.write_text(
                """
                # Batch

                ```json
                [
                  {
                    "person_name": "Boyang Deng",
                    "person_id": "person:example",
                    "short_biography": "CS PhD candidate at Stanford.",
                    "linkedin_url": "https://linkedin.com/in/boyang-deng-728978113",
                    "google_scholar_url": "https://scholar.google.com/citations?user=Nr_uRhQAAAAJ",
                    "github_url": "https://github.com/Awcrr",
                    "personal_website_url": "https://boyangdeng.com/",
                    "source_url": "https://boyangdeng.com/",
                    "evidence_text": "Personal site says CS PhD candidate at Stanford.",
                    "verification_status": "verified"
                  }
                ]
                ```
                """,
                encoding="utf-8",
            )

            records = import_manual_profile_research(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].fetch_status, "manual_research")
        self.assertEqual(records[0].source_type, "people_research")
        self.assertEqual(records[0].person_id, "person:example")
        self.assertEqual(records[0].short_biography, "CS PhD candidate at Stanford.")
        self.assertEqual(records[0].linkedin_url, "https://linkedin.com/in/boyang-deng-728978113")
        self.assertEqual(records[0].verification_status, "verified")


if __name__ == "__main__":
    unittest.main()
