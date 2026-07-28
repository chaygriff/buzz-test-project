from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CachedPage:
    url: str
    html_path: Path
    metadata_path: Path
    retrieved_at: str
    status_code: int
    content_type: str | None = None


class HtmlCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def key_for_url(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def paths_for_url(self, url: str) -> tuple[Path, Path]:
        key = self.key_for_url(url)
        return self.root / f"{key}.html", self.root / f"{key}.json"

    def write(
        self,
        *,
        url: str,
        html: str,
        status_code: int,
        content_type: str | None,
    ) -> CachedPage:
        html_path, metadata_path = self.paths_for_url(url)
        retrieved_at = datetime.now(UTC).isoformat()
        html_path.write_text(html, encoding="utf-8")
        cached = CachedPage(
            url=url,
            html_path=html_path,
            metadata_path=metadata_path,
            retrieved_at=retrieved_at,
            status_code=status_code,
            content_type=content_type,
        )
        metadata_path.write_text(json.dumps(asdict(cached), default=str, indent=2), encoding="utf-8")
        return cached

    def iter_metadata(self) -> list[dict]:
        pages: list[dict] = []
        for path in sorted(self.root.glob("*.json")):
            pages.append(json.loads(path.read_text(encoding="utf-8")))
        return pages

