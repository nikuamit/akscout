import html
import re
from typing import Optional

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# A cap, not a precise limit: pathologically large job descriptions (seen in
# the wild at 200KB+) cost real time in the matcher's substring scans for no
# benefit, since nothing useful lives past the first few thousand words.
MAX_DESCRIPTION_LENGTH = 20_000


def strip_html(text: Optional[str] = None) -> str:
    if not text:
        return ""
    # Drop <script>/<style> blocks (tags AND their content) before the
    # generic tag-stripper, which would otherwise leave JS/CSS source
    # sitting in the plain-text description.
    without_script_style = _SCRIPT_STYLE_RE.sub(" ", text)
    unescaped = html.unescape(without_script_style)
    no_tags = _TAG_RE.sub(" ", unescaped)
    cleaned = _WS_RE.sub(" ", no_tags).strip()
    return cleaned[:MAX_DESCRIPTION_LENGTH]
