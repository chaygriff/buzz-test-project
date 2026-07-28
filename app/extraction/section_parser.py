from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from app.models.records import EvidenceLink


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "li", "td", "th", "div"}
RELEVANT_FALLBACK_TERMS = {
    "alumni",
    "bio",
    "biography",
    "education",
    "experience",
    "graduate",
    "msc",
    "phd",
    "postdoc",
    "student",
    "students",
    "supervised",
    "undergrad",
    "visitor",
    "visitors",
}


@dataclass(frozen=True)
class SectionBlock:
    source_url: str
    heading_path: list[str]
    text: str
    links: list[EvidenceLink] = field(default_factory=list)


class SectionHTMLParser(HTMLParser):
    def __init__(self, source_url: str):
        super().__init__()
        self.source_url = source_url
        self.heading_stack: list[tuple[int, str]] = []
        self.blocks: list[tuple[list[str], str, list[EvidenceLink]]] = []
        self._capture_tag: str | None = None
        self._capture_heading_level: int | None = None
        self._parts: list[str] = []
        self._links: list[EvidenceLink] = []
        self._active_link_href: str | None = None
        self._active_link_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = dict(attrs)
        if tag == "a" and self._capture_tag and attrs_by_name.get("href"):
            self._active_link_href = attrs_by_name["href"]
            self._active_link_parts = []
        elif tag in HEADING_TAGS:
            self._capture_tag = tag
            self._capture_heading_level = int(tag[1])
            self._parts = []
            self._links = []
        elif tag in BLOCK_TAGS and self._capture_tag is None:
            self._capture_tag = tag
            self._parts = []
            self._links = []

    def handle_data(self, data: str) -> None:
        if self._capture_tag:
            self._parts.append(data)
        if self._active_link_parts is not None:
            self._active_link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_link_href and self._active_link_parts is not None:
            text = normalize_text(" ".join(self._active_link_parts))
            if text:
                self._links.append(EvidenceLink(text=text, url=urljoin(self.source_url, self._active_link_href)))
            self._active_link_href = None
            self._active_link_parts = None
            return

        if tag != self._capture_tag:
            return

        text = normalize_text(" ".join(self._parts))
        if text and tag in HEADING_TAGS and self._capture_heading_level is not None:
            self._set_heading(self._capture_heading_level, text)
        elif text and self.heading_stack:
            self.blocks.append(([heading for _, heading in self.heading_stack], text, list(self._links)))

        self._capture_tag = None
        self._capture_heading_level = None
        self._parts = []
        self._links = []

    def _set_heading(self, level: int, text: str) -> None:
        self.heading_stack = [(old_level, old_text) for old_level, old_text in self.heading_stack if old_level < level]
        self.heading_stack.append((level, text))


