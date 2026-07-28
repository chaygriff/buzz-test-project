from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.crawler.robots import RobotsPolicy
from app.models.enrichment import BackfillCandidateRecord, EnrichmentCandidateRecord, ProfileEnrichmentRecord
from app.models.records import EvidenceLink, RelationshipRecord
from app.resolution.entity_resolver import deterministic_id, load_relationship_records, resolve_relationship_entities


CRAWLABLE_SOURCE_TYPES = {"personal_website", "github_pages", "university_profile", "lab_or_group"}
IDENTIFIER_ONLY_SOURCE_TYPES = {"google_scholar", "linkedin", "github_profile", "social"}
SKIPPED_SOURCE_TYPES = {"pdf", "binary", "search", "unknown"}


@dataclass(frozen=True)
class EnrichmentConfig:
    max_candidates_per_person: int = 3
    max_fetches_per_seed: int = 10
    user_agent: str = "TalentNetworkCollector/0.1 (+public evidence crawler)"
    timeout_seconds: int = 20


@dataclass(frozen=True)
class OutboundFetchResult:
    final_url: str
    status_code: int
    content_type: str | None
    html: str


class SimpleProfileParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title: str | None = None
        self.meta_description: str | None = None
        self._capture_title = False
        self._title_parts: list[str] = []
        self._capture_text_tags: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = {name.lower(): value for name, value in attrs}
        if tag == "title":
            self._capture_title = True
            self._title_parts = []
        elif tag == "meta":
            name = (attrs_by_name.get("name") or attrs_by_name.get("property") or "").lower()
            if name in {"description", "og:description"} and attrs_by_name.get("content"):
                self.meta_description = normalize_text(attrs_by_name["content"] or "")
        elif tag in {"p", "li", "h1", "h2", "h3"}:
            self._capture_text_tags.append(tag)

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        if self._capture_text_tags:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._capture_title:
            self.title = normalize_text(" ".join(self._title_parts))
            self._capture_title = False
            self._title_parts = []
        elif self._capture_text_tags and self._capture_text_tags[-1] == tag:
            self._capture_text_tags.pop()

    @property
    def visible_text(self) -> str:
        return normalize_text(" ".join(self._text_parts))


def build_enrichment_candidates(
    records: list[RelationshipRecord],
    *,
    max_candidates_per_person: int = 3,
) -> list[EnrichmentCandidateRecord]:
    resolved = resolve_relationship_entities(records)
    canonical_by_evidence = {
        evidence.evidence_text: relationship
        for evidence, relationship in zip(resolved.evidence_sources, resolved.relationships)
    }
    seen_by_person: dict[str, set[str]] = {}
    candidates: list[EnrichmentCandidateRecord] = []

    for record in records:
        if not record.person_name:
            continue
        relationship = canonical_by_evidence.get(record.evidence_text)
        if relationship is None:
            continue
        person_seen = seen_by_person.setdefault(relationship.person_id, set())
        for link in candidate_links_for_record(record):
            if len(person_seen) >= max_candidates_per_person or link.url in person_seen:
                continue
            person_seen.add(link.url)
            candidates.append(
                EnrichmentCandidateRecord(
                    candidate_id=deterministic_id("candidate", relationship.person_id, link.url, record.evidence_text),
                    person_id=relationship.person_id,
                    person_name=record.person_name,
                    relationship_id=relationship.relationship_id,
                    url=link.url,
                    source_type=classify_url(link.url),
                    source_url=record.source_url,
                    source_section=record.page_section,
                    evidence_text=record.evidence_text,
                )
            )
    return candidates


def build_backfill_candidates(
    records: list[RelationshipRecord],
    *,
    existing_enriched_person_ids: set[str] | None = None,
) -> list[BackfillCandidateRecord]:
    enriched_person_ids = existing_enriched_person_ids or set()
    resolved = resolve_relationship_entities(records)
    canonical_by_evidence = {evidence.evidence_text: relationship for evidence, relationship in zip(records, resolved.relationships)}
    best_by_person: dict[str, BackfillCandidateRecord] = {}

    for record in records:
        if not record.person_name:
            continue
        relationship = canonical_by_evidence.get(record.evidence_text)
        if relationship is None or relationship.person_id in enriched_person_ids:
            continue
        if candidate_links_for_record(record):
            continue

        candidate = backfill_candidate_for_record(record, relationship.person_id, relationship.relationship_id)
        previous = best_by_person.get(candidate.person_id)
        if previous is None or candidate.priority_score > previous.priority_score:
            best_by_person[candidate.person_id] = candidate

    return sorted(
        best_by_person.values(),
        key=lambda candidate: (-candidate.priority_score, candidate.person_name.lower()),
    )


