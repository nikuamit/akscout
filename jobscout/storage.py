import json
from pathlib import Path

from jobscout.models import Job


def job_key(job: Job) -> str:
    return f"{job.source}:{job.company}:{job.id}"


def load_seen(path: str | Path = "data/seen.json") -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    with p.open() as f:
        data = json.load(f)
    return set(data.get("seen_ids", []))


def save_seen(seen_ids: set[str], path: str | Path = "data/seen.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump({"seen_ids": sorted(seen_ids)}, f, indent=2)
        f.write("\n")
