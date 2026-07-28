from __future__ import annotations

import argparse
from pathlib import Path

from app.crawler.crawler import CrawlConfig, TalentCrawler
from app.crawler.seeds import load_faculty_seeds
from app.enrichment.outbound import (
    EnrichmentConfig,
    build_backfill_candidates,
    build_enrichment_candidates,
    enrich_candidates,
    import_manual_profile_research,
    load_enrichment_candidates,
    load_profile_enrichments,
)
from app.extraction.relationship_normalizer import load_section_blocks, normalize_relationships
from app.extraction.section_parser import parse_cached_pages
from app.exports.jsonl import write_jsonl
from app.resolution.entity_resolver import load_relationship_records, resolve_relationship_entities


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Talent Network Collector Phase 1 CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)

    crawl = subcommands.add_parser("crawl", help="Crawl faculty/lab sites from a seed CSV")
    crawl.add_argument("--seeds", required=True, type=Path)
    crawl.add_argument("--out", required=True, type=Path)
    crawl.add_argument("--max-pages-per-seed", default=8, type=int)
    crawl.add_argument("--delay-seconds", default=1.0, type=float)
    crawl.add_argument("--user-agent", default="TalentNetworkCollector/0.1")

    parse_cache = subcommands.add_parser("parse-cache", help="Parse cached HTML into section blocks")
    parse_cache.add_argument("--cache", required=True, type=Path)
    parse_cache.add_argument("--out", required=True, type=Path)

    normalize = subcommands.add_parser("normalize-sections", help="Normalize parsed section blocks into relationship records")
    normalize.add_argument("--sections", required=True, type=Path)
    normalize.add_argument("--out", required=True, type=Path)
    normalize.add_argument("--faculty-name")
    normalize.add_argument("--faculty-institution")
    normalize.add_argument("--faculty-homepage")

    resolve = subcommands.add_parser("resolve-relationships", help="Resolve relationship records into canonical entity tables")
    resolve.add_argument("--relationships", required=True, type=Path)
    resolve.add_argument("--out-dir", required=True, type=Path)

    queue = subcommands.add_parser("build-enrichment-queue", help="Build bounded outbound enrichment candidates")
    queue.add_argument("--relationships", required=True, type=Path)
    queue.add_argument("--out", required=True, type=Path)
    queue.add_argument("--max-candidates-per-person", default=3, type=int)

    backfill_queue = subcommands.add_parser("build-backfill-queue", help="Build no-explicit-link people-research backfill candidates")
    backfill_queue.add_argument("--relationships", required=True, type=Path)
    backfill_queue.add_argument("--out", required=True, type=Path)
    backfill_queue.add_argument(
        "--profile-enrichments",
        action="append",
        default=[],
        type=Path,
        help="Existing profile enrichment JSONL file; may be supplied more than once.",
    )

    enrich = subcommands.add_parser("enrich-profiles", help="Fetch allowed outbound profile pages and emit enrichment records")
    enrich.add_argument("--candidates", required=True, type=Path)
    enrich.add_argument("--out", required=True, type=Path)
    enrich.add_argument("--max-fetches-per-seed", default=10, type=int)
    enrich.add_argument("--user-agent", default="TalentNetworkCollector/0.1 (+public evidence crawler)")

    research = subcommands.add_parser("import-profile-research", help="Import manual people-research profile enrichment records")
    research.add_argument("--research", required=True, type=Path)
    research.add_argument("--out", required=True, type=Path)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "crawl":
        seeds = load_faculty_seeds(args.seeds)
        config = CrawlConfig(
            output_dir=args.out,
            max_pages_per_seed=args.max_pages_per_seed,
            delay_seconds=args.delay_seconds,
            user_agent=args.user_agent,
        )
        TalentCrawler(config).crawl(seeds)
        return

    if args.command == "parse-cache":
        blocks = parse_cached_pages(args.cache)
        write_jsonl(args.out, blocks)
        return

    if args.command == "normalize-sections":
        blocks = load_section_blocks(args.sections)
        records = normalize_relationships(
            blocks,
            faculty_name=args.faculty_name,
            faculty_institution=args.faculty_institution,
            faculty_homepage=args.faculty_homepage,
        )
        write_jsonl(args.out, records)
        return

    if args.command == "resolve-relationships":
        records = load_relationship_records(args.relationships)
        result = resolve_relationship_entities(records)
        write_jsonl(args.out_dir / "people.jsonl", result.people)
        write_jsonl(args.out_dir / "faculty.jsonl", result.faculty)
        write_jsonl(args.out_dir / "organizations.jsonl", result.organizations)
        write_jsonl(args.out_dir / "relationships.jsonl", result.relationships)
        write_jsonl(args.out_dir / "evidence_sources.jsonl", result.evidence_sources)
        write_jsonl(args.out_dir / "resolution_decisions.jsonl", result.resolution_decisions)
        return

    if args.command == "build-enrichment-queue":
        records = load_relationship_records(args.relationships)
        candidates = build_enrichment_candidates(
            records,
            max_candidates_per_person=args.max_candidates_per_person,
        )
        write_jsonl(args.out, candidates)
        return

    if args.command == "build-backfill-queue":
        records = load_relationship_records(args.relationships)
        enriched_person_ids = {
            enrichment.person_id
            for path in args.profile_enrichments
            for enrichment in load_profile_enrichments(path)
        }
        candidates = build_backfill_candidates(records, existing_enriched_person_ids=enriched_person_ids)
        write_jsonl(args.out, candidates)
        return

    if args.command == "enrich-profiles":
        candidates = load_enrichment_candidates(args.candidates)
        records = enrich_candidates(
            candidates,
            config=EnrichmentConfig(
                max_fetches_per_seed=args.max_fetches_per_seed,
                user_agent=args.user_agent,
            ),
        )
        write_jsonl(args.out, records)
        return

    if args.command == "import-profile-research":
        records = import_manual_profile_research(args.research)
        write_jsonl(args.out, records)
        return

    raise ValueError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
