import json
from pathlib import Path

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def load_json_fixture(name: str):
    return json.loads(load_fixture(name))


class FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200, headers=None, url=None):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url or ""

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """A stand-in for requests.Session that returns a fixed response."""

    def __init__(self, response: FakeResponse):
        self.headers: dict = {}
        self._response = response

    def get(self, url, **kwargs):
        return self._response

    def post(self, url, **kwargs):
        return self._response

    def request(self, method, url, **kwargs):
        return getattr(self, method.lower())(url, **kwargs)


@pytest.fixture
def fake_session():
    def _make(response: FakeResponse) -> FakeSession:
        return FakeSession(response)
    return _make
