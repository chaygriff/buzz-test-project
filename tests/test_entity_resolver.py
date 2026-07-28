import unittest

from app.models.records import RelationshipRecord
from app.resolution.entity_resolver import normalize_missing, resolve_relationship_entities, split_org_and_departments


def relationship(
    person_name: str,
    evidence_text: str,
    normalized_relationship: str,
    status: str,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    co_advisor: str | None = None,
    current_destination: str | None = None,
    faculty_homepage: str = "https://web.stanford.edu/~gordonwz/",
) -> RelationshipRecord:
    return RelationshipRecord(
        faculty_name="Gordon Wetzstein",
        faculty_institution="Stanford University",
        faculty_homepage=faculty_homepage,
        person_name=person_name,
        person_profile_url=None,
        raw_relationship=normalized_relationship,
        normalized_relationship=normalized_relationship,
        status=status,
        degree=None,
        start_year=start_year,
        end_year=end_year,
        graduation_year=None,
        co_advisor=co_advisor,
        fellowship=None,
        current_destination=current_destination,
        source_url="https://web.stanford.edu/~gordonwz/",
        page_section="Students supervised",
        evidence_text=evidence_text,
        confidence=0.75,
        verification_status="parsed",
        retrieved_at=None,
    )


class EntityResolverTests(unittest.TestCase):
    def test_merges_exact_name_with_sequential_roles_in_same_faculty_context(self):
        result = resolve_relationship_entities(
            [
                relationship(
                    "Seung-Woo Nam",
                    "Seung-Woo Nam, SNU, Visiting Student 2024",
                    "visitor",
                    "alumni",
                    start_year=2024,
                    end_year=2024,
                ),
                relationship(
                    "Seung-Woo Nam",
                    "Seung-Woo Nam, Stanford University (EE), Postdoc: 2025-",
                    "postdoc",
                    "current",
                    start_year=2025,
                ),
            ]
        )

        people = [person for person in result.people if person.display_name == "Seung-Woo Nam"]
        self.assertEqual(len(people), 1)
        person_id = people[0].person_id
        self.assertEqual(
            [record.person_id for record in result.relationships],
            [person_id, person_id],
        )
        self.assertEqual(result.resolution_decisions[0].decision, "auto_merge")

    def test_does_not_merge_same_name_across_different_faculty_contexts(self):
        result = resolve_relationship_entities(
            [
                relationship(
                    "Alex Lee",
                    "Alex Lee, Stanford University (CS), 2022-",
                    "phd_student",
                    "current",
                    faculty_homepage="https://faculty.example.edu/one",
                ),
                relationship(
                    "Alex Lee",
                    "Alex Lee, MIT, 2022-",
                    "phd_student",
                    "current",
                    faculty_homepage="https://faculty.example.edu/two",
                ),
            ]
        )

        people = [person for person in result.people if person.display_name == "Alex Lee"]
        self.assertEqual(len(people), 2)
        self.assertEqual(result.resolution_decisions, [])

    def test_merges_tong_wu_and_preserves_current_destination_raw(self):
        result = resolve_relationship_entities(
            [
                relationship(
                    "Tong Wu",
                    "Tong Wu, The Chinese University of Hong Kong (CUHK), Visiting Student 2023-2024",
                    "visitor",
                    "alumni",
                    start_year=2023,
                    end_year=2024,
                ),
                relationship(
                    "Tong Wu",
                    "Tong Wu, Stanford University (CS/EE), Postdoc: 2025-2026, now Assistant Professor at Fudan University",
                    "postdoc",
                    "alumni",
                    start_year=2025,
                    end_year=2026,
                    current_destination="Assistant Professor at Fudan University",
                ),
            ]
        )

        people = [person for person in result.people if person.display_name == "Tong Wu"]
        self.assertEqual(len(people), 1)
        self.assertEqual(result.relationships[1].current_destination_raw, "Assistant Professor at Fudan University")
        self.assertIsNotNone(result.relationships[1].current_destination_org_id)

    def test_keeps_co_advisor_as_raw_name_until_supported_by_entity_evidence(self):
        result = resolve_relationship_entities(
            [
                relationship(
                    "Boyang Deng",
                    "Boyang Deng, Stanford University (CS), 2022-, *co-advised with Leo Guibas",
                    "phd_student",
                    "current",
                    start_year=2022,
                    co_advisor="Leo Guibas",
                )
            ]
        )

        self.assertIsNone(result.relationships[0].co_advisor_person_id)
        self.assertEqual(result.relationships[0].co_advisor_name_raw, "Leo Guibas")

    def test_normalizes_missing_values_without_string_na(self):
        self.assertIsNone(normalize_missing(""))
        self.assertIsNone(normalize_missing("N/A"))
        self.assertEqual(normalize_missing(" Stanford "), "Stanford")

    def test_splits_department_parentheticals_from_organization_name(self):
        self.assertEqual(
            split_org_and_departments("Stanford University (CS/EE)"),
            ("Stanford University", ["CS", "EE"]),
        )


if __name__ == "__main__":
    unittest.main()
