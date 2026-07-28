# Talent Network Collector

Evidence-backed data collection pipeline for discovering public relationship
data between AI faculty, labs, students, alumni, and researchers.

## Status

Phase 1 scaffold:

- CSV faculty seed loading
- robots.txt checks
- polite same-site crawler
- raw HTML cache with metadata
- crawl logs
- deterministic relevant-page discovery
- deterministic section parsing for review

No AI extraction is implemented in Phase 1.

## Quickstart

```bash
python3 -m app.crawler.cli crawl --seeds seeds/faculty.example.csv --out data
python3 -m app.crawler.cli parse-cache --cache data/cache --out data/sections.jsonl
python3 -m app.crawler.cli normalize-sections \
  --sections data/sections.jsonl \
  --out data/relationships.jsonl \
  --faculty-name "Example Professor" \
  --faculty-institution "Example University" \
  --faculty-homepage "https://example.edu/professor"
python3 -m app.crawler.cli build-enrichment-queue \
  --relationships data/relationships.jsonl \
  --out data/enrichment_candidates.jsonl
python3 -m app.crawler.cli enrich-profiles \
  --candidates data/enrichment_candidates.jsonl \
  --out data/profile_enrichment.jsonl \
  --max-fetches-per-seed 10
```

Outbound enrichment stores Google Scholar, LinkedIn, and GitHub profile URLs as
external identifiers by default. It only fetches supported HTML profile pages
when robots.txt allows a depth-0 request.

## Development

```bash
python3 -m unittest discover -s tests
```
