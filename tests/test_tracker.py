from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from jobscout import tracker
from jobscout.models import Job


@pytest.fixture
def conn():
    return tracker.connect(":memory:")


def _job(**overrides) -> Job:
    base = dict(id="1", title="Senior Data Engineer", company="Acme", location="Bengaluru",
                url="https://example.com/1", source="greenhouse", description="")
    base.update(overrides)
    return Job(**base)


def test_add_application_and_list(conn):
    app_id = tracker.add_application(conn, _job(), score=85)
    rows = tracker.list_applications(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == app_id
    assert rows[0]["stage"] == "shortlisted"
    assert rows[0]["score"] == 85


def test_adding_the_same_job_twice_does_not_duplicate(conn):
    first_id = tracker.add_application(conn, _job())
    second_id = tracker.add_application(conn, _job())
    assert first_id == second_id
    assert len(tracker.list_applications(conn)) == 1


def test_update_stage_sets_applied_at(conn):
    app_id = tracker.add_application(conn, _job())
    tracker.update_stage(conn, app_id, "applied")
    row = tracker.list_applications(conn, stage="applied")[0]
    assert row["applied_at"] is not None


def test_update_stage_rejects_unknown_stage(conn):
    app_id = tracker.add_application(conn, _job())
    with pytest.raises(ValueError):
        tracker.update_stage(conn, app_id, "not-a-real-stage")


def test_set_contact_preserves_existing_fields_when_not_given(conn):
    app_id = tracker.add_application(conn, _job())
    tracker.set_contact(conn, app_id, name="Jane Recruiter", email="jane@example.com")
    tracker.set_contact(conn, app_id, linkedin="linkedin.com/in/janerecruiter")
    row = tracker.list_applications(conn)[0]
    assert row["ta_name"] == "Jane Recruiter"
    assert row["ta_email"] == "jane@example.com"
    assert row["ta_linkedin"] == "linkedin.com/in/janerecruiter"


@pytest.mark.parametrize("text,expected", [
    ("Unfortunately we've decided to move forward with other candidates.", "no_feedback"),
    ("We're looking for someone with more experience in distributed systems.",
     "experience_mismatch"),
    ("This position has been filled internally.", "role_closed_or_filled"),
    ("We're not able to support remote work without visa sponsorship for this role.",
     "location_or_remote"),
    ("We've put this search on hold due to a hiring freeze.", "timing_or_priorities"),
    ("Thanks for applying!", "other"),
])
def test_classify_rejection_reason(text, expected):
    assert tracker.classify_rejection_reason(text) == expected


def test_set_rejection_stores_classification_and_moves_stage(conn):
    app_id = tracker.add_application(conn, _job())
    category = tracker.set_rejection(conn, app_id, "This position has been filled internally.")
    assert category == "role_closed_or_filled"
    row = tracker.list_applications(conn)[0]
    assert row["stage"] == "rejected"
    assert row["rejection_reason"] == "role_closed_or_filled"
    assert "filled internally" in row["rejection_reason_raw"]


def test_mark_stale_as_ghosted(conn):
    with freeze_time("2026-01-01T00:00:00+00:00"):
        app_id = tracker.add_application(conn, _job())
        tracker.update_stage(conn, app_id, "outreach_sent")

    with freeze_time("2026-02-01T00:00:00+00:00"):  # 31 days later
        changed = tracker.mark_stale_as_ghosted(conn, stale_days=21)

    assert len(changed) == 1
    assert changed[0]["id"] == app_id
    row = tracker.list_applications(conn)[0]
    assert row["stage"] == "ghosted"


def test_mark_stale_as_ghosted_leaves_recent_contact_alone(conn):
    with freeze_time("2026-01-01T00:00:00+00:00"):
        app_id = tracker.add_application(conn, _job())
        tracker.update_stage(conn, app_id, "outreach_sent")

    with freeze_time("2026-01-05T00:00:00+00:00"):  # only 4 days later
        changed = tracker.mark_stale_as_ghosted(conn, stale_days=21)

    assert changed == []
    assert tracker.list_applications(conn)[0]["stage"] == "outreach_sent"


def test_metrics_computes_response_rate_and_interview_conversion(conn):
    for i, stage in enumerate(("outreach_sent", "outreach_sent", "responded", "interview", "ghosted")):
        app_id = tracker.add_application(conn, _job(id=f"job-{i}"))
        tracker.update_stage(conn, app_id, stage)

    m = tracker.metrics(conn)
    assert m["total"] == 5
    # outreach_sent*2 + responded + interview + ghosted = 5 "sent" applications
    assert m["response_rate"] == round(2 / 5, 2)
    assert m["interview_conversion"] == round(1 / 5, 2)


def test_metrics_handles_no_outreach_yet(conn):
    tracker.add_application(conn, _job())
    m = tracker.metrics(conn)
    assert m["response_rate"] is None
    assert m["interview_conversion"] is None


def test_is_not_really_hiring_flags_evergreen_phrases():
    job = _job(title="Join our Talent Community", description="")
    assert tracker.is_not_really_hiring(job) is True


def test_is_not_really_hiring_flags_very_old_postings():
    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    job = _job(posted_at=old_date)
    assert tracker.is_not_really_hiring(job) is True


def test_is_not_really_hiring_leaves_fresh_normal_postings_alone():
    recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    job = _job(title="Senior Data Engineer", description="Build pipelines.",
                posted_at=recent_date)
    assert tracker.is_not_really_hiring(job) is False


def test_is_not_really_hiring_handles_unparseable_dates_gracefully():
    job = _job(posted_at="not-a-real-date")
    assert tracker.is_not_really_hiring(job) is False