def backfill_candidate_for_record(
    record: RelationshipRecord,
    person_id: str,
    relationship_id: str,
) -> BackfillCandidateRecord:
    score, reasons = score_backfill_candidate(record)
    search_terms = backfill_search_terms(record)
    return BackfillCandidateRecord(
        backfill_candidate_id=deterministic_id("backfill_candidate", person_id, relationship_id, record.evidence_text),
        person_id=person_id,
        person_name=record.person_name or "",
        relationship_id=relationship_id,
        relationship_type=record.normalized_relationship,
        status=record.status,
        degree=record.degree,
        start_year=record.start_year,
        end_year=record.end_year,
        graduation_year=record.graduation_year,
        source_affiliation=record.faculty_institution,
        current_destination=record.current_destination,
        evidence_text=record.evidence_text,
        source_url=record.source_url,
        source_section=record.page_section,
        priority_bucket=priority_bucket(score),
        priority_score=score,
        priority_reasons=reasons,
        search_query=" ".join(search_terms),
        search_terms=search_terms,
        research_guidance=backfill_research_guidance(record),
        verification_status="needs_people_research",
    )


def score_backfill_candidate(record: RelationshipRecord) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    relationship = record.normalized_relationship or ""
    status = record.status or ""

    if status == "current":
        score += 30
        reasons.append("current_relationship")
    if relationship in {"phd_student", "postdoc"}:
        score += 25
        reasons.append(f"high_value_{relationship}")
    elif relationship in {"masters_student", "bachelors_student"}:
        score += 12
        reasons.append(f"degree_{relationship}")
    elif relationship == "visitor":
        score += 4
        reasons.append("visitor_requires_strong_attribution")
    elif relationship == "high_school_student":
        score -= 15
        reasons.append("lower_priority_high_school")

    if record.current_destination:
        score += 20
        reasons.append("has_seed_current_destination")
    if record.fellowship:
        score += 5
        reasons.append("has_seed_fellowship")
    if record.co_advisor:
        score += 5
        reasons.append("has_seed_coadvisor")
    if record.start_year or record.end_year or record.graduation_year:
        score += 5
        reasons.append("has_seed_year_context")

    if not reasons:
        reasons.append("missing_explicit_profile_link")
    return score, reasons


def priority_bucket(score: int) -> str:
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def backfill_search_terms(record: RelationshipRecord) -> list[str]:
    terms = [
        record.person_name or "",
        record.faculty_name or "",
        record.faculty_institution or "",
        "Computational Imaging Lab",
    ]
    if record.normalized_relationship:
        terms.append(record.normalized_relationship.replace("_", " "))
    if record.start_year or record.end_year:
        years = "-".join(str(year) for year in [record.start_year, record.end_year] if year)
        if years:
            terms.append(years)
    if record.graduation_year:
        terms.append(str(record.graduation_year))
    if record.current_destination:
        terms.append(record.current_destination)
    if record.fellowship:
        terms.append(record.fellowship)
    if record.co_advisor:
        terms.append(record.co_advisor)
    return [term for term in dedupe_preserving_order(normalize_text(term) for term in terms) if term]


def backfill_research_guidance(record: RelationshipRecord) -> list[str]:
    guidance = [
        "Run people-research with the full context-rich search query, not name-only search.",
        "Require public evidence tying the person to Stanford, Gordon Wetzstein, or the Computational Imaging Lab before marking verified.",
        "Leave URLs null or mark needs_review when attribution is weak.",
    ]
    if record.normalized_relationship == "visitor":
        guidance.append("For visitors, also require evidence tying the profile to the seed source affiliation or destination.")
    return guidance


def dedupe_preserving_order(values: list[str] | object) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def candidate_links_for_record(record: RelationshipRecord) -> list[EvidenceLink]:
    links: list[EvidenceLink] = []
    if record.person_profile_url:
        links.append(EvidenceLink(text=record.person_name or "", url=record.person_profile_url))
    links.extend(record.source_links)

    deduped: list[EvidenceLink] = []
    seen: set[str] = set()
    person_key = normalize_text((record.person_name or "").lower())
    for link in links:
        if link.url in seen:
            continue
        link_key = normalize_text(link.text.lower())
        if person_key and link_key and (person_key == link_key or person_key in link_key or link_key in person_key):
            seen.add(link.url)
            deduped.append(link)
    return deduped


