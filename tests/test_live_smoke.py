"""Real-network smoke tests against each ATS's actual public API.

Skipped by default (see `addopts` in pyproject.toml) because they hit the
real internet and real companies' real job boards - run explicitly with:

    pytest -m live
"""

import pytest

from jobscout.sources import ats

pytestmark = pytest.mark.live


def test_greenhouse_live():
    jobs = ats.fetch_greenhouse({"board": "stripe", "name": "Stripe"})
    assert len(jobs) > 0


def test_lever_live():
    jobs = ats.fetch_lever({"board": "cred", "name": "CRED"})
    assert len(jobs) > 0


def test_workday_live():
    jobs = ats.fetch_workday({
        "host": "walmart.wd504.myworkdayjobs.com", "tenant": "walmart",
        "site": "WalmartExternal", "name": "Walmart Global Tech",
    }, max_results=20)
    assert len(jobs) > 0


def test_oracle_hcm_live():
    jobs = ats.fetch_oracle_hcm({
        "host": "iaziqy.fa.ocs.oraclecloud.com", "site": "UberCareers", "name": "Uber",
    }, max_results=20)
    assert len(jobs) > 0


def test_smartrecruiters_live():
    jobs = ats.fetch_smartrecruiters({"company": "Freshworks", "name": "Freshworks"},
                                      max_results=20)
    assert len(jobs) > 0


def test_ashby_live():
    jobs = ats.fetch_ashby({"board": "ramp", "name": "Ramp"})
    assert len(jobs) > 0
