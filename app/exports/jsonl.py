from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Iterable


def write_jsonl(path: Path, records: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            payload = asdict(record) if is_dataclass(record) else record
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

