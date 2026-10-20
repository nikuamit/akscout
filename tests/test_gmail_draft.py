import base64

import pytest

from jobscout import gmail_draft


class FakeDraftsResource:
    def __init__(self, draft_id="draft-123", raise_error=False):
        self.draft_id = draft_id
        self.raise_error = raise_error
        self.last_body = None

    def create(self, userId, body):
        self.last_body = body
        return self

    def execute(self):
        if self.raise_error:
            raise RuntimeError("quota exceeded")
        return {"id": self.draft_id}


class FakeUsersResource:
    def __init__(self, drafts: FakeDraftsResource):
        self._drafts = drafts

    def drafts(self):
        return self._drafts


class FakeGmailService:
    def __init__(self, drafts: FakeDraftsResource):
        self._users = FakeUsersResource(drafts)

    def users(self):
        return self._users


def test_create_draft_returns_draft_id():
    drafts = FakeDraftsResource(draft_id="abc-999")
    service = FakeGmailService(drafts)

    draft_id = gmail_draft.create_draft(
        to="recruiter@example.com", subject="Interested in the role",
        body="Hello, I'd love to chat.", service=service,
    )

    assert draft_id == "abc-999"


def test_create_draft_encodes_the_message_correctly():
    drafts = FakeDraftsResource()
    service = FakeGmailService(drafts)

    gmail_draft.create_draft(to="recruiter@example.com", subject="Hi",
                              body="Body text here.", service=service)

    raw = drafts.last_body["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw).decode()
    assert "recruiter@example.com" in decoded
    assert "Body text here." in decoded
    assert "Hi" in decoded


def test_create_draft_wraps_api_errors():
    drafts = FakeDraftsResource(raise_error=True)
    service = FakeGmailService(drafts)

    with pytest.raises(gmail_draft.GmailDraftError, match="quota exceeded"):
        gmail_draft.create_draft(to="x@example.com", subject="s", body="b", service=service)


def test_create_draft_without_service_or_google_libs_raises_clear_error(monkeypatch):
    monkeypatch.setattr(gmail_draft, "build", None)
    with pytest.raises(gmail_draft.GmailDraftError, match="\\[gmail\\]"):
        gmail_draft.create_draft(to="x@example.com", subject="s", body="b")
