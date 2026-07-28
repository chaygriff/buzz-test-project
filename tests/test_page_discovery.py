import unittest

from app.extraction.page_discovery import discover_relevant_links


class PageDiscoveryTests(unittest.TestCase):
    def test_discovers_relevant_same_page_links(self):
        html = """
        <a href="/people">People</a>
        <a href="/publications">Publications</a>
        <a href="/alumni">Former students and alumni</a>
        """

        links = discover_relevant_links(html, "https://lab.example.edu/")

        self.assertEqual([link.url for link in links], [
            "https://lab.example.edu/alumni",
            "https://lab.example.edu/people",
        ])


if __name__ == "__main__":
    unittest.main()

