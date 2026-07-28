from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from app.models.entities import (
    CanonicalRelationshipRecord,
    EntityResolutionResult,
    EvidenceSourceRecord,
    FacultyRecord,
    OrganizationRecord,
    PersonRecord,
    ResolutionDecisionRecord,
)
from app.models.records import EvidenceLink, RelationshipRecord


def resolve_relationship_entities(records: list[RelationshipRecord]) -> EntityResolutionResult:
    people: list[PersonRecord] = []
    faculty: list[FacultyRecord] = []
    organizations_by_id: dict[str, OrganizationRecord] = {}
    relationships: list[CanonicalRelationshipRecord] = []
    evidence_sources: list[EvidenceSourceRecord] = []
    decisions: list[ResolutionDecisionRecord] = []

    faculty_by_context = build_faculty(records, people, organizations_by_id)
    people_by_key = group_people(records)
    person_ids_by_record_key: dict[tuple[str, str], str] = {}

    for group_key, group_records in sorted(people_by_key.items()):
        person_name = first_not_none(record.person_name for record in group_records)
        if not person_name:
            continue
        profile_urls = sorted({record.person_profile_url for record in group_records if record.person_profile_url})
        person_id = deterministic_id(
            "person",
            normalize_name(person_name),
            profile_urls[0] if profile_urls else group_key[1],
        )
        resolution_status = "resolved" if len(group_records) > 1 or profile_urls else "single_source"
        people.append(
            PersonRecord(
                person_id=person_id,
                display_name=person_name,
                name_key=normalize_name(person_name),
                profile_urls=profile_urls,
                resolution_status=resolution_status,
            )
        )
        for record in group_records:
            person_ids_by_record_key[record_identity(record)] = person_id
        if len(group_records) > 1:
            decisions.append(
                ResolutionDecisionRecord(
                    decision_id=deterministic_id("decision", "person", person_id, *sorted(record.evidence_text for record in group_records)),
                    entity_type="person",
                    candidate_keys=[normalize_name(record.person_name or "") for record in group_records],
                    chosen_entity_id=person_id,
                    decision="auto_merge",
                    rule_name="exact_name_same_faculty_context_or_profile_url",
                    score=0.9 if profile_urls else 0.82,
                    evidence_summary=summarize_merge_evidence(group_records),
                    review_status="accepted",
                )
            )

    for faculty_record in faculty_by_context.values():
        faculty.append(faculty_record)

    for record in records:
        if not record.person_name:
            continue
        faculty_context = faculty_context_key(record)
        faculty_record = faculty_by_context[faculty_context]
        person_id = person_ids_by_record_key[record_identity(record)]
        source_affiliation_raw = extract_source_affiliation(record.evidence_text)
        source_affiliation_org_id = add_organization(source_affiliation_raw, "university", organizations_by_id)
        current_destination_org_id = add_destination_organization(record.current_destination, organizations_by_id)
        relationship_id = deterministic_id(
            "rel",
            faculty_record.faculty_id,
            person_id,
            record.normalized_relationship or "",
            record.status or "",
            str(record.start_year or ""),
            str(record.end_year or ""),
            record.source_url,
            record.evidence_text,
        )
        relationships.append(
            CanonicalRelationshipRecord(
                relationship_id=relationship_id,
                faculty_id=faculty_record.faculty_id,
                person_id=person_id,
                relationship_type=record.normalized_relationship,
                status=record.status,
                degree=record.degree,
                start_year=record.start_year,
                end_year=record.end_year,
                graduation_year=record.graduation_year,
                co_advisor_person_id=None,
                co_advisor_name_raw=record.co_advisor,
                fellowship=record.fellowship,
                source_affiliation_org_id=source_affiliation_org_id,
                source_affiliation_raw=source_affiliation_raw,
                current_destination_org_id=current_destination_org_id,
                current_destination_raw=record.current_destination,
                confidence=record.confidence,
                verification_status=record.verification_status,
            )
        )
        evidence_sources.append(
            EvidenceSourceRecord(
                evidence_id=deterministic_id("evidence", record.source_url, record.page_section or "", record.evidence_text),
                relationship_id=relationship_id,
                source_url=record.source_url,
                source_section=record.page_section,
                evidence_text=record.evidence_text,
                retrieved_at=record.retrieved_at,
            )
        )

    return EntityResolutionResult(
        people=sorted(people, key=lambda person: person.display_name),
        faculty=sorted(faculty, key=lambda item: item.faculty_id),
        organizations=sorted(organizations_by_id.values(), key=lambda org: org.name_key),
        relationships=relationships,
        evidence_sources=evidence_sources,
        resolution_decisions=sorted(decisions, key=lambda decision: decision.decision_id),
    )


