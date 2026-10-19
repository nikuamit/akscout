import html
import re
from typing import Optional

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: Optional[str] = None) -> str:
    if not text:
        return ""
    unescaped = html.unescape(text)
    no_tags = _TAG_RE.sub(" ", unescaped)
    return _WS_RE.sub(" ", no_tags).strip()
