"""Scores a Job against a candidate profile.

The score is built from four additive components (title, skills, location,
industry) and one subtractive component (an experience-gap penalty), each
capped by a weight from ``profile["weights"]``. Defaults are tuned so that:

* A Senior/Lead/Staff Data Engineer role in Bengaluru/remote that uses the
  candidate's stack scores 70+.
* A generic software-engineering role (no data-engineering title or stack
  overlap) scores below 40.
* A role asking for far more years of experience than the candidate has is
  penalised proportionally to the gap.
"""

from __future__ import annotations

import re
from typing import Optional

from jobscout.models import Job

DEFAULT_WEIGHTS = {
    "title": 40,
    "skills": 25,
    "location": 20,
    "industry": 15,
    "per_skill_points": 5,
    "seniority_bonus": 5,
    "experience_grace_years": 2,
    "experience_penalty_per_year": 8,
    "experience_penalty_max": 40,
}

SENIOR_TERMS = {"senior", "sr", "lead", "staff", "principal", "iii", "iv"}
JUNIOR_TERMS = {"junior", "jr", "intern", "entry level", "entry-level", "associate", "trainee"}

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:to|-)?\s*(\d{1,2})?\s*\+?\s*years", re.IGNORECASE)


def _weights(profile: dict) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    w.update(profile.get("weights") or {})
    return w


def _title_score(job: Job, profile: dict, w: dict) -> float:
    title = job.title.lower()
    target_titles = [t.lower() for t in profile.get("target_titles", [])]
    core_match = any(t in title for t in target_titles)
    if not core_match:
        return 0.0

    score = w["title"]
    has_senior_term = any(re.search(rf"\b{re.escape(t)}\b", title) for t in SENIOR_TERMS)
    has_junior_term = any(t in title for t in JUNIOR_TERMS)
    if has_junior_term:
        score *= 0.3
    elif has_senior_term:
        score += w.get("seniority_bonus", 0)
    return score


def _skill_score(job: Job, profile: dict, w: dict) -> tuple[float, list[str]]:
    haystack = f"{job.title} {job.description}".lower()
    skills = [s.lower() for s in profile.get("skills", [])]
    matched = [s for s in skills if s in haystack]
    raw = len(matched) * w["per_skill_points"]
    return min(raw, w["skills"]), matched


def _location_score(job: Job, profile: dict, w: dict) -> float:
    location = (job.location or "").lower()
    target_locations = [l.lower() for l in profile.get("locations", [])]
    if any(loc in location for loc in target_locations):
        return w["location"]
    if profile.get("remote_ok") and "remote" in location:
        return w["location"]
    return 0.0


def _industry_score(job: Job, profile: dict, w: dict) -> float:
    haystack = f"{job.company} {job.description}".lower()
    industries = [i.lower() for i in profile.get("industries", [])]
    if any(i in haystack for i in industries):
        return w["industry"]
    return 0.0


def _required_years(description: str) -> Optional[int]:
    best = None
    for m in _YEARS_RE.finditer(description):
        nums = [int(g) for g in m.groups() if g]
        if nums:
            best = max(best or 0, max(nums))
    return best


def _experience_penalty(job: Job, profile: dict, w: dict) -> float:
    required = _required_years(job.description)
    if required is None:
        return 0.0
    candidate_years = profile.get("years_experience", 0)
    gap = required - candidate_years - w["experience_grace_years"]
    if gap <= 0:
        return 0.0
    return min(gap * w["experience_penalty_per_year"], w["experience_penalty_max"])


def score_job(job: Job, profile: dict) -> dict:
    w = _weights(profile)
    title = _title_score(job, profile, w)
    skills, matched_skills = _skill_score(job, profile, w)
    location = _location_score(job, profile, w)
    industry = _industry_score(job, profile, w)
    penalty = _experience_penalty(job, profile, w)

    total = title + skills + location + industry - penalty
    total = max(0, min(100, round(total)))

    return {
        "score": total,
        "breakdown": {
            "title": round(title, 1),
            "skills": round(skills, 1),
            "location": round(location, 1),
            "industry": round(industry, 1),
            "experience_penalty": round(penalty, 1),
            "matched_skills": matched_skills,
        },
    }


def rank_jobs(jobs: list[Job], profile: dict) -> list[dict]:
    scored = []
    for job in jobs:
        result = score_job(job, profile)
        scored.append({"job": job, **result})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored
