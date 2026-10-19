import pytest

from jobscout.sources import ats
from tests.conftest import FakeResponse, load_fixture, load_json_fixture


def test_fetch_greenhouse(fake_session):
    data = load_json_fixture("greenhouse_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    jobs = ats.fetch_greenhouse({"board": "stripe", "name": "Stripe"}, session=session)
    assert len(jobs) == 2
    assert jobs[0].source == "greenhouse"
    assert jobs[0].company == "Stripe"
    assert jobs[0].title
    assert jobs[0].url.startswith("https://")
    assert "<" not in jobs[0].description  # HTML stripped


def test_fetch_greenhouse_404(fake_session):
    session = fake_session(FakeResponse(json_data={}, status_code=404))
    with pytest.raises(ats.AdapterError):
        ats.fetch_greenhouse({"board": "nope", "name": "Nope"}, session=session)


def test_fetch_lever(fake_session):
    data = load_json_fixture("lever_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    jobs = ats.fetch_lever({"board": "example", "name": "Example"}, session=session)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior Data Engineer"
    assert "Remote - India" in jobs[0].location
    assert "PySpark" in jobs[0].description


def test_fetch_workday(fake_session):
    data = load_json_fixture("workday_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    entry = {"host": "takeda.wd502.myworkdayjobs.com", "tenant": "takeda", "site": "External",
             "name": "Takeda"}
    jobs = ats.fetch_workday(entry, session=session)
    assert len(jobs) == 2
    assert jobs[0].source == "workday"
    assert jobs[0].url.startswith("https://takeda.wd502.myworkdayjobs.com/en-US/External/job/")


def test_fetch_workday_422(fake_session):
    session = fake_session(FakeResponse(json_data={}, status_code=422))
    entry = {"host": "bad.wd1.myworkdayjobs.com", "tenant": "bad", "site": "External", "name": "Bad"}
    with pytest.raises(ats.AdapterError):
        ats.fetch_workday(entry, session=session)


def test_fetch_oracle_hcm(fake_session):
    data = load_json_fixture("oracle_hcm_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    entry = {"host": "iaziqy.fa.ocs.oraclecloud.com", "site": "UberCareers", "name": "Uber"}
    jobs = ats.fetch_oracle_hcm(entry, session=session)
    assert len(jobs) == 2
    assert jobs[0].source == "oracle_hcm"
    assert "UberCareers" in jobs[0].url


def test_fetch_successfactors(fake_session):
    html = load_fixture("successfactors_search.html")
    session = fake_session(FakeResponse(text=html))
    entry = {"host": "career5.successfactors.com", "company_id": "EXAMPLE", "name": "Example"}
    jobs = ats.fetch_successfactors(entry, session=session)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior Data Engineer"
    assert "Bengaluru" in jobs[0].location


def test_fetch_icims(fake_session):
    data = load_json_fixture("icims_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    entry = {"host": "careers.example.icims.com", "name": "Example"}
    jobs = ats.fetch_icims(entry, session=session)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior Data Engineer"
    assert "Bengaluru" in jobs[0].location


def test_fetch_jobs_dispatch(fake_session):
    data = load_json_fixture("greenhouse_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    jobs = ats.fetch_jobs({"ats": "greenhouse", "board": "stripe", "name": "Stripe"}, session=session)
    assert len(jobs) == 2


def test_fetch_jobs_unknown_ats():
    with pytest.raises(ats.AdapterError):
        ats.fetch_jobs({"ats": "carrier-pigeon", "name": "Nope"})


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/stripe", {"ats": "greenhouse", "board": "stripe"}),
    ("https://job-boards.greenhouse.io/databricks", {"ats": "greenhouse", "board": "databricks"}),
    ("https://jobs.lever.co/example", {"ats": "lever", "board": "example"}),
    (
        "https://takeda.wd502.myworkdayjobs.com/en-US/External/job/Boston/foo_R1",
        {"ats": "workday", "host": "takeda.wd502.myworkdayjobs.com", "tenant": "takeda",
         "site": "External"},
    ),
    (
        "https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/UberCareers/jobs",
        {"ats": "oracle_hcm", "host": "iaziqy.fa.ocs.oraclecloud.com", "site": "UberCareers"},
    ),
    (
        "https://career5.successfactors.com/career?company=EXAMPLE",
        {"ats": "successfactors", "host": "career5.successfactors.com", "company_id": "EXAMPLE"},
    ),
    (
        "https://careers.example.icims.com/jobs/10045/senior-data-engineer/job",
        {"ats": "icims", "host": "careers.example.icims.com"},
    ),
])
def test_detect_ats(url, expected):
    assert ats.detect_ats(url) == expected


def test_detect_ats_unknown():
    assert ats.detect_ats("https://example.com/careers") is None
