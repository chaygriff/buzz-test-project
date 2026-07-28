import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.extraction.section_parser import parse_cached_pages, parse_sections


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

    def test_parses_legacy_strong_label_and_table_rows(self):
        html = """
        <strong>Students supervised</strong>
        <table>
          <tr><td>PhD</td><td><a href="https://example.com/alex">Alex Lee</a>, Stanford University (CS), 2022-</td></tr>
          <tr><td></td><td>Jane Smith, Stanford University (EE), 2023-, co-advised</td></tr>
          <tr><td>Alumni PhD Students</td><td>Sam Rivera, Stanford University (EE), 2018-2023, now at Example AI</td></tr>
        </table>
        """

        blocks = parse_sections(html, "https://web.stanford.edu/~example/")

        self.assertEqual(blocks[0].heading_path, ["Students supervised", "PhD"])
        self.assertEqual(blocks[0].text, "Alex Lee, Stanford University (CS), 2022-")
        self.assertEqual(blocks[0].links[0].text, "Alex Lee")
        self.assertEqual(blocks[0].links[0].url, "https://example.com/alex")
        self.assertEqual(blocks[1].heading_path, ["Students supervised", "PhD"])
        self.assertEqual(blocks[1].text, "Jane Smith, Stanford University (EE), 2023-, co-advised")
        self.assertEqual(blocks[2].heading_path, ["Students supervised", "Alumni PhD Students"])
        self.assertIn("now at Example AI", blocks[2].text)

    def test_resolves_relative_links_against_source_url(self):
        html = """
        <h1>Students supervised</h1>
        <h2>PhD</h2>
        <ul><li><a href="/people/alex">Alex Lee</a>, Stanford University (CS), 2022-</li></ul>
        """

        blocks = parse_sections(html, "https://lab.example.edu/faculty")

        self.assertEqual(blocks[0].links[0].url, "https://lab.example.edu/people/alex")

    def test_parses_strong_labeled_biography_paragraph(self):
        html = """
        <p><strong>Short Biography:</strong> Gordon Wetzstein is an Associate Professor
        of Electrical Engineering and, by courtesy, of Computer Science at Stanford University.</p>
        """

        blocks = parse_sections(html, "https://web.stanford.edu/~example/")

        self.assertEqual(blocks[0].heading_path, ["Short Biography"])
        self.assertIn("Associate Professor", blocks[0].text)

    def test_parses_hidden_panel_list_items_with_implicit_li_boundaries(self):
        html = """
        <div id="alumniDiv" class="hideClass">
          <span class="panel-label">ALUMNI</span>
          <ol>
            <li> Shruti Agarwal (Ph.D., 2021) [<a href="downloads/sathesis21.pdf">dissertation</a>]
            <li> <a href="https://www.matyasbohacek.com">Maty Bohacek</a>
            <li> Tiago Carvalho (visiting Ph.D. student, UNICAMP, Brazil, 2014)
          </ol>
        </div>
        """

        blocks = parse_sections(html, "https://hfarid.org/")

        alumni_blocks = [block for block in blocks if block.heading_path == ["Alumni"]]
        self.assertEqual(len(alumni_blocks), 3)
        self.assertEqual(alumni_blocks[0].text, "Shruti Agarwal (Ph.D., 2021) [ dissertation ]")
        self.assertEqual(alumni_blocks[0].links[0].url, "https://hfarid.org/downloads/sathesis21.pdf")
        self.assertEqual(alumni_blocks[1].text, "Maty Bohacek")
        self.assertEqual(alumni_blocks[1].links[0].url, "https://www.matyasbohacek.com")

    def test_parse_cached_pages_skips_duplicate_html_bodies(self):
        html = """
        <div id="alumniDiv" class="hideClass">
          <span class="panel-label">ALUMNI</span>
          <ol><li> Shruti Agarwal (Ph.D., 2021)</ol>
        </div>
        """
        with TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            root_html = cache_dir / "root.html"
            fragment_html = cache_dir / "fragment.html"
            root_html.write_text(html, encoding="utf-8")
            fragment_html.write_text(html, encoding="utf-8")
            (cache_dir / "root.json").write_text(
                json.dumps({"url": "https://hfarid.org/", "html_path": str(root_html)}),
                encoding="utf-8",
            )
            (cache_dir / "fragment.json").write_text(
                json.dumps({"url": "https://hfarid.org/#alumniDiv", "html_path": str(fragment_html)}),
                encoding="utf-8",
            )

            blocks = parse_cached_pages(cache_dir)

        self.assertEqual(len([block for block in blocks if block.heading_path == ["Alumni"]]), 1)
        self.assertEqual(blocks[0].source_url, "https://hfarid.org/")


if __name__ == "__main__":
    unittest.main()
