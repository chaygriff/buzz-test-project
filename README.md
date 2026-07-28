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
```

## Development

```bash
python3 -m unittest discover -s tests
```
