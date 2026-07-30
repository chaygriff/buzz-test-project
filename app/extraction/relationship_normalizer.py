from __future__ import annotations

import json
import re
from pathlib import Path

from app.extraction.section_parser import SectionBlock
from app.models.records import EvidenceLink, RelationshipRecord


RELATIONSHIP_BY_CATEGORY = {
    "postdocs": ("postdoc", "current", None),
    "phd": ("phd_student", "current", "PhD"),
    "msc": ("masters_student", "current", "MSc"),
    "visitors": ("visitor", "current", None),
    "alumni postdocs": ("postdoc", "alumni", None),
    "alumni phd students": ("phd_student", "alumni", "PhD"),
    "alumni msc students": ("masters_student", "alumni", "MSc"),
    "alumni bsc students": ("undergraduate_student", "alumni", "BSc"),
    "alumni visitors": ("visitor", "alumni", None),
    "alumni high school students": ("high_school_student", "alumni", None),
}


def normalize_relationships(
    blocks: list[SectionBlock],
    *,
    faculty_name: str | None = None,
    faculty_institution: str | None = None,
    faculty_homepage: str | None = None,
) -> list[RelationshipRecord]:
    records: list[RelationshipRecord] = []
    for block in blocks:
        record = normalize_relationship_block(
            block,
            faculty_name=faculty_name,
            faculty_institution=faculty_institution,
            faculty_homepage=faculty_homepage,
        )
        if record is not None:
            records.append(record)
    return records


def normalize_relationship_block(
    block: SectionBlock,
    *,
    faculty_name: str | None = None,
    faculty_institution: str | None = None,
    faculty_homepage: str | None = None,
) -> RelationshipRecord | None:
    category = relationship_category_for_block(block)
    if category is None:
        return None
    normalized_relationship, status, degree = relationship_from_block(block, category)
    if normalized_relationship is None:
        return None
    person_name = extract_person_name(block.text)
    person_profile_url = select_person_profile_url(person_name, block.links)

    return RelationshipRecord(
        faculty_name=faculty_name,
        faculty_institution=faculty_institution,
        faculty_homepage=faculty_homepage,
        person_name=person_name,
        person_profile_url=person_profile_url,
        raw_relationship=category,
        normalized_relationship=normalized_relationship,
        status=status,
        degree=degree,
        start_year=extract_start_year(block.text),
        end_year=extract_end_year(block.text),
        graduation_year=extract_end_year(block.text) if status == "alumni" and degree else None,
        co_advisor=extract_co_advisor(block.text),
        fellowship=extract_fellowship(block.text),
        current_destination=extract_current_destination(block.text),
        source_url=block.source_url,
        page_section=" > ".join(block.heading_path),
        evidence_text=block.text,
        confidence=0.75,
        verification_status="parsed",
        retrieved_at=None,
        source_links=block.links,
    )


def relationship_from_category(category: str) -> tuple[str | None, str | None, str | None]:
    return RELATIONSHIP_BY_CATEGORY.get(normalize_category(category), (None, None, None))


def relationship_category_for_block(block: SectionBlock) -> str | None:
    if len(block.heading_path) >= 2 and block.heading_path[0].lower() == "students supervised":
        return block.heading_path[1]
    if block.heading_path and normalize_category(block.heading_path[0]) == "alumni":
        return block.heading_path[0]
    return None


def relationship_from_block(block: SectionBlock, category: str) -> tuple[str | None, str | None, str | None]:
    if normalize_category(category) == "alumni":
        return infer_alumni_relationship(block.text)
    return relationship_from_category(category)


def infer_alumni_relationship(text: str) -> tuple[str | None, str | None, str | None]:
    normalized = normalize_category(text)
    if "visiting ph.d. student" in normalized or "visiting phd student" in normalized:
        return ("visitor", "alumni", "PhD")
    if "visiting m.s. student" in normalized or "visiting ms student" in normalized:
        return ("visitor", "alumni", "MSc")
    if "visiting professor" in normalized:
        return ("visitor", "alumni", None)
    if "m.d./ph.d." in normalized or "md/phd" in normalized:
        return ("phd_student", "alumni", "MD/PhD")
    if "ph.d." in normalized or "phd" in normalized:
        return ("phd_student", "alumni", "PhD")
    if "m.s." in normalized or "ms" in normalized:
        return ("masters_student", "alumni", "MSc")
    if "postdoc" in normalized:
        return ("postdoc", "alumni", None)
    if re.search(r"\B'\d{2}\b", text):
        return ("undergraduate_student", "alumni", "BSc")
    if "programmer" in normalized:
        return ("staff", "alumni", None)
    return ("alum", "alumni", None)


def normalize_category(category: str) -> str:
    return re.sub(r"\s+", " ", category.lower()).strip()


def extract_person_name(text: str) -> str | None:
    name = re.split(r"\s*(?:,|\(|')", text, maxsplit=1)[0].strip()
    return name or None


def select_person_profile_url(person_name: str | None, links: list[EvidenceLink]) -> str | None:
    if not person_name:
        return None
    person_key = normalize_link_text(person_name)
    for link in links:
        if normalize_link_text(link.text) == person_key:
            return link.url
    for link in links:
        link_key = normalize_link_text(link.text)
        if person_key and (person_key in link_key or link_key in person_key):
            return link.url
    return None


def normalize_link_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def extract_start_year(text: str) -> int | None:
    range_match = re.search(r"\b((?:19|20)\d{2})\s*[-–]", text)
    if range_match:
        return int(range_match.group(1))
    year_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    return int(year_match.group(1)) if year_match else None


def extract_end_year(text: str) -> int | None:
    range_match = re.search(r"\b(?:19|20)\d{2}\s*[-–]\s*((?:19|20)\d{2})\b", text)
    if range_match:
        return int(range_match.group(1))
    if re.search(r"\b(?:19|20)\d{2}\s*[-–]", text):
        return None
    if re.search(r"\b(?:ph\.?d|m\.?s|postdoc|visiting|programmer|m\.d\./ph\.d\.)\b", text, flags=re.IGNORECASE):
        years = re.findall(r"\b((?:19|20)\d{2})\b", text)
        if years:
            return int(years[-1])
    class_year_match = re.search(r"\B'(\d{2})\b", text)
    if class_year_match:
        year = int(class_year_match.group(1))
        return 1900 + year if year >= 50 else 2000 + year
    return None


def extract_co_advisor(text: str) -> str | None:
    match = re.search(r"\*(?:co-advised|joint) with ([^,]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_current_destination(text: str) -> str | None:
    match = re.search(r",\s*now\s+(.+)$", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_fellowship(text: str) -> str | None:
    candidates = []
    for part in [part.strip() for part in text.split(",")]:
        if re.search(r"\b(fellowship|grfp|gfrp|sgf|ndseg|knight-hennessy)\b", part, flags=re.IGNORECASE):
            candidates.append(part)
    return "; ".join(candidates) if candidates else None


def load_section_blocks(path: Path) -> list[SectionBlock]:
    blocks: list[SectionBlock] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            blocks.append(
                SectionBlock(
                    source_url=payload["source_url"],
                    heading_path=list(payload["heading_path"]),
                    text=payload["text"],
                    links=[
                        EvidenceLink(text=link["text"], url=link["url"])
                        for link in payload.get("links", [])
                    ],
                )
            )
    return blocks