class FallbackHTMLParser(HTMLParser):
    def __init__(self, source_url: str):
        super().__init__()
        self.source_url = source_url
        self.blocks: list[tuple[list[str], str, list[EvidenceLink]]] = []
        self._current_section: str | None = None
        self._current_table_label: str | None = None
        self._tag_stack: list[str] = []
        self._strong_parts: list[str] | None = None
        self._paragraph_parts: list[str] | None = None
        self._paragraph_links: list[EvidenceLink] | None = None
        self._row_cells: list[str] | None = None
        self._row_cell_links: list[list[EvidenceLink]] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_links: list[EvidenceLink] | None = None
        self._active_link_href: str | None = None
        self._active_link_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = dict(attrs)
        self._tag_stack.append(tag)
        if tag == "a" and attrs_by_name.get("href") and (self._paragraph_parts is not None or self._cell_parts is not None):
            self._active_link_href = attrs_by_name["href"]
            self._active_link_parts = []
        elif tag == "strong":
            self._strong_parts = []
        elif tag == "p":
            self._paragraph_parts = []
            self._paragraph_links = []
        elif tag == "tr":
            self._row_cells = []
            self._row_cell_links = []
        elif tag in {"td", "th"} and self._row_cells is not None:
            self._cell_parts = []
            self._cell_links = []

    def handle_data(self, data: str) -> None:
        if self._strong_parts is not None:
            self._strong_parts.append(data)
        if self._paragraph_parts is not None:
            self._paragraph_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._active_link_parts is not None:
            self._active_link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_link_href and self._active_link_parts is not None:
            link_text = normalize_text(" ".join(self._active_link_parts))
            if link_text:
                link = EvidenceLink(text=link_text, url=urljoin(self.source_url, self._active_link_href))
                if self._paragraph_links is not None:
                    self._paragraph_links.append(link)
                if self._cell_links is not None:
                    self._cell_links.append(link)
            self._active_link_href = None
            self._active_link_parts = None
        elif tag == "strong" and self._strong_parts is not None:
            heading = normalize_text(" ".join(self._strong_parts)).removesuffix(":")
            if heading:
                self._current_section = heading
                self._current_table_label = None
            self._strong_parts = None
        elif tag == "p" and self._paragraph_parts is not None:
            text = normalize_text(" ".join(self._paragraph_parts))
            if text and self._current_section and is_relevant_fallback_label(self._current_section):
                text = remove_leading_label(text, self._current_section)
                self.blocks.append(([self._current_section], text, list(self._paragraph_links or [])))
            self._paragraph_parts = None
            self._paragraph_links = None
        elif tag in {"td", "th"} and self._cell_parts is not None:
            if self._row_cells is not None:
                self._row_cells.append(normalize_text(" ".join(self._cell_parts)))
            if self._row_cell_links is not None:
                self._row_cell_links.append(list(self._cell_links or []))
            self._cell_parts = None
            self._cell_links = None
        elif tag == "tr" and self._row_cells is not None:
            self._flush_row(self._row_cells, self._row_cell_links or [])
            self._row_cells = None
            self._row_cell_links = None

        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        elif tag in self._tag_stack:
            self._tag_stack.remove(tag)

    def _flush_row(self, cells: list[str], cell_links: list[list[EvidenceLink]]) -> None:
        if len(cells) < 2:
            return

        label = cells[0]
        text = normalize_text(" ".join(cell for cell in cells[1:] if cell))
        if label:
            self._current_table_label = label
        if not text or not self._current_section:
            return

        heading_path = [self._current_section]
        if self._current_table_label:
            heading_path.append(self._current_table_label)
        if any(is_relevant_fallback_label(label) for label in heading_path):
            links = [link for links_for_cell in cell_links[1:] for link in links_for_cell]
            self.blocks.append((heading_path, text, links))


def normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+([,.;:])", r"\1", normalized)


def is_relevant_fallback_label(value: str) -> bool:
    normalized = value.lower()
    return any(term in normalized for term in RELEVANT_FALLBACK_TERMS)


def remove_leading_label(text: str, label: str) -> str:
    pattern = rf"^{re.escape(label)}\s*:?\s*"
    return re.sub(pattern, "", text, flags=re.IGNORECASE)


def parse_sections(html: str, source_url: str) -> list[SectionBlock]:
    parser = SectionHTMLParser(source_url)
    parser.feed(html)
    fallback_parser = FallbackHTMLParser(source_url)
    fallback_parser.feed(html)
    seen: set[tuple[tuple[str, ...], str]] = set()
    blocks: list[SectionBlock] = []
    for heading_path, text, links in [*parser.blocks, *fallback_parser.blocks]:
        key = (tuple(heading_path), text)
        if key in seen:
            continue
        seen.add(key)
        blocks.append(SectionBlock(source_url=source_url, heading_path=heading_path, text=text, links=links))
    return [
        block
        for block in blocks
    ]


def parse_cached_pages(cache_dir: Path) -> list[SectionBlock]:
    blocks: list[SectionBlock] = []
    for metadata_path in sorted(cache_dir.glob("*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        html_path = Path(metadata["html_path"])
        html = html_path.read_text(encoding="utf-8")
        blocks.extend(parse_sections(html, metadata["url"]))
    return blocks
