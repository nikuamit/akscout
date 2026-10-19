"""Best-effort extraction of a draft profile from a resume PDF.

This is intentionally heuristic: it pulls an email, a rough years-of-experience
number, and any known skill/title keywords it recognizes out of the resume
text, so `jobscout init` can produce a starting point for the user to edit
or merge into their hand-maintained profile.
"""

from __future__ import annotations

import re
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*years", re.IGNORECASE)

KNOWN_SKILLS = [
    "python", "pyspark", "spark", "sql", "scala", "java",
    "aws glue", "aws dms", "redshift", "athena", "kinesis", "lake formation",
    "s3", "ec2", "lambda", "emr", "airflow", "apache iceberg", "iceberg",
    "delta lake", "cube cloud", "cube.js", "dbt", "snowflake", "bigquery",
    "kafka", "docker", "kubernetes", "terraform", "postgres", "mysql",
    "row-level security", "multi-tenant",
]

KNOWN_TITLES = [
    "data engineer", "senior data engineer", "lead data engineer",
    "staff data engineer", "principal data engineer", "data architect",
    "analytics engineer", "software engineer",
]


def _extract_text(pdf_path: str | Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_profile(pdf_path: str | Path) -> dict:
    text = _extract_text(pdf_path)
    lower = text.lower()

    email_match = EMAIL_RE.search(text)
    years_match = YEARS_RE.search(text)

    skills = [s for s in KNOWN_SKILLS if s in lower]
    titles = [t for t in KNOWN_TITLES if t in lower]

    profile: dict = {
        "name": "",
        "title": titles[0].title() if titles else "",
        "years_experience": int(years_match.group(1)) if years_match else None,
        "email": email_match.group(0) if email_match else None,
        "skills": skills,
        "target_titles": titles,
        "watchlist": [],
    }
    return profile
