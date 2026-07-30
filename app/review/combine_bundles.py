from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.review.bundle import build_review_bundle


DATASETS = [
    {
        "key": "gordon_wetzstein",
        "label": "Gordon Wetzstein pilot",
        "professor_name": "Gordon Wetzstein",
        "bundle_path": Path("app/review/ui/source_bundles/gordon_wetzstein_review_bundle.json"),
    },
    {
        "key": "jiajun_wu",
        "label": "Jiajun Wu pilot",
        "professor_name": "Jiajun Wu",
        "bundle_path": Path("app/review/ui/source_bundles/jiajun_wu_review_bundle.json"),
    },
    {
        "key": "maneesh_agrawala",
        "label": "Maneesh Agrawala pilot",
        "professor_name": "Maneesh Agrawala",
        "bundle_path": Path("app/review/ui/source_bundles/maneesh_agrawala_review_bundle.json"),
    },
]

ARRAY_KEYS = [
    "people",
    "relationships",
    "organizations",
    "evidence_sources",
    "resolution_decisions",
    "profile_enrichments",
    "profile_reconciliation_decisions",
    "backfill_candidates",
]

JSONL_FILENAMES = {
    "people": "people.jsonl",
    "relationships": "relationships.jsonl",
    "organizations": "organizations.jsonl",
    "evidence_sources": "evidence_sources.jsonl",
    "resolution_decisions": "resolution_decisions.jsonl",
    "profile_enrichments": "profile_enrichments.jsonl",
    "backfill_candidates": "backfill_candidates.jsonl",
}


