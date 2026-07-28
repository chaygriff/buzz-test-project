from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnrichmentCandidateRecord:
    candidate_id: str
    person_id: str
    person_name: str
    relationship_id: str
    url: str
    source_type: str
    source_url: str
    source_section: str | None
    evidence_text: str


@dataclass(frozen=True)
class BackfillCandidateRecord:
    backfill_candidate_id: str
    person_id: str
    person_name: str
    relationship_id: str
    relationship_type: str | None
    status: str | None
    degree: str | None
    start_year: int | None
    end_year: int | None
    graduation_year: int | None
    source_affiliation: str | None
    current_destination: str | None
    evidence_text: str
    source_url: str
    source_section: str | None
    priority_bucket: str
    priority_score: int
    priority_reasons: list[str]
    search_query: str
    search_terms: list[str]
    research_guidance: list[str]
    verification_status: str


@dataclass(frozen=True)
class ProfileEnrichmentRecord:
    enrichment_id: str
    candidate_id: str
    person_id: str
    person_name: str
    candidate_url: str
    final_url: str | None
    source_type: str
    fetch_status: str
    skip_reason: str | None
    status_code: int | None
    content_type: str | None
    profile_title: str | None
    homepage_claimed_name: str | None
    short_biography: str | None
    personal_website_url: str | None
    github_url: str | None
    google_scholar_url: str | None
    linkedin_url: str | None
    source_url: str
    evidence_text: str
    retrieved_at: str | None
    verification_status: str
