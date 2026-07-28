from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from app.crawler.cache import HtmlCache
from app.crawler.robots import RobotsPolicy
from app.crawler.seeds import FacultySeed
from app.extraction.page_discovery import discover_relevant_links


@dataclass(frozen=True)
class CrawlConfig:
    output_dir: Path
    max_pages_per_seed: int = 8
    delay_seconds: float = 1.0
    user_agent: str = "TalentNetworkCollector/0.1"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content_type: str | None
    html: str


class TalentCrawler:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.cache = HtmlCache(config.output_dir / "cache")
        self.log_path = config.output_dir / "crawl.log.jsonl"
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

    def crawl(self, seeds: list[FacultySeed]) -> None:
        for seed in seeds:
            self._crawl_seed(seed)

    def _crawl_seed(self, seed: FacultySeed) -> None:
        policy = RobotsPolicy.for_url(seed.faculty_homepage, self.config.user_agent)
        queue = [seed.faculty_homepage]
        seen: set[str] = set()
        seed_netloc = urlparse(seed.faculty_homepage).netloc

        while queue and len(seen) < self.config.max_pages_per_seed:
            url = queue.pop(0)
            if url in seen or urlparse(url).netloc != seed_netloc:
                continue
            seen.add(url)

            if not policy.can_fetch(url):
                self._log(seed, url, "skipped_robots", None)
                continue

            try:
                result = self._fetch(url)
            except (HTTPError, URLError, TimeoutError) as exc:
                self._log(seed, url, "fetch_error", str(exc))
                continue

            cached = self.cache.write(
                url=result.url,
                html=result.html,
                status_code=result.status_code,
                content_type=result.content_type,
            )
            self._log(seed, result.url, "cached", str(cached.html_path))

            for link in discover_relevant_links(result.html, result.url):
                absolute = urljoin(result.url, link.url)
                if absolute not in seen and urlparse(absolute).netloc == seed_netloc:
                    queue.append(absolute)

            time.sleep(self.config.delay_seconds)

    def _fetch(self, url: str) -> FetchResult:
        request = Request(url, headers={"User-Agent": self.config.user_agent})
        with urlopen(request, timeout=20) as response:
            body = response.read()
            content_type = response.headers.get("content-type")
            encoding = response.headers.get_content_charset() or "utf-8"
            html = body.decode(encoding, errors="replace")
            return FetchResult(
                url=response.geturl(),
                status_code=response.status,
                content_type=content_type,
                html=html,
            )

    def _log(self, seed: FacultySeed, url: str, status: str, detail: str | None) -> None:
        entry = {"seed": asdict(seed), "url": url, "status": status, "detail": detail}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

