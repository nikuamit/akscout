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


def test_fetch_workday_paginates_past_the_first_two_pages(fake_session):
    # Regression test: Workday's `total` field is only accurate on the
    # first page - every later page reports total=0 (confirmed live on
    # Novartis), which used to make the loop stop after exactly 2 pages
    # (40 jobs) no matter how many postings actually existed.
    def make_page(n, total):
        return {
            "total": total,
            "jobPostings": [
                {"title": f"Job {i}", "externalPath": f"/job/{i}", "locationsText": "Remote"}
                for i in range(n)
            ],
        }

    class PagingSession:
        def __init__(self):
            self.headers = {}
            self.responses = [
                FakeResponse(json_data=make_page(20, 45)),   # page 1: real total
                FakeResponse(json_data=make_page(20, 0)),     # page 2: total resets to 0
                FakeResponse(json_data=make_page(5, 0)),      # page 3: last partial page
            ]
            self.calls = 0

        def post(self, url, **kwargs):
            resp = self.responses[min(self.calls, len(self.responses) - 1)]
            self.calls += 1
            return resp

    session = PagingSession()
    entry = {"host": "acme.wd1.myworkdayjobs.com", "tenant": "acme", "site": "External",
              "name": "Acme"}
    jobs = ats.fetch_workday(entry, max_results=100, session=session)
    assert len(jobs) == 45
    assert session.calls == 3


def test_fetch_oracle_hcm(fake_session):
    data = load_json_fixture("oracle_hcm_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    entry = {"host": "iaziqy.fa.ocs.oraclecloud.com", "site": "UberCareers", "name": "Uber"}
    jobs = ats.fetch_oracle_hcm(entry, session=session)
    assert len(jobs) == 2
    assert jobs[0].source == "oracle_hcm"
    assert "UberCareers" in jobs[0].url


def test_fetch_oracle_hcm_requests_expand_param(fake_session):
    # Regression test: Oracle's recruitingCEJobRequisitions endpoint silently
    # omits "requisitionList" from every item unless the request carries
    # expand=requisitionList.secondaryLocations - without it fetch_oracle_hcm
    # used to return an empty list even when the tenant has open roles.
    data = load_json_fixture("oracle_hcm_jobs.json")

    class RecordingSession:
        def __init__(self):
            self.headers = {}
            self.last_params = None

        def get(self, url, **kwargs):
            self.last_params = kwargs.get("params", {})
            return FakeResponse(json_data=data)

    session = RecordingSession()
    ats.fetch_oracle_hcm({"host": "iaziqy.fa.ocs.oraclecloud.com", "site": "UberCareers"},
                          session=session)
    assert session.last_params["expand"] == "requisitionList.secondaryLocations"


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


def test_fetch_smartrecruiters(fake_session):
    data = load_json_fixture("smartrecruiters_jobs.json")
    session = fake_session(FakeResponse(json_data=data))
    entry = {"company": "Freshworks", "name": "Freshworks"}
    jobs = ats.fetch_smartrecruiters(entry, session=session)
    assert len(jobs) == 2
    assert jobs[0].source == "smartrecruiters"
    assert jobs[0].url == f"https://jobs.smartrecruiters.com/Freshworks/{jobs[0].id}"


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
    (
        "https://jobs.smartrecruiters.com/Freshworks/744000156328949-lead",
        {"ats": "smartrecruiters", "company": "Freshworks"},
    ),
])
def test_detect_ats(url, expected):
    assert ats.detect_ats(url) == expected


def test_detect_ats_unknown():
    assert ats.detect_ats("https://example.com/careers") is None
