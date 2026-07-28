from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PersonRecord:
    person_id: str
    display_name: str
    name_key: str
    profile_urls: list[str] = field(default_factory=list)
    primary_affiliation_org_id: str | None = None
    primary_role: str | None = None
    resolution_status: str = "resolved"


@dataclass(frozen=True)
class FacultyRecord:
    faculty_id: str
    person_id: str
    institution_id: str | None
    department: str | None
    title: str | None
    homepage_url: str | None
    lab_id: str | None = None
    research_areas: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OrganizationRecord:
    organization_id: str
    name: str
    name_key: str
    org_type: str
    parent_org_id: str | None = None
    url: str | None = None
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CanonicalRelationshipRecord:
    relationship_id: str
    faculty_id: str
    person_id: str
    relationship_type: str | None
    status: str | None
    degree: str | None
    start_year: int | None
    end_year: int | None
    graduation_year: int | None
    co_advisor_person_id: str | None
    co_advisor_name_raw: str | None
    fellowship: str | None
    source_affiliation_org_id: str | None
    source_affiliation_raw: str | None
    current_destination_org_id: str | None
    current_destination_raw: str | None
    confidence: float | None
    verification_status: str


@dataclass(frozen=True)
class EvidenceSourceRecord:
    evidence_id: str
    relationship_id: str
    source_url: str
    source_section: str | None
    evidence_text: str
    retrieved_at: str | None
    parser_version: str | None = None
    raw_cache_key: str | None = None


@dataclass(frozen=True)
class ResolutionDecisionRecord:
    decision_id: str
    entity_type: str
    candidate_keys: list[str]
    chosen_entity_id: str | None
    decision: str
    rule_name: str
    score: float
    evidence_summary: str
    review_status: str


@dataclass(frozen=True)
class EntityResolutionResult:
    people: list[PersonRecord]
    faculty: list[FacultyRecord]
    organizations: list[OrganizationRecord]
    relationships: list[CanonicalRelationshipRecord]
    evidence_sources: list[EvidenceSourceRecord]
    resolution_decisions: list[ResolutionDecisionRecord]
