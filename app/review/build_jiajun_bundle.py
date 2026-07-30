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


FACULTY_NAME = "Jiajun Wu"
FACULTY_INSTITUTION = "Stanford University"
FACULTY_HOMEPAGE = "https://jiajunwu.com/"
SOURCE_SECTION_PREFIX = "Group"
RETRIEVED_AT = "2026-07-29T01:40:00+00:00"
OUTBOUND_PROFILE_ENRICHMENTS_PATH = Path("app/review/ui/source_bundles/jiajun_wu_profile_enrichments.jsonl")


ROSTER: list[dict[str, Any]] = [
    {"name": "Raven Huang", "url": "https://qingh097.github.io/", "section": "Postdocs", "type": "postdoc", "status": "current", "co_advisor": "Fei-Fei Li"},
    {"name": "R. Kenny Jones", "url": "https://rkjones4.github.io/", "section": "Postdocs", "type": "postdoc", "status": "current", "co_advisor": "Maneesh Agrawala"},
    {"name": "Ruohan Zhang", "url": "https://ai.stanford.edu/~zharu/", "section": "Postdocs", "type": "postdoc", "status": "current", "co_advisor": "Fei-Fei Li and Silvio Savarese"},
    {"name": "Ziyu Chen", "url": "https://ziyc.github.io/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Cristobal Eyzaguirre", "url": "https://ceyzaguirre4.github.io/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD", "co_advisor": "Juan Carlos Niebles"},
    {"name": "Yue Gao", "url": "https://yuegao.me/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD", "co_advisor": "Juan Carlos Niebles"},
    {"name": "Chen Geng", "url": "https://chen-geng.com/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Joy Hsu", "url": "https://web.stanford.edu/~joycjhsu/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Zizhang Li", "url": "https://kyleleey.github.io/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Kyle Sargent", "url": "https://kylesargent.github.io/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD", "co_advisor": "Fei-Fei Li"},
    {"name": "Jeff Tan", "url": "https://jefftan969.github.io/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Stephen Tian", "url": "https://s-tian.github.io/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Koven Yu", "url": "https://kovenyu.com/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Yanjie Ze", "url": "https://yanjieze.com/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD", "co_advisor": "Karen Liu"},
    {"name": "Yunzhi Zhang", "url": "https://ai.stanford.edu/~yunzhi/", "section": "PhD Students", "type": "phd_student", "status": "current", "degree": "PhD"},
    {"name": "Hadi Alzayer", "url": "https://hadizayer.github.io/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "Jia-Bin Huang"},
    {"name": "Haonan Chen", "url": "https://haonan16.github.io/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "Yilun Du"},
    {"name": "Arushi Gupta", "url": "https://arushig100.github.io/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "James Zou"},
    {"name": "Zhanpeng He", "url": "https://zhanpenghe.github.io/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "Amazon"},
    {"name": "Emily Jin", "url": "https://emilyzjin.github.io/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "Nick Haber"},
    {"name": "Klemen Kotar", "url": "https://klemenkotar.github.io/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "Dan Yamins"},
    {"name": "Maggie Wang", "url": "https://maggiewang.org/", "section": "Affiliates", "type": "affiliate", "status": "current", "co_advisor": "Mac Schwager"},
    {"name": "Jiaman Li", "url": "https://lijiaman.github.io/", "section": "Alumni", "type": "phd_student", "status": "alumni", "degree": "PhD", "graduation_year": 2025, "co_advisor": "Karen Liu", "destination": "Applied Scientist, Amazon FAR"},
    {"name": "Fan-Yun Sun", "url": "https://sunfanyun.com/", "section": "Alumni", "type": "phd_student", "status": "alumni", "degree": "PhD", "graduation_year": 2025, "co_advisor": "Nick Haber", "destination": "Co-Founder & CEO, Moonlake AI"},
    {"name": "Samuel Clarke", "url": "https://samuelpclarke.com/", "section": "Alumni", "type": "phd_student", "status": "alumni", "degree": "PhD", "graduation_year": 2025, "destination": "Senior ML Engineer, Tesla"},
    {"name": "Kyle Hsu", "url": "https://kylehsu.org/", "section": "Alumni", "type": "phd_student", "status": "alumni", "degree": "PhD", "graduation_year": 2025, "co_advisor": "Chelsea Finn", "destination": "Senior ML Engineer, Tesla"},
    {"name": "Michelle Guo", "url": "https://shellguo.com/", "section": "Alumni", "type": "phd_student", "status": "alumni", "degree": "PhD", "graduation_year": 2025, "co_advisor": "Karen Liu", "destination": "Research Scientist, Meta Superintelligence Labs"},
    {"name": "Weiyu Liu", "url": "https://weiyuliu.com/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2025, "destination": "Member of Technical Staff, Rhoda AI"},
    {"name": "Mengdi Xu", "url": "https://mxu34.github.io/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2025, "co_advisor": "Fei-Fei Li", "destination": "Assistant Professor, Tsinghua University"},
    {"name": "Stefan Stojanov", "url": "https://sstojanov.github.io/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2025, "co_advisor": "Dan Yamins", "destination": "Research Scientist, Google"},
    {"name": "Eric Chan", "url": "https://ericryanchan.github.io/", "section": "Alumni", "type": "alumni", "status": "alumni", "graduation_year": 2024, "co_advisor": "Gordon Wetzstein", "destination": "Co-Founder & Chief Scientist, Rhoda AI"},
    {"name": "Elliott Wu", "url": "https://elliottwu.com/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2024, "destination": "Assistant Professor, University of Cambridge"},
    {"name": "Manling Li", "url": "https://limanling.github.io/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2024, "destination": "Assistant Professor, Northwestern University"},
    {"name": "Ryosuke Sawata", "url": "https://ai.sony/people/Ryosuke-Sawata/", "section": "Alumni", "type": "visitor", "status": "alumni", "degree": "PhD", "graduation_year": 2023, "co_advisor": "Laurent Itti", "destination": "Research Scientist, Sony AI"},
    {"name": "Yunhao Ge", "url": "https://gyhandy.github.io/", "section": "Alumni", "type": "visitor", "status": "alumni", "degree": "PhD", "graduation_year": 2023, "co_advisor": "Laurent Itti", "destination": "Research Scientist, Nvidia"},
    {"name": "Yunzhu Li", "url": "https://yunzhuli.github.io/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2023, "co_advisor": "Fei-Fei Li", "destination": "Assistant Professor, Columbia University"},
    {"name": "Ruohan Gao", "url": "https://ruohangao.github.io/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2023, "co_advisor": "Fei-Fei Li and Silvio Savarese", "destination": "Assistant Professor, University of Maryland, College Park"},
    {"name": "Sumith Kulal", "url": "https://cs.stanford.edu/~sumith/", "section": "Alumni", "type": "phd_student", "status": "alumni", "degree": "PhD", "graduation_year": 2023, "co_advisor": "Alex Aiken", "destination": "Co-Founder, Black Forest Labs"},
    {"name": "Michael Lingelbach", "url": "https://mlingelbach.com/", "section": "Alumni", "type": "alumni", "status": "alumni", "graduation_year": 2023, "co_advisor": "Fei-Fei Li", "destination": "Founder & CEO, Hedra"},
    {"name": "Huazhe Xu", "url": "https://hxu.rocks/", "section": "Alumni", "type": "postdoc", "status": "alumni", "graduation_year": 2022, "destination": "Assistant Professor, Tsinghua University"},
]


def main() -> None:
    bundle_path = Path("app/review/ui/source_bundles/jiajun_wu_review_bundle.json")

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
        write_jsonl(out_dir / "backfill_candidates.jsonl", [])
        (out_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "dataset_label": "Jiajun Wu pilot",
                    "professor_name": FACULTY_NAME,
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
    year = item.get("graduation_year")
    relationship_text = item["section"]
    if year:
        relationship_text += f", {item.get('degree') or item['type'].replace('_', ' ')} {year}"
    if item.get("co_advisor"):
        relationship_text += f", with {item['co_advisor']}"
    if item.get("destination"):
        relationship_text += f", {item['destination']}"
    evidence_text = f"{item['name']}, Stanford University, {relationship_text}"

    return RelationshipRecord(
        faculty_name=FACULTY_NAME,
        faculty_institution=FACULTY_INSTITUTION,
        faculty_homepage=FACULTY_HOMEPAGE,
        person_name=item["name"],
        person_profile_url=item["url"],
        raw_relationship=item["section"],
        normalized_relationship=item["type"],
        status=item["status"],
        degree=item.get("degree"),
        start_year=None,
        end_year=year,
        graduation_year=year if item["status"] == "alumni" else None,
        co_advisor=item.get("co_advisor"),
        fellowship=None,
        current_destination=item.get("destination"),
        source_url=FACULTY_HOMEPAGE,
        page_section=f"{SOURCE_SECTION_PREFIX} > {item['section']}",
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
                "personal_website_url": url,
                "github_url": None,
                "google_scholar_url": None,
                "linkedin_url": None,
                "source_url": FACULTY_HOMEPAGE,
                "evidence_text": f"Jiajun Wu homepage group roster links {payload['display_name']} to this profile URL.",
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
            raise ValueError(f"Could not map enrichment row to Jiajun source person: {enrichment.get('person_name')}")

        row = dict(enrichment)
        row["person_id"] = person["person_id"]
        row["person_name"] = person["display_name"]
        row["dataset_key"] = "jiajun_wu"
        row["dataset_label"] = "Jiajun Wu pilot"
        row["professor_name"] = FACULTY_NAME
        remapped.append(row)
    return remapped


def normalize_url(url: str | None) -> str:
    return (url or "").rstrip("/")


if __name__ == "__main__":
    main()
