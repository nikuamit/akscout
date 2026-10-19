"""Drafts a tailored recruiter outreach email for a job posting, using Claude."""

from __future__ import annotations

import os

import requests
from bs4 import BeautifulSoup

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised via the [ai] extra
    anthropic = None

DEFAULT_MODEL = "claude-sonnet-5-5"


class OutreachError(RuntimeError):
    pass


def fetch_job_description(job_url: str, *, session: requests.Session | None = None) -> str:
    sess = session or requests.Session()
    sess.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 jobscout/0.1",
    )
    try:
        resp = sess.get(job_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OutreachError(f"Could not fetch {job_url}: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    if not text:
        raise OutreachError(f"Could not extract any text from {job_url}")
    return text[:8000]


def build_prompt(description: str, profile: dict) -> str:
    name = profile.get("name", "the candidate")
    title = profile.get("title", "")
    years = profile.get("years_experience", "")
    skills = ", ".join(profile.get("skills", [])[:12])
    return (
        f"You are writing on behalf of {name}, a {title} with {years}+ years "
        f"of experience. Core stack: {skills}.\n\n"
        "Below is a job description. Write a short outreach email to the "
        "recruiter or hiring manager expressing genuine interest in this "
        "specific role.\n\n"
        "Hard requirements:\n"
        "- Exactly one paragraph. No bullet points, no headers, no lists.\n"
        "- 120-160 words.\n"
        "- Mention 2-3 concrete, specific things from the job description "
        "(stack, domain, or responsibility) to show it isn't generic.\n"
        "- Confident, warm, concise tone - not boastful.\n"
        "- End with a brief call to action.\n"
        f"- Sign off with just {name.split()[0] if name else 'the candidate'}.\n\n"
        f"JOB DESCRIPTION:\n{description}"
    )


def draft_email(description: str, profile: dict, *, api_key: str, model: str | None = None) -> str:
    if anthropic is None:
        raise OutreachError(
            "The 'anthropic' package is required for `jobscout outreach`. "
            "Install it with: pip install 'jobscout[ai]'"
        )

    model = model or os.environ.get("JOBSCOUT_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(description, profile)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # anthropic's own error hierarchy
        raise OutreachError(f"Anthropic API call failed: {exc}") from exc

    text = "".join(
        getattr(block, "text", "") for block in response.content
    ).strip()
    if not text:
        raise OutreachError("Anthropic API returned no text content")
    return text
