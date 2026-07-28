from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationshipRecord:
    faculty_name: str | None
    faculty_institution: str | None
    faculty_homepage: str | None
    person_name: str | None
    person_profile_url: str | None
    raw_relationship: str | None
    normalized_relationship: str | None
    status: str | None
    degree: str | None
    start_year: int | None
    end_year: int | None
    graduation_year: int | None
    co_advisor: str | None
    fellowship: str | None
    current_destination: str | None
    source_url: str
    page_section: str | None
    evidence_text: str
    confidence: float | None
    verification_status: str
    retrieved_at: str | None
