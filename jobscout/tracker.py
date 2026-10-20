"""A local SQLite tracker for applications you've actually sent.

Nothing here talks to the network. It's a personal pipeline log: what stage
each application is at, who you've spoken to (if you've recorded it
yourself - this never scrapes contacts), and a couple of small heuristics
(stale-application "ghosting" detection, a rejection-reason classifier)
that work off what you type in, not AI inference.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from jobscout.models import Job

STAGES = (
    "shortlisted", "applied", "outreach_sent", "responded",
    "interview", "offer", "rejected", "ghosted", "withdrawn",
)

DEFAULT_DB_PATH = "data/applications.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT UNIQUE NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'shortlisted',
    score INTEGER,
    not_really_hiring INTEGER NOT NULL DEFAULT 0,
    ta_name TEXT,
    ta_email TEXT,
    ta_linkedin TEXT,
    rejection_reason_raw TEXT,
    rejection_reason TEXT,
    notes TEXT,
    applied_at TEXT,
    last_contact_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Common markers of a req that's posted indefinitely rather than for an
# actual open role right now.
_EVERGREEN_PHRASES = (
    "general application", "talent community", "talent pool",
    "future opportunities", "future opportunity", "evergreen",
    "express interest", "stay connected",
)
_EVERGREEN_AGE_DAYS = 120

_REJECTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("experience_mismatch", ("more experience", "not enough experience", "senior candidates",
                              "overqualified", "underqualified", "years of experience")),
    ("role_closed_or_filled", ("position has been filled", "role has been closed",
                                "no longer accepting", "position was filled", "closed this req")),
    ("skills_mismatch", ("skill set", "skillset", "technical requirements", "different direction",
                          "not a match for the required")),
    ("compensation", ("salary expectations", "compensation expectations", "budget for this role")),
    ("location_or_remote", ("location requirements", "not able to support remote",
                             "visa sponsorship", "work authorization", "relocat")),
    ("timing_or_priorities", ("paused this search", "put this role on hold", "changed priorities",
                               "hiring freeze", "no longer hiring for this")),
    ("no_feedback", ("unfortunately", "decided to move forward with other candidates",
                      "pursue other candidates", "will not be moving forward")),
]


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_not_really_hiring(job: Job) -> bool:
    """Best-effort flag for evergreen/perpetual postings, not a real open
    req right now. Based only on text already in the posting - no
    network calls, no guessing beyond what the listing itself says.
    """
    haystack = f"{job.title} {job.description}".lower()
    if any(phrase in haystack for phrase in _EVERGREEN_PHRASES):
        return True
    if job.posted_at:
        try:
            posted = datetime.fromisoformat(job.posted_at.replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - posted
            if age > timedelta(days=_EVERGREEN_AGE_DAYS):
                return True
        except ValueError:
            pass  # unparseable date format - don't flag on it
    return False


def classify_rejection_reason(raw_text: str) -> str:
    """Keyword-based classification of a rejection email/note - not ML,
    just the same pragmatic heuristic style as the rest of this project.
    Returns one of the categories in _REJECTION_RULES, or "other".
    """
    lower = (raw_text or "").lower()
    for category, keywords in _REJECTION_RULES:
        if any(kw in lower for kw in keywords):
            return category
    return "other"


def add_application(conn: sqlite3.Connection, job: Job, *, score: Optional[int] = None,
                     stage: str = "shortlisted") -> int:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage!r}")
    job_key = f"{job.source}:{job.company}:{job.id}"
    now = _now()
    not_hiring = int(is_not_really_hiring(job))
    conn.execute(
        """
        INSERT INTO applications
            (job_key, company, title, url, source, stage, score,
             not_really_hiring, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_key) DO NOTHING
        """,
        (job_key, job.company, job.title, job.url, job.source, stage, score,
         not_hiring, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM applications WHERE job_key = ?", (job_key,)).fetchone()
    return row["id"]


def update_stage(conn: sqlite3.Connection, app_id: int, stage: str, *,
                  note: Optional[str] = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage!r}")
    now = _now()
    fields = {"stage": stage, "updated_at": now}
    if stage == "applied":
        fields["applied_at"] = now
    if stage in ("outreach_sent", "responded", "interview"):
        fields["last_contact_at"] = now
    if note:
        fields["notes"] = note
    columns = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE applications SET {columns} WHERE id = ?",
                 (*fields.values(), app_id))
    conn.commit()


def set_contact(conn: sqlite3.Connection, app_id: int, *, name: Optional[str] = None,
                 email: Optional[str] = None, linkedin: Optional[str] = None) -> None:
    conn.execute(
        """
        UPDATE applications
        SET ta_name = COALESCE(?, ta_name),
            ta_email = COALESCE(?, ta_email),
            ta_linkedin = COALESCE(?, ta_linkedin),
            updated_at = ?
        WHERE id = ?
        """,
        (name, email, linkedin, _now(), app_id),
    )
    conn.commit()


def set_rejection(conn: sqlite3.Connection, app_id: int, raw_reason: str) -> str:
    category = classify_rejection_reason(raw_reason)
    conn.execute(
        """
        UPDATE applications
        SET stage = 'rejected', rejection_reason_raw = ?, rejection_reason = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (raw_reason, category, _now(), app_id),
    )
    conn.commit()
    return category


def list_applications(conn: sqlite3.Connection, *, stage: Optional[str] = None) -> list[dict]:
    if stage:
        rows = conn.execute("SELECT * FROM applications WHERE stage = ? ORDER BY updated_at DESC",
                             (stage,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def mark_stale_as_ghosted(conn: sqlite3.Connection, *, stale_days: int = 21) -> list[dict]:
    """Flips any application stuck in applied/outreach_sent/responded with
    no contact for `stale_days` to 'ghosted'. Returns the rows it changed.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
    candidates = conn.execute(
        """
        SELECT * FROM applications
        WHERE stage IN ('applied', 'outreach_sent', 'responded')
          AND COALESCE(last_contact_at, applied_at, created_at) < ?
        """,
        (cutoff,),
    ).fetchall()
    changed = [dict(r) for r in candidates]
    for row in changed:
        update_stage(conn, row["id"], "ghosted")
    return changed


def metrics(conn: sqlite3.Connection) -> dict:
    rows = list_applications(conn)
    total = len(rows)
    by_stage = {stage: sum(1 for r in rows if r["stage"] == stage) for stage in STAGES}
    outreach_sent = sum(1 for r in rows if r["stage"] in
                         ("outreach_sent", "responded", "interview", "offer", "rejected", "ghosted"))
    responded = sum(1 for r in rows if r["stage"] in ("responded", "interview", "offer"))
    interviews = by_stage["interview"] + by_stage["offer"]
    return {
        "total": total,
        "by_stage": by_stage,
        "response_rate": round(responded / outreach_sent, 2) if outreach_sent else None,
        "interview_conversion": round(interviews / outreach_sent, 2) if outreach_sent else None,
        "not_really_hiring_flagged": sum(1 for r in rows if r["not_really_hiring"]),
    }
