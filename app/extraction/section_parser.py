from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

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


class PanelListHTMLParser(HTMLParser):
    def __init__(self, source_url: str):
        super().__init__()
        self.source_url = source_url
        self.blocks: list[tuple[list[str], str, list[EvidenceLink]]] = []
        self._panel_stack: list[str] = []
        self._pending_panel_label = False
        self._panel_label_parts: list[str] = []
        self._current_panel_label: str | None = None
        self._list_depth = 0
        self._li_parts: list[str] | None = None
        self._li_links: list[EvidenceLink] = []
        self._active_link_href: str | None = None
        self._active_link_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = {name.lower(): value for name, value in attrs}
        classes = set((attrs_by_name.get("class") or "").split())
        element_id = attrs_by_name.get("id") or ""

        if tag == "div" and (element_id.endswith("Div") or "hideClass" in classes):
            self._panel_stack.append(element_id)
            self._current_panel_label = panel_label_from_id(element_id)
        elif self._panel_stack and tag == "span" and "panel-label" in classes:
            self._pending_panel_label = True
            self._panel_label_parts = []
        elif self._panel_stack and tag in {"ol", "ul"}:
            self._list_depth += 1
        elif self._panel_stack and tag == "li" and self._list_depth:
            self._flush_list_item()
            self._li_parts = []
            self._li_links = []
        elif tag == "a" and attrs_by_name.get("href") and self._li_parts is not None:
            self._active_link_href = attrs_by_name["href"]
            self._active_link_parts = []

    def handle_data(self, data: str) -> None:
        if self._pending_panel_label:
            self._panel_label_parts.append(data)
        if self._li_parts is not None:
            self._li_parts.append(data)
        if self._active_link_parts is not None:
            self._active_link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_link_href and self._active_link_parts is not None:
            link_text = normalize_text(" ".join(self._active_link_parts))
            if link_text:
                self._li_links.append(EvidenceLink(text=link_text, url=urljoin(self.source_url, self._active_link_href)))
            self._active_link_href = None
            self._active_link_parts = None
        elif tag == "span" and self._pending_panel_label:
            label = normalize_text(" ".join(self._panel_label_parts))
            if label:
                self._current_panel_label = title_case_panel_label(label)
            self._pending_panel_label = False
            self._panel_label_parts = []
        elif self._panel_stack and tag in {"ol", "ul"}:
            self._flush_list_item()
            self._list_depth = max(0, self._list_depth - 1)
        elif self._panel_stack and tag == "div":
            self._flush_list_item()
            self._panel_stack.pop()
            self._current_panel_label = panel_label_from_id(self._panel_stack[-1]) if self._panel_stack else None

    def close(self) -> None:
        self._flush_list_item()
        super().close()

    def _flush_list_item(self) -> None:
        if self._li_parts is None:
            return
        text = normalize_text(" ".join(self._li_parts))
        label = self._current_panel_label
        if text and label and is_relevant_fallback_label(label):
            self.blocks.append(([label], text, list(self._li_links)))
        self._li_parts = None
        self._li_links = []


def panel_label_from_id(element_id: str) -> str | None:
    if not element_id:
        return None
    label = re.sub(r"Div$", "", element_id)
    label = re.sub(r"([a-z])([A-Z])", r"\1 \2", label)
    return title_case_panel_label(label)


def title_case_panel_label(label: str) -> str:
    return normalize_text(label).title()


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
    panel_parser = PanelListHTMLParser(source_url)
    panel_parser.feed(html)
    panel_parser.close()
    seen: set[tuple[tuple[str, ...], str]] = set()
    blocks: list[SectionBlock] = []
    for heading_path, text, links in [*parser.blocks, *fallback_parser.blocks, *panel_parser.blocks]:
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
    seen_html_hashes: set[str] = set()
    metadata_records = []
    for metadata_path in sorted(cache_dir.glob("*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata_records.append(metadata)
    metadata_records.sort(key=lambda metadata: (1 if urlparse(metadata["url"]).fragment else 0, metadata["url"]))
    for metadata in metadata_records:
        html_path = Path(metadata["html_path"])
        html = html_path.read_text(encoding="utf-8")
        html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if html_hash in seen_html_hashes:
            continue
        seen_html_hashes.add(html_hash)
        blocks.extend(parse_sections(html, metadata["url"]))
    return blocks
