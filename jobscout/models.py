from dataclasses import dataclass
from typing import Optional


@dataclass
class Job:
    """A normalized job posting, regardless of which ATS it came from."""

    id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: Optional[str] = None
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "posted_at": self.posted_at,
            "description": self.description,
        }
