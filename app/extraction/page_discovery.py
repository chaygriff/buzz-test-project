from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


RELEVANT_TERMS = {
    "people",
    "student",
    "students",
    "alumni",
    "member",
    "members",
    "postdoc",
    "postdocs",
    "researcher",
    "researchers",
    "team",
    "lab",
}


@dataclass(frozen=True)
class RelevantLink:
    url: str
    label: str
    score: int


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_by_name = dict(attrs)
        href = attrs_by_name.get("href")
        if href:
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href:
            self.links.append((self._current_href, " ".join(self._text_parts).strip()))
            self._current_href = None
            self._text_parts = []


def discover_relevant_links(html: str, base_url: str) -> list[RelevantLink]:
    parser = LinkParser()
    parser.feed(html)

    discovered: dict[str, RelevantLink] = {}
    for href, label in parser.links:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        url_signal = f"{parsed.path} {parsed.query} {parsed.fragment}"
        haystack = f"{url_signal} {label}".lower()
        score = sum(1 for term in RELEVANT_TERMS if term in haystack)
        if score == 0:
            continue
        existing = discovered.get(absolute)
        candidate = RelevantLink(url=absolute, label=label, score=score)
        if existing is None or candidate.score > existing.score:
            discovered[absolute] = candidate

    return sorted(discovered.values(), key=lambda link: (-link.score, link.url))
