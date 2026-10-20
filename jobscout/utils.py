import html
import re
from typing import Optional

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
# Requires a letter (or a leading "/") right after "<" so a literal "<3" in
# job-description text doesn't get mistaken for a tag and greedily eaten up
# to the next real ">" this would match.
_TAG_RE = re.compile(r"</?[a-zA-Z][^<>]*>")
_WS_RE = re.compile(r"\s+")

# A cap, not a precise limit: pathologically large job descriptions (seen in
# the wild at 200KB+) cost real time in the matcher's substring scans for no
# benefit, since nothing useful lives past the first few thousand words.
MAX_DESCRIPTION_LENGTH = 20_000


def strip_html(text: Optional[str] = None) -> str:
    if not text:
        return ""
    # Unescape first: some ATSs (Greenhouse) double-encode their HTML, so
    # the tags themselves only become real "<...>" after this step. The
    # tag regex then requires a letter right after "<"/"</", so a literal
    # "<3" that unescaping also exposes doesn't get mistaken for a tag and
    # greedily eaten up to the next real ">".
    unescaped = html.unescape(text)
    without_script_style = _SCRIPT_STYLE_RE.sub(" ", unescaped)
    no_tags = _TAG_RE.sub(" ", without_script_style)
    cleaned = _WS_RE.sub(" ", no_tags).strip()
    return cleaned[:MAX_DESCRIPTION_LENGTH]
