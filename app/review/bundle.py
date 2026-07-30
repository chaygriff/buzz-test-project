from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.review.confidence import add_relationship_confidence


DATASET_LABEL = "Wetzstein seed"
FACULTY_CONTEXT = "Gordon Wetzstein"
LAB_CONTEXT = "Computational Imaging Lab"


def build_review_bundle(data_dir: Path) -> dict[str, Any]:
    metadata = read_metadata(data_dir)
    people = read_jsonl(data_dir / "people.jsonl")
    relationships = read_jsonl(data_dir / "relationships.jsonl")
    organizations = read_jsonl(data_dir / "organizations.jsonl")
    evidence = read_jsonl(data_dir / "evidence_sources.jsonl")
    decisions = read_jsonl(data_dir / "resolution_decisions.jsonl")
    profile_enrichments = read_jsonl(data_dir / "profile_enrichments.jsonl")
    reconciliation_decisions = build_profile_reconciliation_decisions(people, profile_enrichments)
    backfill_path = data_dir / "backfill_candidates.jsonl"
    if backfill_path.exists():
        backfill_candidates = read_jsonl(backfill_path)
    else:
        backfill_candidates = build_backfill_candidates(metadata, people, relationships, evidence, profile_enrichments)
    scored_relationships = add_relationship_confidence(
        people,
        relationships,
        evidence,
        profile_enrichments,
        decisions,
        reconciliation_decisions,
        backfill_candidates,
    )

    return {
        "metadata": {
            **metadata,
            "bundle_version": 1,
            "counts": {
                "people": len(people),
                "relationships": len(relationships),
                "organizations": len(organizations),
                "evidence_sources": len(evidence),
                "resolution_decisions": len(decisions),
                "profile_enrichments": len(profile_enrichments),
                "profile_reconciliation_decisions": len(reconciliation_decisions),
                "backfill_candidates": len(backfill_candidates),
            },
        },
        "people": people,
        "relationships": scored_relationships,
        "organizations": organizations,
        "evidence_sources": evidence,
        "resolution_decisions": decisions,
        "profile_enrichments": profile_enrichments,
        "profile_reconciliation_decisions": reconciliation_decisions,
        "backfill_candidates": backfill_candidates,
    }


