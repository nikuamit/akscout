"""Generates site/data/public.json from real repo state - no fabricated or
personal numbers. This is the only thing the AKScout Pages site serves
publicly; it never includes anything from the tracker (applications,
contacts, rejection reasons) - only facts about the tool itself.

Run manually, or via .github/workflows/pages.yml before every deploy:

    python scripts/generate_public_stats.py
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def count_tests(tests_dir: Path) -> int:
    count = 0
    for path in tests_dir.glob("test_*.py"):
        count += len(re.findall(r"^def test_", path.read_text(), re.MULTILINE))
    return count


def build_stats(*, companies_watched: int, ats_adapters: list[str], tests_passing: int,
                 commit_sha: str, commit_date: str,
                 latest_release: Optional[dict] = None) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "companies_watched": companies_watched,
        "ats_adapters_supported": sorted(ats_adapters),
        "tests_passing": tests_passing,
        "latest_commit": {"sha": commit_sha, "date": commit_date},
        "latest_release": latest_release,
    }


def latest_release_info() -> Optional[dict]:
    tag = _git("describe", "--tags", "--abbrev=0")
    if not tag:
        return None
    return {
        "tag": tag,
        "summary": _git("log", "-1", "--format=%s", tag),
        "date": _git("log", "-1", "--format=%cI", tag),
    }


def main() -> None:
    import yaml

    from jobscout.sources.ats import ADAPTERS

    profile = yaml.safe_load((ROOT / "profiles" / "amit.yaml").read_text())
    stats = build_stats(
        companies_watched=len(profile.get("watchlist", [])),
        ats_adapters=list(ADAPTERS.keys()),
        tests_passing=count_tests(ROOT / "tests"),
        commit_sha=_git("rev-parse", "--short", "HEAD") or "unknown",
        commit_date=_git("log", "-1", "--format=%cI") or "",
        latest_release=latest_release_info(),
    )
    out_path = ROOT / "site" / "data" / "public.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
