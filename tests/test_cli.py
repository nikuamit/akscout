import requests

from jobscout import cli
from jobscout.models import Job


def test_collect_jobs_survives_one_entry_raising_a_network_error(monkeypatch):
    good_job = Job(id="1", title="Data Engineer", company="Good Co", location="Remote",
                    url="https://example.com/1", source="greenhouse")

    def fake_fetch_jobs(entry, **kwargs):
        if entry["name"] == "Flaky Co":
            raise requests.exceptions.Timeout("connect timed out")
        return [good_job]

    monkeypatch.setattr(cli, "fetch_jobs", fake_fetch_jobs)

    profile = {
        "watchlist": [
            {"name": "Flaky Co", "ats": "greenhouse", "board": "flaky"},
            {"name": "Good Co", "ats": "greenhouse", "board": "good"},
        ]
    }

    jobs = cli._collect_jobs(profile)

    assert jobs == [good_job]
