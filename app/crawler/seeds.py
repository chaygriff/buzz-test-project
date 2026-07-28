from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FacultySeed:
    faculty_name: str
    faculty_institution: str
    faculty_homepage: str


REQUIRED_COLUMNS = {"faculty_name", "faculty_institution", "faculty_homepage"}


def load_faculty_seeds(path: Path) -> list[FacultySeed]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Seed CSV missing required columns: {', '.join(sorted(missing))}")

        seeds = []
        for row_number, row in enumerate(reader, start=2):
            seed = FacultySeed(
                faculty_name=(row.get("faculty_name") or "").strip(),
                faculty_institution=(row.get("faculty_institution") or "").strip(),
                faculty_homepage=(row.get("faculty_homepage") or "").strip(),
            )
            if not all((seed.faculty_name, seed.faculty_institution, seed.faculty_homepage)):
                raise ValueError(f"Seed CSV row {row_number} has blank required fields")
            seeds.append(seed)
        return seeds

