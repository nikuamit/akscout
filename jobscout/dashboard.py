"""A local Streamlit dashboard over the SQLite tracker + latest scan report.

Data-shaping logic lives in plain functions (unit-tested without Streamlit
installed); `streamlit` itself is only imported inside `main()`, so this
module stays importable - and `jobscout track`/`daily` keep working - even
if the `dashboard` extra isn't installed.

Run with: jobscout dashboard   (shells out to `streamlit run` on this file)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from jobscout import tracker

_REPORT_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*\[(.*?)\]\((.*?)\)\s*\|$"
)


def parse_report_table(markdown_text: str) -> list[dict]:
    """Pulls the score/title/company/location/source/link rows out of a
    report written by jobscout.report.render_markdown.
    """
    rows = []
    for line in markdown_text.splitlines():
        m = _REPORT_ROW_RE.match(line.strip())
        if not m:
            continue
        score, title, company, location, source, link = m.groups()
        rows.append({
            "score": int(score), "title": title, "company": company,
            "location": location, "source": source, "link": link,
        })
    return rows


def load_hiring_now(report_path: str = "reports/latest.md") -> list[dict]:
    path = Path(report_path)
    if not path.exists():
        return []
    return parse_report_table(path.read_text())


def stage_counts(rows: list[dict]) -> dict:
    counts = {stage: 0 for stage in tracker.STAGES}
    for r in rows:
        counts[r["stage"]] = counts.get(r["stage"], 0) + 1
    return counts


def rejection_breakdown(rows: list[dict]) -> dict:
    breakdown: dict[str, int] = {}
    for r in rows:
        if r["stage"] == "rejected" and r.get("rejection_reason"):
            breakdown[r["rejection_reason"]] = breakdown.get(r["rejection_reason"], 0) + 1
    return breakdown

def top_companies_by_score(rows: list[dict], *, limit: int = 10) -> list[tuple[str, float]]:
    totals: dict[str, list[int]] = {}
    for r in rows:
        if r.get("score") is None:
            continue
        totals.setdefault(r["company"], []).append(r["score"])
    averages = [(company, sum(scores) / len(scores)) for company, scores in totals.items()]
    averages.sort(key=lambda pair: pair[1], reverse=True)
    return averages[:limit]


def needs_follow_up(rows: list[dict], *, stale_days: int = 14) -> list[dict]:
    """Applications in an active, non-terminal stage with no contact
    recorded in `stale_days` - a softer, earlier warning than the
    `sweep-ghosted` cutoff (default 21 days), and read-only: it doesn't
    change anything in the database, just flags it for the dashboard.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    due = []
    for r in rows:
        if r["stage"] not in ("applied", "outreach_sent", "responded"):
            continue
        last = r.get("last_contact_at") or r.get("applied_at") or r.get("created_at")
        if not last:
            continue
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            continue
        if last_dt < cutoff:
            due.append(r)
    return due


def main() -> None:  # pragma: no cover - thin UI wiring, logic tested above
    import streamlit as st

    st.set_page_config(page_title="AKScout dashboard", layout="wide")
    st.title("AKScout")

    conn = tracker.connect()
    rows = tracker.list_applications(conn)

    tab_hiring, tab_pipeline, tab_metrics, tab_insights, tab_followups = st.tabs(
        ["Hiring Now", "Pipeline", "Metrics", "Insights", "Follow-ups"]
    )

    with tab_hiring:
        st.subheader("Latest scan")
        hiring_rows = load_hiring_now()
        if not hiring_rows:
            st.info("No report yet - run `jobscout scan` first.")
        else:
            st.dataframe(hiring_rows, use_container_width=True)

    with tab_pipeline:
        st.subheader("Applications by stage")
        for stage in tracker.STAGES:
            stage_rows = [r for r in rows if r["stage"] == stage]
            if not stage_rows:
                continue
            st.markdown(f"**{stage}** ({len(stage_rows)})")
            st.dataframe(stage_rows, use_container_width=True)

    with tab_metrics:
        st.subheader("Pipeline metrics")
        m = tracker.metrics(conn)
        col1, col2, col3 = st.columns(3)
        col1.metric("Total tracked", m["total"])
        col2.metric("Response rate",
                    f"{m['response_rate'] * 100:.0f}%" if m["response_rate"] is not None else "-")
        col3.metric("Interview conversion",
                    f"{m['interview_conversion'] * 100:.0f}%"
                    if m["interview_conversion"] is not None else "-")
        st.bar_chart(m["by_stage"])

    with tab_insights:
        st.subheader("Top companies by average score")
        st.table(top_companies_by_score(rows))
        st.subheader("Rejection reasons")
        st.bar_chart(rejection_breakdown(rows))

    with tab_followups:
        st.subheader("Needs follow-up (14+ days quiet)")
        due = needs_follow_up(rows)
        if not due:
            st.success("Nothing overdue.")
        else:
            st.dataframe(due, use_container_width=True)


if __name__ == "__main__":  # pragma: no cover
    main()
