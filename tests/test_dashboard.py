from datetime import datetime, timedelta, timezone

from jobscout.dashboard import (
    needs_follow_up,
    parse_report_table,
    rejection_breakdown,
    stage_counts,
    top_companies_by_score,
)


def test_parse_report_table_extracts_rows():
    markdown = (
        "# JobScout report\n\n"
        "_Generated now - 2 jobs_\n\n"
        "| Score | Title | Company | Location | Link |\n"
        "|---|---|---|---|---|\n"
        "| 85 | Senior Data Engineer | Acme | Bengaluru | [greenhouse](https://example.com/1) |\n"
        "| 40 | Software Engineer | Acme | Remote | [lever](https://example.com/2) |\n"
    )
    rows = parse_report_table(markdown)
    assert len(rows) == 2
    assert rows[0] == {
        "score": 85, "title": "Senior Data Engineer", "company": "Acme",
        "location": "Bengaluru", "source": "greenhouse", "link": "https://example.com/1",
    }
    assert rows[1]["score"] == 40


def test_parse_report_table_ignores_non_data_lines():
    markdown = "# Title\n\n_blah_\n\n| Score | Title | Company | Location | Link |\n|---|---|---|---|---|\n"
    assert parse_report_table(markdown) == []


def test_stage_counts():
    rows = [{"stage": "applied"}, {"stage": "applied"}, {"stage": "ghosted"}]
    counts = stage_counts(rows)
    assert counts["applied"] == 2
    assert counts["ghosted"] == 1
    assert counts["interview"] == 0


def test_rejection_breakdown_only_counts_rejected_with_a_reason():
    rows = [
        {"stage": "rejected", "rejection_reason": "role_closed_or_filled"},
        {"stage": "rejected", "rejection_reason": "role_closed_or_filled"},
        {"stage": "rejected", "rejection_reason": "other"},
        {"stage": "applied", "rejection_reason": None},
    ]
    breakdown = rejection_breakdown(rows)
    assert breakdown == {"role_closed_or_filled": 2, "other": 1}


def test_top_companies_by_score_averages_and_sorts():
    rows = [
        {"company": "Acme", "score": 90},
        {"company": "Acme", "score": 70},
        {"company": "Beta", "score": 50},
    ]
    result = top_companies_by_score(rows, limit=10)
    assert result[0] == ("Acme", 80.0)
    assert result[1] == ("Beta", 50.0)


def test_top_companies_by_score_skips_missing_scores():
    rows = [{"company": "Acme", "score": None}, {"company": "Beta", "score": 60}]
    result = top_companies_by_score(rows)
    assert result == [("Beta", 60.0)]


def test_needs_follow_up_flags_stale_active_applications():
    stale = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rows = [
        {"stage": "outreach_sent", "last_contact_at": stale, "applied_at": None,
         "created_at": stale, "id": 1},
        {"stage": "outreach_sent", "last_contact_at": fresh, "applied_at": None,
         "created_at": fresh, "id": 2},
        {"stage": "rejected", "last_contact_at": stale, "applied_at": None,
         "created_at": stale, "id": 3},
    ]
    due = needs_follow_up(rows, stale_days=14)
    assert [r["id"] for r in due] == [1]


def test_needs_follow_up_handles_missing_dates_gracefully():
    rows = [{"stage": "applied", "last_contact_at": None, "applied_at": None,
             "created_at": None, "id": 1}]
    assert needs_follow_up(rows) == []
