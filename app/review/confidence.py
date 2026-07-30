from __future__ import annotations

from typing import Any


def add_relationship_confidence(
    people: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    evidence_sources: list[dict[str, Any]],
    profile_enrichments: list[dict[str, Any]],
    resolution_decisions: list[dict[str, Any]],
    profile_reconciliation_decisions: list[dict[str, Any]],
    backfill_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    people_by_id = {person["person_id"]: person for person in people}
    evidence_by_relationship = {item["relationship_id"]: item for item in evidence_sources}
    enrichment_by_person = first_by_key(profile_enrichments, "person_id")
    reconciliation_by_person = first_by_key(profile_reconciliation_decisions, "person_id")
    backfill_by_person = first_by_key(backfill_candidates, "person_id")
    review_decision_by_person = review_decisions_by_person(resolution_decisions)

    scored_relationships: list[dict[str, Any]] = []
    for relationship in relationships:
        person = people_by_id.get(relationship["person_id"], {})
        evidence = evidence_by_relationship.get(relationship["relationship_id"], {})
        person_id = relationship["person_id"]
        score = score_relationship_confidence(
            person=person,
            relationship=relationship,
            evidence=evidence,
            enrichment=enrichment_by_person.get(person_id),
            review_decision=review_decision_by_person.get(person_id),
            reconciliation_decision=reconciliation_by_person.get(person_id),
            backfill_candidate=backfill_by_person.get(person_id),
        )
        scored_relationships.append({**relationship, **score})
    return scored_relationships


def score_relationship_confidence(
    *,
    person: dict[str, Any],
    relationship: dict[str, Any],
    evidence: dict[str, Any],
    enrichment: dict[str, Any] | None,
    review_decision: dict[str, Any] | None,
    reconciliation_decision: dict[str, Any] | None,
    backfill_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    penalties: list[str] = []

    relationship_score, relationship_reasons = relationship_evidence_score(relationship, evidence)
    identity_score, identity_reasons = identity_score_for_person(person, enrichment)
    context_score, context_reasons = context_completeness_score(relationship)
    score += relationship_score + identity_score + context_score
    reasons.extend([*relationship_reasons, *identity_reasons, *context_reasons])

    if reconciliation_decision:
        score -= 25
        penalties.append("profile_reconciliation_needed")
    if review_decision:
        score -= 30
        penalties.append("relationship_review_needed")
    if backfill_candidate:
        score -= 15
        penalties.append("profile_backfill_queued")
    if not person.get("profile_urls"):
        score -= 10
        penalties.append("missing_profile_url")
    if not enrichment:
        score -= 6
        penalties.append("missing_profile_enrichment")
    elif enrichment.get("fetch_status") in {"skipped", "identifier_only"}:
        score -= 4
        penalties.append(f"profile_fetch_{enrichment.get('fetch_status')}")

    bounded_score = max(0, min(100, score))
    bucket = confidence_bucket(bounded_score)
    if review_decision or reconciliation_decision:
        bucket = "needs_review"

    return {
        "confidence_score": bounded_score,
        "confidence_bucket": bucket,
        "confidence_reasons": reasons[:8],
        "confidence_penalties": penalties,
    }


def relationship_evidence_score(relationship: dict[str, Any], evidence: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    verification_status = relationship.get("verification_status")
    if verification_status in {"source_roster_verified", "parsed"}:
        score += 20
        reasons.append(verification_status)
    elif verification_status:
        score += 12
        reasons.append(f"relationship_{verification_status}")

    confidence = relationship.get("confidence")
    if isinstance(confidence, int | float):
        score += round(max(0, min(1, confidence)) * 10)
        reasons.append("parser_confidence_present")

    if evidence.get("evidence_text"):
        score += 5
        reasons.append("has_evidence_text")
    if evidence.get("source_url"):
        score += 3
        reasons.append("has_source_url")
    if evidence.get("source_section"):
        score += 2
        reasons.append("has_source_section")

    return min(score, 40), reasons


def identity_score_for_person(person: dict[str, Any], enrichment: dict[str, Any] | None) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if person.get("profile_urls"):
        score += 7
        reasons.append("has_profile_url")
    if not enrichment:
        return score, reasons

    if enrichment.get("verification_status") in {"verified", "source_roster_link", "source_roster_verified", "linked"}:
        score += 6
        reasons.append(f"profile_{enrichment.get('verification_status')}")
    if enrichment.get("personal_website_url"):
        score += 8
        reasons.append("has_personal_website")
    if enrichment.get("github_url"):
        score += 5
        reasons.append("has_github")
    if enrichment.get("google_scholar_url"):
        score += 6
        reasons.append("has_google_scholar")
    if enrichment.get("linkedin_url"):
        score += 5
        reasons.append("has_linkedin")
    if enrichment.get("short_biography"):
        score += 3
        reasons.append("has_short_biography")
    if enrichment.get("homepage_claimed_name"):
        score += 1
        reasons.append("has_homepage_claimed_name")

    return min(score, 35), reasons


def context_completeness_score(relationship: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if relationship.get("source_affiliation_raw") or relationship.get("source_affiliation_org_id"):
        score += 4
        reasons.append("has_source_affiliation")
    if relationship.get("relationship_type") and relationship.get("status"):
        score += 3
        reasons.append("has_relationship_type_and_status")
    if relationship.get("start_year") or relationship.get("end_year") or relationship.get("graduation_year"):
        score += 3
        reasons.append("has_year_context")
    if relationship.get("degree"):
        score += 2
        reasons.append("has_degree")
    if relationship.get("current_destination_raw") or relationship.get("current_destination_org_id"):
        score += 2
        reasons.append("has_destination")
    if relationship.get("co_advisor_name_raw") or relationship.get("fellowship"):
        score += 1
        reasons.append("has_advisor_or_fellowship")

    return min(score, 15), reasons


def confidence_bucket(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def first_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if value and value not in result:
            result[value] = row
    return result


def review_decisions_by_person(decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if decision.get("review_status") != "needs_review":
            continue
        for person_id in person_ids_for_decision(decision):
            result.setdefault(person_id, decision)
    return result


def person_ids_for_decision(decision: dict[str, Any]) -> list[str]:
    return [
        person_id
        for person_id in [
            decision.get("person_id"),
            decision.get("chosen_entity_id"),
            *(decision.get("candidate_person_ids") or []),
        ]
        if person_id
    ]