def classify_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if host.endswith("scholar.google.com"):
        return "google_scholar"
    if "linkedin.com" in host:
        return "linkedin"
    if host == "github.com":
        return "github_profile"
    if host.endswith("github.io"):
        return "github_pages"
    if any(domain in host for domain in ["x.com", "twitter.com", "facebook.com", "instagram.com"]):
        return "social"
    if query and any(term in path for term in ["/search", "/query"]):
        return "search"
    if is_university_host(host):
        return "university_profile"
    if any(term in host for term in ["lab", "group", "psai", "computationalimaging"]):
        return "lab_or_group"
    if parsed.scheme in {"http", "https"} and host:
        return "personal_website"
    return "unknown"


def is_university_host(host: str) -> bool:
    return host.endswith(".edu") or ".edu." in host or any(
        domain in host
        for domain in [
            "stanford.edu",
            "mit.edu",
            "berkeley.edu",
            "cmu.edu",
            "princeton.edu",
            "toronto.edu",
        ]
    )


def enrich_candidates(
    candidates: list[EnrichmentCandidateRecord],
    *,
    config: EnrichmentConfig | None = None,
) -> list[ProfileEnrichmentRecord]:
    config = config or EnrichmentConfig()
    records: list[ProfileEnrichmentRecord] = []
    fetches = 0
    for candidate in candidates:
        if candidate.source_type in IDENTIFIER_ONLY_SOURCE_TYPES:
            records.append(identifier_only_record(candidate))
            continue
        if candidate.source_type in SKIPPED_SOURCE_TYPES or candidate.source_type not in CRAWLABLE_SOURCE_TYPES:
            records.append(skipped_record(candidate, "unsupported_source_type"))
            continue
        if fetches >= config.max_fetches_per_seed:
            records.append(skipped_record(candidate, "max_fetches_per_seed_reached"))
            continue
        policy = RobotsPolicy.for_url(candidate.url, config.user_agent)
        if not policy.can_fetch(candidate.url):
            records.append(skipped_record(candidate, "robots_disallowed"))
            continue
        try:
            result = fetch_candidate(candidate.url, user_agent=config.user_agent, timeout=config.timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            records.append(skipped_record(candidate, f"fetch_error: {exc}"))
            continue
        fetches += 1
        records.append(enriched_record(candidate, result))
    return records


def fetch_candidate(url: str, *, user_agent: str, timeout: int) -> OutboundFetchResult:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type")
        body = response.read()
        if content_type and "html" not in content_type.lower():
            raise ValueError(f"unsupported content type: {content_type}")
        encoding = response.headers.get_content_charset() or "utf-8"
        return OutboundFetchResult(
            final_url=response.geturl(),
            status_code=response.status,
            content_type=content_type,
            html=body.decode(encoding, errors="replace"),
        )


def identifier_only_record(candidate: EnrichmentCandidateRecord) -> ProfileEnrichmentRecord:
    return base_enrichment_record(
        candidate,
        fetch_status="identifier_only",
        skip_reason="stored_as_external_identifier",
        final_url=candidate.url,
        verification_status="linked",
        **external_identifier_fields(candidate),
    )


def skipped_record(candidate: EnrichmentCandidateRecord, reason: str) -> ProfileEnrichmentRecord:
    return base_enrichment_record(
        candidate,
        fetch_status="skipped",
        skip_reason=reason,
        final_url=None,
        verification_status="skipped",
        **external_identifier_fields(candidate),
    )


def enriched_record(candidate: EnrichmentCandidateRecord, result: OutboundFetchResult) -> ProfileEnrichmentRecord:
    parser = SimpleProfileParser()
    parser.feed(result.html)
    title = parser.title
    short_bio = choose_short_biography(parser, candidate.person_name)
    return base_enrichment_record(
        candidate,
        fetch_status="fetched",
        skip_reason=None,
        final_url=result.final_url,
        status_code=result.status_code,
        content_type=result.content_type,
        profile_title=title,
        homepage_claimed_name=extract_claimed_name(title, candidate.person_name),
        short_biography=short_bio,
        verification_status="parsed",
        **external_identifier_fields(candidate),
    )


def choose_short_biography(parser: SimpleProfileParser, person_name: str) -> str | None:
    if parser.meta_description and len(parser.meta_description) >= 30:
        return truncate(parser.meta_description, 500)
    text = parser.visible_text
    person_key = normalize_text(person_name.lower())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        sentence_text = normalize_text(html.unescape(sentence))
        if person_key in sentence_text.lower() and len(sentence_text) >= 40:
            return truncate(sentence_text, 500)
    return None


def extract_claimed_name(title: str | None, person_name: str) -> str | None:
    if not title:
        return None
    if normalize_text(person_name.lower()) in normalize_text(title.lower()):
        return person_name
    return None


def external_identifier_fields(candidate: EnrichmentCandidateRecord) -> dict[str, str | None]:
    return {
        "personal_website_url": candidate.url if candidate.source_type in {"personal_website", "github_pages", "university_profile", "lab_or_group"} else None,
        "github_url": candidate.url if candidate.source_type in {"github_profile", "github_pages"} else None,
        "google_scholar_url": candidate.url if candidate.source_type == "google_scholar" else None,
        "linkedin_url": candidate.url if candidate.source_type == "linkedin" else None,
    }


def base_enrichment_record(
    candidate: EnrichmentCandidateRecord,
    *,
    fetch_status: str,
    skip_reason: str | None,
    final_url: str | None,
    verification_status: str,
    status_code: int | None = None,
    content_type: str | None = None,
    profile_title: str | None = None,
    homepage_claimed_name: str | None = None,
    short_biography: str | None = None,
    personal_website_url: str | None = None,
    github_url: str | None = None,
    google_scholar_url: str | None = None,
    linkedin_url: str | None = None,
) -> ProfileEnrichmentRecord:
    return ProfileEnrichmentRecord(
        enrichment_id=deterministic_id("enrichment", candidate.candidate_id, final_url or "", fetch_status, skip_reason or ""),
        candidate_id=candidate.candidate_id,
        person_id=candidate.person_id,
        person_name=candidate.person_name,
        candidate_url=candidate.url,
        final_url=final_url,
        source_type=candidate.source_type,
        fetch_status=fetch_status,
        skip_reason=skip_reason,
        status_code=status_code,
        content_type=content_type,
        profile_title=profile_title,
        homepage_claimed_name=homepage_claimed_name,
        short_biography=short_biography,
        personal_website_url=personal_website_url,
        github_url=github_url,
        google_scholar_url=google_scholar_url,
        linkedin_url=linkedin_url,
        source_url=candidate.source_url,
        evidence_text=candidate.evidence_text,
        retrieved_at=datetime.now(UTC).isoformat(),
        verification_status=verification_status,
    )


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def truncate(value: str, max_length: int) -> str:
    value = normalize_text(value)
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def load_enrichment_candidates(path: Path) -> list[EnrichmentCandidateRecord]:
    candidates: list[EnrichmentCandidateRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                candidates.append(EnrichmentCandidateRecord(**json.loads(line)))
    return candidates


def load_profile_enrichments(path: Path) -> list[ProfileEnrichmentRecord]:
    records: list[ProfileEnrichmentRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(ProfileEnrichmentRecord(**json.loads(line)))
    return records


def import_manual_profile_research(path: Path) -> list[ProfileEnrichmentRecord]:
    payload = json.loads(extract_json_payload(path.read_text(encoding="utf-8")))
    records: list[ProfileEnrichmentRecord] = []
    for item in payload:
        person_id = item["person_id"]
        source_url = item["source_url"]
        candidate = EnrichmentCandidateRecord(
            candidate_id=deterministic_id("manual_candidate", person_id, source_url, item["evidence_text"]),
            person_id=person_id,
            person_name=item["person_name"],
            relationship_id="manual_research",
            url=source_url,
            source_type="people_research",
            source_url=source_url,
            source_section=None,
            evidence_text=item["evidence_text"],
        )
        records.append(
            base_enrichment_record(
                candidate,
                fetch_status="manual_research",
                skip_reason=None,
                final_url=source_url,
                verification_status=item.get("verification_status") or "manual_research",
                profile_title=None,
                homepage_claimed_name=item["person_name"],
                short_biography=item.get("short_biography"),
                personal_website_url=item.get("personal_website_url"),
                github_url=item.get("github_url"),
                google_scholar_url=item.get("google_scholar_url"),
                linkedin_url=item.get("linkedin_url"),
            )
        )
    return records


def extract_json_payload(text: str) -> str:
    fence_match = re.search(r"```json\s*(?P<payload>.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group("payload")
    return text
