import requests
import responses

from jobscout.sources import ats


def test_tracking_params_are_ignored():
    result = ats.detect_ats(
        "https://boards.greenhouse.io/stripe?utm_source=linkedin&utm_campaign=q4&gh_src=abc123"
    )
    assert result == {"ats": "greenhouse", "board": "stripe"}


def test_trailing_slash_is_ignored():
    result = ats.detect_ats("https://boards.greenhouse.io/stripe/")
    assert result == {"ats": "greenhouse", "board": "stripe"}


def test_http_vs_https_both_detected():
    assert ats.detect_ats("http://boards.greenhouse.io/stripe") == \
        {"ats": "greenhouse", "board": "stripe"}
    assert ats.detect_ats("https://boards.greenhouse.io/stripe") == \
        {"ats": "greenhouse", "board": "stripe"}


def test_bare_domain_without_scheme():
    assert ats.detect_ats("boards.greenhouse.io/stripe") == \
        {"ats": "greenhouse", "board": "stripe"}


def test_www_prefix_does_not_break_detection():
    result = ats.detect_ats("https://www.jobs.lever.co/example")
    assert result == {"ats": "lever", "board": "example"}


def test_unsupported_ats_returns_none_not_a_crash():
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://careers.some-random-company.example/",
                 body="<html>no known ATS markers here</html>", status=200)
        result = ats.detect_ats("https://careers.some-random-company.example/",
                                 session=requests.Session())
    assert result is None


def test_unreachable_custom_domain_returns_none_not_a_crash():
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://totally-dead-domain.example/careers",
                 body=requests.exceptions.ConnectionError("name resolution failed"))
        result = ats.detect_ats("https://totally-dead-domain.example/careers",
                                 session=requests.Session())
    assert result is None


def test_custom_domain_redirecting_to_greenhouse_is_detected():
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET, "https://careers.examplecorp.com/",
            status=302,
            headers={"Location": "https://boards.greenhouse.io/examplecorp"},
        )
        rsps.add(
            responses.GET, "https://boards.greenhouse.io/examplecorp",
            status=200, body="ok",
        )
        result = ats.detect_ats("https://careers.examplecorp.com/", session=requests.Session())
    assert result == {"ats": "greenhouse", "board": "examplecorp"}


def test_custom_domain_redirecting_to_workday_is_detected():
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET, "https://jobs.examplecorp.com/careers",
            status=301,
            headers={"Location":
                     "https://examplecorp.wd5.myworkdayjobs.com/en-US/External/job/Remote/x_R1"},
        )
        rsps.add(
            responses.GET,
            "https://examplecorp.wd5.myworkdayjobs.com/en-US/External/job/Remote/x_R1",
            status=200, body="ok",
        )
        result = ats.detect_ats("https://jobs.examplecorp.com/careers", session=requests.Session())
    assert result == {"ats": "workday", "host": "examplecorp.wd5.myworkdayjobs.com",
                       "tenant": "examplecorp", "site": "External"}


def test_a_company_can_have_entries_on_two_different_ats(fake_session):
    # Nothing ties "one company" to "one ATS" in the data model - a
    # watchlist can carry two entries with the same display name on
    # different boards (e.g. a legacy Lever board alongside a new
    # Greenhouse one during a migration), and each fetches independently.
    from tests.conftest import FakeResponse

    gh_session = fake_session(FakeResponse(json_data={"jobs": [
        {"id": 1, "title": "Data Engineer (new board)"},
    ]}))
    lever_session = fake_session(FakeResponse(json_data=[
        {"id": "1", "text": "Data Engineer (legacy board)"},
    ]))

    gh_jobs = ats.fetch_jobs({"ats": "greenhouse", "board": "examplecorp",
                               "name": "ExampleCorp"}, session=gh_session)
    lever_jobs = ats.fetch_jobs({"ats": "lever", "board": "examplecorp-legacy",
                                  "name": "ExampleCorp"}, session=lever_session)

    assert gh_jobs[0].title == "Data Engineer (new board)"
    assert lever_jobs[0].title == "Data Engineer (legacy board)"
