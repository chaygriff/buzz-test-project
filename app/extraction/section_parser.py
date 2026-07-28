from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "li", "td", "th", "div"}


@dataclass(frozen=True)
class SectionBlock:
    source_url: str
    heading_path: list[str]
    text: str


class SectionHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.heading_stack: list[tuple[int, str]] = []
        self.blocks: list[tuple[list[str], str]] = []
        self._capture_tag: str | None = None
        self._capture_heading_level: int | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in HEADING_TAGS:
            self._capture_tag = tag
            self._capture_heading_level = int(tag[1])
            self._parts = []
        elif tag in BLOCK_TAGS and self._capture_tag is None:
            self._capture_tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_tag:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._capture_tag:
            return

        text = normalize_text(" ".join(self._parts))
        if text and tag in HEADING_TAGS and self._capture_heading_level is not None:
            self._set_heading(self._capture_heading_level, text)
        elif text and self.heading_stack:
            self.blocks.append(([heading for _, heading in self.heading_stack], text))

        self._capture_tag = None
        self._capture_heading_level = None
        self._parts = []

    def _set_heading(self, level: int, text: str) -> None:
        self.heading_stack = [(old_level, old_text) for old_level, old_text in self.heading_stack if old_level < level]
        self.heading_stack.append((level, text))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_sections(html: str, source_url: str) -> list[SectionBlock]:
    parser = SectionHTMLParser()
    parser.feed(html)
    return [
        SectionBlock(source_url=source_url, heading_path=heading_path, text=text)
        for heading_path, text in parser.blocks
    ]


def parse_cached_pages(cache_dir: Path) -> list[SectionBlock]:
    blocks: list[SectionBlock] = []
    for metadata_path in sorted(cache_dir.glob("*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        html_path = Path(metadata["html_path"])
        html = html_path.read_text(encoding="utf-8")
        blocks.extend(parse_sections(html, metadata["url"]))
    return blocks

