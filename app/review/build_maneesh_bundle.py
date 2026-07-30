from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.exports.jsonl import write_jsonl
from app.models.records import RelationshipRecord
from app.resolution.entity_resolver import deterministic_id, resolve_relationship_entities
from app.review.bundle import build_review_bundle


FACULTY_NAME = "Maneesh Agrawala"
FACULTY_INSTITUTION = "Stanford University"
FACULTY_HOMEPAGE = "https://graphics.stanford.edu/~maneesh/"
RETRIEVED_AT = "2026-07-30T01:21:19+00:00"
OUTBOUND_PROFILE_ENRICHMENTS_PATH = Path("app/review/ui/source_bundles/maneesh_agrawala_profile_enrichments.jsonl")


ROSTER: list[dict[str, Any]] = [
    {"name": "Maty Bohacek", "url": "https://www.matyasbohacek.com/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Matthew Caren", "url": "https://matthewcaren.github.io/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Jean-Peïc Chou", "url": "https://www.linkedin.com/in/jeanpeicchou/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Jihyeon Je", "url": "https://jihyeonje.com/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Nicholas Jennings", "url": "https://nicholasjj.github.io/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "R. Kenny Jones", "url": "https://rkjones4.github.io/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Jiaju Ma", "url": "https://majiaju.io/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Mia Tang", "url": "https://www.mia-tang.com/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Chuan Yan", "url": "https://nauhcnay.github.io/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Chong Zeng", "url": "https://www.chong-zeng.com/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Lvmin Zhang", "url": "https://lllyasviel.github.io/lvmin_zhang/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Sharon Zhang", "url": "https://sxzhang25.github.io/", "section": "Students, Postdocs & Visitors", "type": "affiliate", "status": "current"},
    {"name": "Sean Arietta", "url": "https://sarietta.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Adrien Bousseau", "url": "http://www-sop.inria.fr/members/Adrien.Bousseau/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Robert Carroll", "url": "https://www.linkedin.com/in/robert-carroll-97b71738/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Lydia Chilton", "url": "https://www.cs.columbia.edu/~chilton/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Will Crichton", "url": "http://willcrichton.net/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Ross Daly", "url": None, "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Abe Davis", "url": "http://www.abedavis.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Ohad Fried", "url": "http://www.ohadf.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Shiry Ginosar", "url": "http://www.eecs.berkeley.edu/~shiry/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Ahna Girshick", "url": "http://lightdark.org/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Madeleine Grunde-McLaughlin", "url": "https://madeleinegrunde.github.io/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Alex Hall", "url": "https://www.linkedin.com/in/frederickalexanderhall/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jonathan Harper", "url": "http://harperj.github.io/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jeffrey Heer", "url": "http://homes.cs.washington.edu/~jheer/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Robert Held", "url": "https://www.linkedin.com/in/robin-held/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Enamul Hoque", "url": "https://www.yorku.ca/enamulh/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jessica Hullman", "url": "http://users.eecs.northwestern.edu/~jhullman/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Terrell Ibanez", "url": "https://www.linkedin.com/in/ibnzterrell", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "David Jacobs", "url": "http://graphics.stanford.edu/~dejacobs/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jennifer Jacobs", "url": "http://jenniferjacobs.mat.ucsb.edu/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Olga Karpenko", "url": "https://www.usfca.edu/faculty/olga-karpenko", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Dae Hyun Kim", "url": "http://dhkim16.github.io/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jeongyeon Kim", "url": "https://www.jeongyeon.kim/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Juho Kim", "url": "http://juhokim.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Kenrick Kin", "url": "https://www.linkedin.com/in/kenrick-kin-51575753/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Nicholas Kong", "url": "https://www.linkedin.com/in/kongn", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Mackenzie Leake", "url": "http://mackenzieleake.com", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Janel Lee", "url": "https://www.linkedin.com/in/jihyeonlee/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jingyi Li", "url": "http://jingyi.me/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Sean Liu", "url": "https://lseancs.github.io/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Anelise Newman", "url": "https://anelisenewman.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "James O'Shea", "url": "http://jposhea.org/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Amy Pavel", "url": "http://amypavel.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Anyi Rao", "url": "https://anyirao.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Colorado Reed", "url": "https://cjrd.github.io/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jacob Ritchie", "url": "https://www.jacobritchie.xyz/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Steve Rubin", "url": "http://ssrubin.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Jason Sanders", "url": "https://www.linkedin.com/in/jasonpsanders/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Mira Shalah", "url": "https://www.linkedin.com/in/mira-shalah-abboud-4082a110a/?originalSubdomain=il", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Evan Strasnick", "url": "http://cs.stanford.edu/people/estrasni/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Anh Truong", "url": None, "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Wesley Willett", "url": "http://www.wjwillett.net/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "Sofia Wyetzner", "url": "https://www.sofiawyetzner.com/", "section": "Alumni", "type": "alumni", "status": "alumni"},
    {"name": "JiaXian Yao", "url": "https://www.linkedin.com/in/eric-yao-a1703a55/", "section": "Alumni", "type": "alumni", "status": "alumni"},
]


def main() -> None:
    bundle_path = Path("app/review/ui/source_bundles/maneesh_agrawala_review_bundle.json")
    records = [relationship_record(item) for item in ROSTER]
    result = resolve_relationship_entities(records)

    with tempfile.TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir)
        write_jsonl(out_dir / "people.jsonl", result.people)
        write_jsonl(out_dir / "relationships.jsonl", result.relationships)
        write_jsonl(out_dir / "organizations.jsonl", result.organizations)
        write_jsonl(out_dir / "evidence_sources.jsonl", result.evidence_sources)
        write_jsonl(out_dir / "resolution_decisions.jsonl", result.resolution_decisions)
        write_jsonl(out_dir / "profile_enrichments.jsonl", profile_enrichments(result.people))
        (out_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "dataset_label": "Maneesh Agrawala pilot",
                    "professor_name": FACULTY_NAME,
                    "lab_context": "Stanford Graphics",
                    "source_homepage": FACULTY_HOMEPAGE,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        bundle = build_review_bundle(out_dir)

    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def relationship_record(item: dict[str, Any]) -> RelationshipRecord:
    evidence_text = f"{item['name']}, Stanford University, {item['section']}"
    return RelationshipRecord(
        faculty_name=FACULTY_NAME,
        faculty_institution=FACULTY_INSTITUTION,
        faculty_homepage=FACULTY_HOMEPAGE,
        person_name=item["name"],
        person_profile_url=item["url"],
        raw_relationship=item["section"],
        normalized_relationship=item["type"],
        status=item["status"],
        degree=None,
        start_year=None,
        end_year=None,
        graduation_year=None,
        co_advisor=None,
        fellowship=None,
        current_destination=None,
        source_url=FACULTY_HOMEPAGE,
        page_section=f"Homepage left panel > {item['section']}",
        evidence_text=evidence_text,
        confidence=0.82,
        verification_status="source_roster_verified",
        retrieved_at=RETRIEVED_AT,
        source_links=[],
    )


def profile_enrichments(people: list[Any]) -> list[dict[str, Any]]:
    if OUTBOUND_PROFILE_ENRICHMENTS_PATH.exists():
        return remap_profile_enrichments(read_jsonl(OUTBOUND_PROFILE_ENRICHMENTS_PATH), people)

    enrichments: list[dict[str, Any]] = []
    for person in people:
        payload = asdict(person)
        if payload.get("primary_role") == "faculty" or not payload.get("profile_urls"):
            continue
        url = payload["profile_urls"][0]
        is_linkedin = "linkedin.com/in/" in url
        enrichments.append(
            {
                "enrichment_id": deterministic_id("enrichment", payload["person_id"], url),
                "candidate_id": deterministic_id("manual_candidate", payload["display_name"], url),
                "person_id": payload["person_id"],
                "person_name": payload["display_name"],
                "candidate_url": url,
                "final_url": url,
                "source_type": "source_roster_link",
                "fetch_status": "not_fetched",
                "skip_reason": None,
                "status_code": None,
                "content_type": None,
                "profile_title": None,
                "homepage_claimed_name": payload["display_name"],
                "short_biography": None,
                "personal_website_url": None if is_linkedin else url,
                "github_url": None,
                "google_scholar_url": None,
                "linkedin_url": url if is_linkedin else None,
                "source_url": FACULTY_HOMEPAGE,
                "evidence_text": f"Maneesh Agrawala homepage left-panel roster links {payload['display_name']} to this public profile URL.",
                "retrieved_at": RETRIEVED_AT,
                "verification_status": "source_roster_link",
            }
        )
    return enrichments


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def remap_profile_enrichments(enrichments: list[dict[str, Any]], people: list[Any]) -> list[dict[str, Any]]:
    people_payloads = [asdict(person) for person in people]
    people_by_id = {person["person_id"]: person for person in people_payloads}
    people_by_name = {person["display_name"].lower(): person for person in people_payloads}
    people_by_url = {
        normalize_url(url): person
        for person in people_payloads
        for url in person.get("profile_urls", [])
    }

    remapped: list[dict[str, Any]] = []
    for enrichment in enrichments:
        person = people_by_id.get(enrichment.get("person_id"))
        if person is None:
            person = people_by_name.get(str(enrichment.get("person_name", "")).lower())
        if person is None:
            person = people_by_url.get(normalize_url(enrichment.get("personal_website_url") or enrichment.get("final_url")))
        if person is None:
            raise ValueError(f"Could not map enrichment row to Maneesh source person: {enrichment.get('person_name')}")

        row = dict(enrichment)
        row["person_id"] = person["person_id"]
        row["person_name"] = person["display_name"]
        row["dataset_key"] = "maneesh_agrawala"
        row["dataset_label"] = "Maneesh Agrawala pilot"
        row["professor_name"] = FACULTY_NAME
        remapped.append(row)
    return remapped


def normalize_url(url: str | None) -> str:
    return (url or "").rstrip("/")


if __name__ == "__main__":
    main()
