from __future__ import annotations

import argparse
from pathlib import Path

from app.crawler.crawler import CrawlConfig, TalentCrawler
from app.crawler.seeds import load_faculty_seeds
from app.extraction.section_parser import parse_cached_pages
from app.exports.jsonl import write_jsonl


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

    raise ValueError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()