def build_profile_reconciliation_decisions(people: list[dict[str, Any]], enrichments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    people_by_id = {person["person_id"]: person for person in people}
    decisions: list[dict[str, Any]] = []
    for enrichment in enrichments:
        person = people_by_id.get(enrichment.get("person_id"))
        if not person:
            decisions.append(profile_reconciliation_decision(enrichment, None, "missing_person", "needs_review", 0.0))
            continue
        if normalize_name(enrichment.get("person_name", "")) != normalize_name(person.get("display_name", "")):
            decisions.append(profile_reconciliation_decision(enrichment, person, "name_mismatch_same_person_id", "needs_review", 0.72))
    return decisions


def profile_reconciliation_decision(
    enrichment: dict[str, Any],
    person: dict[str, Any] | None,
    rule_name: str,
    review_status: str,
    score: float,
) -> dict[str, Any]:
    person_name = person["display_name"] if person else "Missing person"
    enrichment_name = enrichment.get("person_name") or "Unknown enrichment"
    return {
        "decision_id": stable_id("profile_reconciliation", enrichment.get("enrichment_id"), enrichment.get("person_id"), rule_name),
        "entity_type": "profile_enrichment",
        "candidate_keys": [normalize_name(person_name), normalize_name(enrichment_name)],
        "chosen_entity_id": enrichment.get("person_id"),
        "decision": "join_enrichment_to_person",
        "rule_name": rule_name,
        "score": score,
        "evidence_summary": f"Canonical person is {person_name}; enrichment claimed name is {enrichment_name}. Source: {enrichment.get('source_url') or 'N/A'}.",
        "review_status": review_status,
        "person_id": enrichment.get("person_id"),
        "person_name": person_name,
        "enrichment_id": enrichment.get("enrichment_id"),
        "enrichment_person_name": enrichment_name,
    }


def build_backfill_candidates(
    metadata: dict[str, Any],
    people: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    enrichments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    people_by_id = {person["person_id"]: person for person in people}
    evidence_by_relationship = {item["relationship_id"]: item for item in evidence}
    enriched_person_ids = {item["person_id"] for item in enrichments if item.get("person_id")}
    best_by_person: dict[str, dict[str, Any]] = {}

    for relationship in relationships:
        person = people_by_id.get(relationship["person_id"])
        if not person or relationship["person_id"] in enriched_person_ids:
            continue
        if person.get("profile_urls"):
            continue
        source = evidence_by_relationship.get(relationship["relationship_id"], {})
        candidate = backfill_candidate_for_relationship(metadata, person, relationship, source)
        previous = best_by_person.get(candidate["person_id"])
        if previous is None or candidate["priority_score"] > previous["priority_score"]:
            best_by_person[candidate["person_id"]] = candidate

    return sorted(best_by_person.values(), key=lambda item: (-item["priority_score"], item["person_name"].lower()))


def backfill_candidate_for_relationship(
    metadata: dict[str, Any],
    person: dict[str, Any],
    relationship: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    score, reasons = score_backfill_candidate(relationship)
    terms = search_terms(metadata, person, relationship)
    return {
        "backfill_candidate_id": stable_id("backfill_candidate", person["person_id"], relationship["relationship_id"], evidence.get("evidence_text")),
        "person_id": person["person_id"],
        "person_name": person["display_name"],
        "relationship_id": relationship["relationship_id"],
        "relationship_type": relationship.get("relationship_type"),
        "status": relationship.get("status"),
        "degree": relationship.get("degree"),
        "start_year": relationship.get("start_year"),
        "end_year": relationship.get("end_year"),
        "graduation_year": relationship.get("graduation_year"),
        "source_affiliation": relationship.get("source_affiliation_raw"),
        "current_destination": relationship.get("current_destination_raw"),
        "evidence_text": evidence.get("evidence_text"),
        "source_url": evidence.get("source_url"),
        "source_section": evidence.get("source_section"),
        "priority_bucket": priority_bucket(score),
        "priority_score": score,
        "priority_reasons": reasons,
        "search_query": " ".join(terms),
        "search_terms": terms,
        "verification_status": "needs_people_research",
    }


def score_backfill_candidate(relationship: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    relationship_type = relationship.get("relationship_type")
    if relationship.get("status") == "current":
        score += 30
        reasons.append("current_relationship")
    if relationship_type in {"phd_student", "postdoc"}:
        score += 25
        reasons.append(f"high_value_{relationship_type}")
    elif relationship_type in {"masters_student", "bachelors_student"}:
        score += 12
        reasons.append(f"degree_{relationship_type}")
    elif relationship_type == "visitor":
        score += 4
        reasons.append("visitor_requires_strong_attribution")
    elif relationship_type == "high_school_student":
        score -= 15
        reasons.append("lower_priority_high_school")
    if relationship.get("current_destination_raw"):
        score += 20
        reasons.append("has_seed_current_destination")
    if relationship.get("fellowship"):
        score += 5
        reasons.append("has_seed_fellowship")
    if relationship.get("co_advisor_name_raw"):
        score += 5
        reasons.append("has_seed_coadvisor")
    if relationship.get("start_year") or relationship.get("end_year") or relationship.get("graduation_year"):
        score += 5
        reasons.append("has_seed_year_context")
    return score, reasons or ["missing_explicit_profile_link"]


def priority_bucket(score: int) -> str:
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def search_terms(metadata: dict[str, Any], person: dict[str, Any], relationship: dict[str, Any]) -> list[str]:
    faculty_context = metadata.get("professor_name") or FACULTY_CONTEXT
    lab_context = metadata.get("lab_context") or LAB_CONTEXT
    terms = [
        person.get("display_name"),
        faculty_context,
        relationship.get("source_affiliation_raw"),
        lab_context,
        (relationship.get("relationship_type") or "").replace("_", " "),
        year_range(relationship),
        str(relationship.get("graduation_year") or ""),
        relationship.get("current_destination_raw"),
        relationship.get("fellowship"),
        relationship.get("co_advisor_name_raw"),
    ]
    return dedupe([normalize_space(term) for term in terms if term])


def year_range(relationship: dict[str, Any]) -> str:
    years = [str(relationship.get(key)) for key in ["start_year", "end_year"] if relationship.get(key)]
    return "-".join(years)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_metadata(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "metadata.json"
    if not path.exists():
        return {"dataset_label": DATASET_LABEL}
    metadata = json.loads(path.read_text(encoding="utf-8"))
    return {"dataset_label": metadata.get("dataset_label") or DATASET_LABEL, **metadata}


def write_review_bundle(data_dir: Path, out_path: Path) -> None:
    bundle = build_review_bundle(data_dir)
    out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_name(value: str) -> str:
    normalized = re.sub(r"[.,]", "", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("||".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


if __name__ == "__main__":
    write_review_bundle(Path("app/review/ui/data"), Path("app/review/ui/data/review_bundle.json"))
