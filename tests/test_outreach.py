from types import SimpleNamespace

import pytest

from jobscout import outreach

PROFILE = {
    "name": "Amit Kumar Sahu",
    "title": "Senior Data Engineer",
    "years_experience": 9,
    "skills": ["python", "pyspark", "sql", "airflow"],
}


class FakeMessages:
    def __init__(self, text: str):
        self._text = text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


class FakeAnthropicClient:
    def __init__(self, api_key=None, text="Dear hiring team, ..."):
        self.api_key = api_key
        self.messages = FakeMessages(text)


class FakeAnthropicModule:
    def __init__(self, text="Dear hiring team, ..."):
        self._text = text
        self.last_client = None

    def Anthropic(self, api_key=None):
        self.last_client = FakeAnthropicClient(api_key=api_key, text=self._text)
        return self.last_client


def test_draft_email_uses_mocked_client(monkeypatch):
    fake_module = FakeAnthropicModule(text="Hello, I'd love to chat about this role.")
    monkeypatch.setattr(outreach, "anthropic", fake_module)
    monkeypatch.delenv("JOBSCOUT_MODEL", raising=False)

    result = outreach.draft_email("Some job description", PROFILE, api_key="sk-ant-fake")

    assert result == "Hello, I'd love to chat about this role."
    assert fake_module.last_client.api_key == "sk-ant-fake"
    assert fake_module.last_client.messages.last_kwargs["model"] == outreach.DEFAULT_MODEL


def test_draft_email_uses_jobscout_model_env(monkeypatch):
    fake_module = FakeAnthropicModule(text="Hi there")
    monkeypatch.setattr(outreach, "anthropic", fake_module)
    monkeypatch.setenv("JOBSCOUT_MODEL", "claude-custom-model")

    outreach.draft_email("Some JD", PROFILE, api_key="sk-ant-fake")

    assert fake_module.last_client.messages.last_kwargs["model"] == "claude-custom-model"


def test_draft_email_without_anthropic_installed(monkeypatch):
    monkeypatch.setattr(outreach, "anthropic", None)
    with pytest.raises(outreach.OutreachError):
        outreach.draft_email("Some JD", PROFILE, api_key="sk-ant-fake")


def test_draft_email_raises_on_empty_response(monkeypatch):
    fake_module = FakeAnthropicModule(text="")
    monkeypatch.setattr(outreach, "anthropic", fake_module)
    with pytest.raises(outreach.OutreachError):
        outreach.draft_email("Some JD", PROFILE, api_key="sk-ant-fake")


def test_build_prompt_includes_profile_and_description():
    prompt = outreach.build_prompt("Looking for a data pipeline wizard.", PROFILE)
    assert "Amit Kumar Sahu" in prompt
    assert "Looking for a data pipeline wizard." in prompt
    assert "one paragraph" in prompt.lower()