def build_faculty(
    records: list[RelationshipRecord],
    people: list[PersonRecord],
    organizations_by_id: dict[str, OrganizationRecord],
) -> dict[str, FacultyRecord]:
    faculty_by_context: dict[str, FacultyRecord] = {}
    for record in records:
        context = faculty_context_key(record)
        if context in faculty_by_context:
            continue
        faculty_name = record.faculty_name or "Unknown faculty"
        faculty_person_id = deterministic_id("person", normalize_name(faculty_name), record.faculty_homepage or record.source_url)
        institution_id = add_organization(record.faculty_institution, "university", organizations_by_id)
        if not any(person.person_id == faculty_person_id for person in people):
            people.append(
                PersonRecord(
                    person_id=faculty_person_id,
                    display_name=faculty_name,
                    name_key=normalize_name(faculty_name),
                    profile_urls=[record.faculty_homepage] if record.faculty_homepage else [],
                    primary_affiliation_org_id=institution_id,
                    primary_role="faculty",
                    resolution_status="seed_faculty",
                )
            )
        faculty_by_context[context] = FacultyRecord(
            faculty_id=deterministic_id("faculty", faculty_person_id, institution_id or "", record.faculty_homepage or ""),
            person_id=faculty_person_id,
            institution_id=institution_id,
            department=None,
            title=None,
            homepage_url=record.faculty_homepage,
        )
    return faculty_by_context


def group_people(records: list[RelationshipRecord]) -> dict[tuple[str, str], list[RelationshipRecord]]:
    grouped: dict[tuple[str, str], list[RelationshipRecord]] = defaultdict(list)
    for record in records:
        if not record.person_name:
            continue
        profile_or_context = record.person_profile_url or faculty_context_key(record)
        grouped[(normalize_name(record.person_name), profile_or_context)].append(record)
    return grouped


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"[.,]", "", normalized.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_organization_name(value: str) -> str:
    organization, _departments = split_org_and_departments(value)
    normalized = unicodedata.normalize("NFKC", organization)
    normalized = re.sub(r"[.,]", "", normalized.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_missing(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.upper() == "N/A":
        return None
    return normalized


def split_org_and_departments(value: str) -> tuple[str, list[str]]:
    match = re.match(r"^(?P<org>.+?)\s*\((?P<departments>[^)]+)\)\s*$", value.strip())
    if not match:
        return value.strip(), []
    departments = [department.strip() for department in re.split(r"[/,]", match.group("departments")) if department.strip()]
    return match.group("org").strip(), departments


def add_organization(
    raw_name: str | None,
    org_type: str,
    organizations_by_id: dict[str, OrganizationRecord],
) -> str | None:
    raw_name = normalize_missing(raw_name)
    if raw_name is None:
        return None
    name, _departments = split_org_and_departments(raw_name)
    name_key = normalize_organization_name(raw_name)
    organization_id = deterministic_id("org", org_type, name_key)
    organizations_by_id.setdefault(
        organization_id,
        OrganizationRecord(
            organization_id=organization_id,
            name=name,
            name_key=name_key,
            org_type=org_type,
        ),
    )
    return organization_id


def add_destination_organization(
    current_destination: str | None,
    organizations_by_id: dict[str, OrganizationRecord],
) -> str | None:
    current_destination = normalize_missing(current_destination)
    if current_destination is None:
        return None
    match = re.search(r"\bat\s+(.+)$", current_destination, flags=re.IGNORECASE)
    if not match:
        return None
    return add_organization(match.group(1), "organization", organizations_by_id)


def extract_source_affiliation(evidence_text: str) -> str | None:
    parts = [part.strip() for part in evidence_text.split(",")]
    if len(parts) < 2:
        return None
    candidate = parts[1]
    if re.search(r"\b(?:19|20)\d{2}\b|postdoc|visiting|student|phd|msc|bsc", candidate, flags=re.IGNORECASE):
        return None
    return normalize_missing(candidate)


def faculty_context_key(record: RelationshipRecord) -> str:
    return record.faculty_homepage or record.source_url


def record_identity(record: RelationshipRecord) -> tuple[str, str]:
    return (record.source_url, record.evidence_text)


def deterministic_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\u001f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def first_not_none(values) -> str | None:
    for value in values:
        if value:
            return value
    return None


def summarize_merge_evidence(records: list[RelationshipRecord]) -> str:
    years = [str(record.start_year) for record in records if record.start_year]
    relationship_types = sorted({record.normalized_relationship or "unknown" for record in records})
    return f"Exact name match in one faculty context across {', '.join(relationship_types)} records; years: {', '.join(years) or 'unknown'}."


def load_relationship_records(path: Path) -> list[RelationshipRecord]:
    records: list[RelationshipRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            payload["source_links"] = [
                EvidenceLink(text=link["text"], url=link["url"])
                for link in payload.get("source_links", [])
            ]
            records.append(RelationshipRecord(**payload))
    return records
