import unittest

from app.extraction.section_parser import parse_sections


class SectionParserTests(unittest.TestCase):
    def test_parses_heading_hierarchy_and_text_blocks(self):
        html = """
        <h1>People</h1>
        <h2>Former Students</h2>
        <p>Jane Smith -- PhD 2022, Google DeepMind</p>
        <h2>Current PhD Students</h2>
        <ul><li>Alex Lee</li></ul>
        """

        blocks = parse_sections(html, "https://lab.example.edu/people")

        self.assertEqual(blocks[0].heading_path, ["People", "Former Students"])
        self.assertEqual(blocks[0].text, "Jane Smith -- PhD 2022, Google DeepMind")
        self.assertEqual(blocks[1].heading_path, ["People", "Current PhD Students"])
        self.assertEqual(blocks[1].text, "Alex Lee")


if __name__ == "__main__":
    unittest.main()

