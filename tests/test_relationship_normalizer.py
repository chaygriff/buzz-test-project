import unittest

from app.extraction.relationship_normalizer import normalize_relationship_block, normalize_relationships
from app.extraction.section_parser import SectionBlock


class RelationshipNormalizerTests(unittest.TestCase):
    def test_normalizes_current_phd_student_row(self):
        block = SectionBlock(
            source_url="https://web.stanford.edu/~gordonwz/",
            heading_path=["Students supervised", "PhD"],
            text="Boyang Deng, Stanford University (CS), 2022-, Meta Research PhD Fellowship, *co-advised with Leo Guibas",
        )

        record = normalize_relationship_block(
            block,
            faculty_name="Gordon Wetzstein",
            faculty_institution="Stanford University",
            faculty_homepage="https://web.stanford.edu/~gordonwz/",
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.person_name, "Boyang Deng")
        self.assertEqual(record.normalized_relationship, "phd_student")
        self.assertEqual(record.status, "current")
        self.assertEqual(record.degree, "PhD")
        self.assertEqual(record.start_year, 2022)
        self.assertIsNone(record.end_year)
        self.assertEqual(record.co_advisor, "Leo Guibas")
        self.assertEqual(record.fellowship, "Meta Research PhD Fellowship")
        self.assertEqual(record.page_section, "Students supervised > PhD")

    def test_normalizes_alumni_destination_and_graduation_year(self):
        block = SectionBlock(
            source_url="https://web.stanford.edu/~gordonwz/",
            heading_path=["Students supervised", "Alumni PhD Students"],
            text="Connor Lin, Stanford University (CS), 2020-2024, Stanford SGF, *co-advised with Leo Guibas, now CTO at Apparate AI",
        )

        record = normalize_relationship_block(block)

        self.assertIsNotNone(record)
        self.assertEqual(record.person_name, "Connor Lin")
        self.assertEqual(record.normalized_relationship, "phd_student")
        self.assertEqual(record.status, "alumni")
        self.assertEqual(record.start_year, 2020)
        self.assertEqual(record.end_year, 2024)
        self.assertEqual(record.graduation_year, 2024)
        self.assertEqual(record.co_advisor, "Leo Guibas")
        self.assertEqual(record.fellowship, "Stanford SGF")
        self.assertEqual(record.current_destination, "CTO at Apparate AI")

    def test_ignores_non_supervision_sections(self):
        blocks = [
            SectionBlock(
                source_url="https://web.stanford.edu/~gordonwz/",
                heading_path=["Short Biography"],
                text="Gordon Wetzstein is an Associate Professor.",
            )
        ]

        self.assertEqual(normalize_relationships(blocks), [])


if __name__ == "__main__":
    unittest.main()