def combine_bundles(repo_root: Path, out_dir: Path) -> dict[str, Any]:
    combined = {key: [] for key in ARRAY_KEYS}
    dataset_summaries = []

    for config in DATASETS:
        bundle_path = (repo_root / config["bundle_path"]).resolve()
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        summary = {
            "key": config["key"],
            "label": config["label"],
            "professor_name": config["professor_name"],
            "source_bundle": str(bundle_path),
            "counts": bundle.get("metadata", {}).get("counts", {}),
        }
        dataset_summaries.append(summary)
        for key in ARRAY_KEYS:
            rows = [annotate_row(row, config) for row in bundle.get(key, [])]
            combined[key].extend(rows)

    merge_duplicate_people_by_id(combined)
    merge_people_by_profile_url(combined)
    mark_relationship_conflicts(combined)

    metadata = {
        "dataset_label": "Stanford faculty pilots: Gordon Wetzstein + Jiajun Wu + Maneesh Agrawala",
        "professors": [
            {"key": item["key"], "label": item["label"], "professor_name": item["professor_name"]}
            for item in dataset_summaries
        ],
        "source_datasets": dataset_summaries,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    for key, filename in JSONL_FILENAMES.items():
        write_jsonl(out_dir / filename, combined[key])

    bundle = build_review_bundle(out_dir)
    (out_dir / "review_bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    return bundle


def annotate_row(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(row)
    annotated.setdefault("dataset_key", config["key"])
    annotated.setdefault("dataset_label", config["label"])
    annotated.setdefault("professor_name", config["professor_name"])
    return annotated


def merge_duplicate_people_by_id(combined: dict[str, list[dict[str, Any]]]) -> None:
    people_by_id: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for person in combined["people"]:
        existing = people_by_id.get(person["person_id"])
        if existing is None:
            people_by_id[person["person_id"]] = person
            deduped.append(person)
            continue
        merge_person_rows(existing, person)
    combined["people"] = deduped


def merge_people_by_profile_url(combined: dict[str, list[dict[str, Any]]]) -> None:
    people_by_id = {person["person_id"]: person for person in combined["people"]}
    person_ids_by_url: dict[str, set[str]] = {}
    for person in combined["people"]:
        for url in profile_urls_for_person(person):
            person_ids_by_url.setdefault(url, set()).add(person["person_id"])
    for enrichment in combined["profile_enrichments"]:
        person_id = enrichment.get("person_id")
        if person_id in people_by_id:
            for url in profile_urls_for_enrichment(enrichment):
                person_ids_by_url.setdefault(url, set()).add(person_id)

    remapped_ids: dict[str, str] = {}
    for person_ids in person_ids_by_url.values():
        active_ids = {remapped_ids.get(person_id, person_id) for person_id in person_ids}
        if len(active_ids) < 2 or len(dataset_keys_for_people(active_ids, people_by_id)) < 2:
            continue
        canonical_id = choose_canonical_person_id(active_ids, people_by_id)
        for person_id in active_ids:
            if person_id != canonical_id:
                remapped_ids[person_id] = canonical_id
                merge_person_rows(people_by_id[canonical_id], people_by_id[person_id])

    if not remapped_ids:
        return

    for key in ["relationships", "profile_enrichments", "backfill_candidates"]:
        for row in combined[key]:
            person_id = row.get("person_id")
            if person_id in remapped_ids:
                row["person_id"] = remapped_ids[person_id]

    combined["profile_enrichments"] = dedupe_profile_enrichments(combined["profile_enrichments"])
    combined["people"] = [
        person
        for person in combined["people"]
        if person["person_id"] not in remapped_ids
    ]


def profile_urls_for_person(person: dict[str, Any]) -> set[str]:
    return {normalize_url(url) for url in person.get("profile_urls", []) if normalize_url(url)}


def profile_urls_for_enrichment(enrichment: dict[str, Any]) -> set[str]:
    return {
        normalize_url(enrichment.get(key))
        for key in ["final_url", "personal_website_url", "candidate_url"]
        if normalize_url(enrichment.get(key))
    }


def normalize_url(url: str | None) -> str:
    return (url or "").rstrip("/")


def choose_canonical_person_id(person_ids: set[str], people_by_id: dict[str, dict[str, Any]]) -> str:
    return sorted(
        person_ids,
        key=lambda person_id: (
            people_by_id[person_id].get("primary_role") != "faculty",
            -len(people_by_id[person_id].get("display_name", "")),
            people_by_id[person_id].get("display_name", "").lower(),
        ),
    )[0]


def dataset_keys_for_people(person_ids: set[str], people_by_id: dict[str, dict[str, Any]]) -> set[str]:
    return {people_by_id[person_id].get("dataset_key", "") for person_id in person_ids}


def dedupe_profile_enrichments(enrichments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str | None, str], dict[str, Any]] = {}
    for enrichment in enrichments:
        key = (enrichment.get("person_id"), normalize_url(enrichment.get("personal_website_url") or enrichment.get("final_url")))
        if not key[1]:
            key = (enrichment.get("person_id"), enrichment.get("enrichment_id", ""))
        previous = best_by_key.get(key)
        if previous is None or enrichment_quality(enrichment) > enrichment_quality(previous):
            best_by_key[key] = enrichment
    return list(best_by_key.values())


def enrichment_quality(enrichment: dict[str, Any]) -> int:
    return sum(
        1
        for key in ["short_biography", "google_scholar_url", "linkedin_url", "github_url"]
        if enrichment.get(key)
    )


def merge_person_rows(canonical: dict[str, Any], duplicate: dict[str, Any]) -> None:
    canonical["profile_urls"] = sorted(
        {
            *canonical.get("profile_urls", []),
            *duplicate.get("profile_urls", []),
        }
    )
    if not canonical.get("primary_affiliation_org_id"):
        canonical["primary_affiliation_org_id"] = duplicate.get("primary_affiliation_org_id")
    if not canonical.get("primary_role"):
        canonical["primary_role"] = duplicate.get("primary_role")
    canonical["resolution_status"] = "cross_dataset_profile_url_merge"


def mark_relationship_conflicts(combined: dict[str, list[dict[str, Any]]]) -> None:
    relationships_by_person: dict[str, list[dict[str, Any]]] = {}
    for relationship in combined["relationships"]:
        relationships_by_person.setdefault(relationship["person_id"], []).append(relationship)

    existing_decision_ids = {decision.get("decision_id") for decision in combined["resolution_decisions"]}
    for person_id, relationships in relationships_by_person.items():
        statuses = {relationship.get("status") for relationship in relationships}
        if not {"current", "alumni"}.issubset(statuses):
            continue
        alumni_records = [relationship for relationship in relationships if relationship.get("status") == "alumni"]
        if not any(relationship.get("current_destination_raw") for relationship in alumni_records):
            continue
        decision = relationship_conflict_decision(person_id, relationships)
        if decision["decision_id"] not in existing_decision_ids:
            combined["resolution_decisions"].append(decision)
            existing_decision_ids.add(decision["decision_id"])


def relationship_conflict_decision(person_id: str, relationships: list[dict[str, Any]]) -> dict[str, Any]:
    relationship_ids = sorted(relationship["relationship_id"] for relationship in relationships)
    professor_summaries = sorted(
        f"{relationship.get('professor_name')}: {relationship.get('relationship_type')} / {relationship.get('status')}"
        for relationship in relationships
    )
    destination = next(
        (
            relationship.get("current_destination_raw")
            for relationship in relationships
            if relationship.get("status") == "alumni" and relationship.get("current_destination_raw")
        ),
        "N/A",
    )
    return {
        "decision_id": stable_id("decision", "relationship_conflict", person_id, *relationship_ids),
        "entity_type": "relationship",
        "candidate_keys": professor_summaries,
        "chosen_entity_id": person_id,
        "decision": "mark_relationship_conflict",
        "rule_name": "cross_dataset_current_alumni_status_conflict",
        "score": 0.68,
        "evidence_summary": f"Cross-dataset relationship status conflict for one merged person. Contexts: {'; '.join(professor_summaries)}. Alumni destination observed: {destination}.",
        "review_status": "needs_review",
        "person_id": person_id,
        "candidate_person_ids": [person_id],
    }


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("||".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine review bundles for the static review UI.")
    parser.add_argument("--out-dir", type=Path, default=Path("app/review/ui/data"))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    combine_bundles(repo_root, args.out_dir)


if __name__ == "__main__":
    main()
