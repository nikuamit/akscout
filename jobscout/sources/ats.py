"""Adapters that fetch job postings from various Applicant Tracking Systems.

Every adapter takes a watchlist ``entry`` dict (as stored in a profile YAML
file) and returns a list of normalized :class:`~jobscout.models.Job` objects.
A single ``fetch_jobs`` dispatcher picks the right adapter from
``entry["ats"]``, and ``detect_ats`` turns a pasted careers-page URL into a
ready-to-use watchlist entry.
"""

from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs

import requests

from jobscout.models import Job
from jobscout.utils import strip_html

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 jobscout/0.1"
)
DEFAULT_TIMEOUT = 15


class AdapterError(RuntimeError):
    """Raised when an ATS responds in a shape the adapter cannot parse."""


def _session(session: Optional[requests.Session]) -> requests.Session:
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", USER_AGENT)
    s.headers.setdefault("Accept", "application/json")
    return s


# --------------------------------------------------------------------------
# Greenhouse
# --------------------------------------------------------------------------

def fetch_greenhouse(entry: dict, *, max_results: int = 60,
                      session: Optional[requests.Session] = None) -> list[Job]:
    board = entry["board"]
    company = entry.get("name", board)
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    resp = _session(session).get(url, params={"content": "true"}, timeout=DEFAULT_TIMEOUT)
    if resp.status_code == 404:
        raise AdapterError(f"Greenhouse board '{board}' not found (404)")
    resp.raise_for_status()
    try:
        data = resp.json()
        raw_jobs = data["jobs"]
    except (ValueError, KeyError) as exc:
        raise AdapterError(f"Unexpected Greenhouse response shape: {exc}") from exc

    # The board API returns every open job in one response regardless of
    # how many there are - there's no pagination to limit, so max_results
    # doesn't apply here. Truncating client-side would just silently drop
    # jobs (a 900-job board sorted alphabetically could cut off every
    # "Data Engineer" title, which starts well past position 60).
    jobs = []
    for j in raw_jobs:
        location = (j.get("location") or {}).get("name", "")
        jobs.append(Job(
            id=str(j["id"]),
            title=j.get("title", ""),
            company=company,
            location=location,
            url=j.get("absolute_url", ""),
            source="greenhouse",
            posted_at=j.get("first_published") or j.get("updated_at"),
            description=strip_html(j.get("content", "")),
        ))
    return jobs


# --------------------------------------------------------------------------
# Lever
# --------------------------------------------------------------------------

def fetch_lever(entry: dict, *, max_results: int = 60,
                session: Optional[requests.Session] = None) -> list[Job]:
    board = entry["board"]
    company = entry.get("name", board)
    url = f"https://api.lever.co/v0/postings/{board}"
    resp = _session(session).get(url, params={"mode": "json"}, timeout=DEFAULT_TIMEOUT)
    if resp.status_code == 404:
        raise AdapterError(f"Lever board '{board}' not found (404)")
    resp.raise_for_status()
    try:
        raw_jobs = resp.json()
        if not isinstance(raw_jobs, list):
            raise AdapterError(f"Unexpected Lever response shape: {raw_jobs!r}")
    except ValueError as exc:
        raise AdapterError(f"Unexpected Lever response shape: {exc}") from exc

    # Same as Greenhouse: one response has every posting already, so there's
    # nothing to gain by truncating and real jobs to lose.
    jobs = []
    for j in raw_jobs:
        categories = j.get("categories") or {}
        location = categories.get("location", "")
        description_parts = [j.get("descriptionPlain") or strip_html(j.get("description", ""))]
        for lst in j.get("lists") or []:
            description_parts.append(strip_html(lst.get("content", "")))
        jobs.append(Job(
            id=str(j.get("id", "")),
            title=j.get("text", ""),
            company=company,
            location=location,
            url=j.get("hostedUrl", ""),
            source="lever",
            posted_at=str(j.get("createdAt", "")) or None,
            description=" ".join(p for p in description_parts if p),
        ))
    return jobs


# --------------------------------------------------------------------------
# Workday
# --------------------------------------------------------------------------

def fetch_workday(entry: dict, *, max_results: int = 60,
                   session: Optional[requests.Session] = None) -> list[Job]:
    host = entry["host"]
    tenant = entry["tenant"]
    site = entry["site"]
    company = entry.get("name", tenant)
    search_text = entry.get("search_text", "")
    api_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    jobs: list[Job] = []
    offset = 0
    page_size = 20
    sess = _session(session)
    while len(jobs) < max_results:
        body = {
            "appliedFacets": {},
            "limit": page_size,
            "offset": offset,
            "searchText": search_text,
        }
        resp = sess.post(api_url, json=body, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 404:
            raise AdapterError(f"Workday site '{tenant}/{site}' not found (404)")
        if resp.status_code == 422:
            raise AdapterError(
                f"Workday rejected request for '{tenant}/{site}' (422) - "
                "check host/tenant/site are correct"
            )
        resp.raise_for_status()
        try:
            data = resp.json()
            postings = data["jobPostings"]
        except (ValueError, KeyError) as exc:
            raise AdapterError(f"Unexpected Workday response shape: {exc}") from exc

        if not postings:
            break
        for p in postings:
            external_path = p.get("externalPath", "")
            jobs.append(Job(
                id=external_path or p.get("title", ""),
                title=p.get("title", ""),
                company=company,
                location=p.get("locationsText", ""),
                url=f"https://{host}/en-US/{site}{external_path}",
                source="workday",
                posted_at=p.get("postedOn"),
                description="",
            ))
            if len(jobs) >= max_results:
                break
        offset += page_size
        if offset >= data.get("total", 0):
            break
    return jobs


# --------------------------------------------------------------------------
# Oracle Cloud HCM (Fusion Recruiting Cloud / "ORC")
# --------------------------------------------------------------------------

def fetch_oracle_hcm(entry: dict, *, max_results: int = 60,
                      session: Optional[requests.Session] = None) -> list[Job]:
    host = entry["host"]
    site = entry["site"]
    site_number = entry.get("site_number", "CX_1")
    company = entry.get("name", site)
    keyword = entry.get("search_text", "")
    api_url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    finder = (
        f"findReqs;siteNumber={site_number},facetsList=LOCATIONS,"
        f"limit={max_results},offset=0,sortBy=POSTING_DATES_DESC"
    )
    if keyword:
        finder += f",keyword={keyword}"

    resp = _session(session).get(
        api_url,
        params={
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": finder,
        },
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
        item = data["items"][0]
    except (ValueError, KeyError, IndexError) as exc:
        raise AdapterError(f"Unexpected Oracle HCM response shape: {exc}") from exc

    reqs = item.get("requisitionList") or []
    jobs = []
    for r in reqs[:max_results]:
        jobs.append(Job(
            id=str(r.get("Id", "")),
            title=r.get("Title", ""),
            company=company,
            location=r.get("PrimaryLocation", ""),
            url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r.get('Id', '')}",
            source="oracle_hcm",
            posted_at=r.get("PostedDate"),
            description=strip_html(r.get("ShortDescriptionStr", "")),
        ))
    return jobs


# --------------------------------------------------------------------------
# SuccessFactors (Career Site Builder) - no public JSON API, so we scrape the
# server-rendered search page.
# --------------------------------------------------------------------------

def fetch_successfactors(entry: dict, *, max_results: int = 60,
                          session: Optional[requests.Session] = None) -> list[Job]:
    """Scrapes the server-rendered search page (SuccessFactors Career Site
    Builder has no public JSON API). Fetches a single page of results -
    enough to confirm the site is live and surface its most recent postings.
    """
    from bs4 import BeautifulSoup

    host = entry["host"]
    company_id = entry.get("company_id")
    company = entry.get("name", host)

    sess = _session(session)
    sess.headers["Accept"] = "text/html"
    params = {
        "q": entry.get("search_text", ""),
        "sortColumn": "referencedate",
        "sortDirection": "desc",
        "locale": "en_US",
        "startrow": 0,
    }
    if company_id:
        params["company"] = company_id
    resp = sess.get(f"https://{host}/search/", params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select("a.jobTitle-link")

    jobs: list[Job] = []
    for a in links[:max_results]:
        href = a.get("href", "")
        title = a.get_text(strip=True)
        row = a.find_parent("tr") or a.find_parent("div")
        location = ""
        if row is not None:
            loc_el = row.select_one(".jobLocation, .colLocation")
            if loc_el is not None:
                location = loc_el.get_text(strip=True)
        match = re.search(r"/job/[^/]+/(\d+)/?", href)
        job_id = match.group(1) if match else href
        jobs.append(Job(
            id=job_id,
            title=title,
            company=company,
            location=location,
            url=href if href.startswith("http") else f"https://{host}{href}",
            source="successfactors",
        ))
    return jobs


# --------------------------------------------------------------------------
# SmartRecruiters - public, documented Postings API, no auth needed.
# --------------------------------------------------------------------------

def fetch_smartrecruiters(entry: dict, *, max_results: int = 60,
                           session: Optional[requests.Session] = None) -> list[Job]:
    company_id = entry["company"]
    company = entry.get("name", company_id)
    api_url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"

    jobs: list[Job] = []
    offset = 0
    page_size = min(max_results, 100)
    sess = _session(session)
    while len(jobs) < max_results:
        resp = sess.get(api_url, params={"limit": page_size, "offset": offset},
                         timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 404:
            raise AdapterError(f"SmartRecruiters company '{company_id}' not found (404)")
        resp.raise_for_status()
        try:
            data = resp.json()
            postings = data["content"]
        except (ValueError, KeyError) as exc:
            raise AdapterError(f"Unexpected SmartRecruiters response shape: {exc}") from exc

        if not postings:
            break
        for p in postings:
            location = (p.get("location") or {}).get("fullLocation", "")
            jobs.append(Job(
                id=str(p.get("id", "")),
                title=p.get("name", ""),
                company=company,
                location=location,
                url=f"https://jobs.smartrecruiters.com/{company_id}/{p.get('id', '')}",
                source="smartrecruiters",
                posted_at=p.get("releasedDate"),
                # The public list endpoint doesn't expose the job description
                # text (only the per-posting detail endpoint does, which
                # would mean one extra request per job) - title/location
                # only for this ATS.
                description="",
            ))
            if len(jobs) >= max_results:
                break
        offset += page_size
        if offset >= data.get("totalFound", 0):
            break
    return jobs


# --------------------------------------------------------------------------
# iCIMS (Jibe-based career sites exposing a public /api/jobs endpoint)
# --------------------------------------------------------------------------

def fetch_icims(entry: dict, *, max_results: int = 60,
                 session: Optional[requests.Session] = None) -> list[Job]:
    host = entry["host"]
    company = entry.get("name", host)
    country = entry.get("country")

    jobs: list[Job] = []
    page = 1
    page_size = min(max_results, 100)
    sess = _session(session)
    while len(jobs) < max_results:
        params = {
            "page": page,
            "limit": page_size,
            "sortBy": "posted_date",
            "descending": "true",
        }
        if country:
            params["country"] = country
        resp = sess.get(f"https://{host}/api/jobs", params=params, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 404:
            raise AdapterError(f"iCIMS career site '{host}' has no /api/jobs endpoint (404)")
        resp.raise_for_status()
        try:
            data = resp.json()
            raw_jobs = data["jobs"]
        except (ValueError, KeyError) as exc:
            raise AdapterError(f"Unexpected iCIMS response shape: {exc}") from exc

        if not raw_jobs:
            break
        for j in raw_jobs:
            d = j.get("data", j)
            jobs.append(Job(
                id=str(d.get("slug", d.get("id", ""))),
                title=d.get("title", ""),
                company=company,
                location=d.get("full_location", ""),
                url=d.get("apply_url", f"https://{host}/jobs/{d.get('slug', '')}"),
                source="icims",
                posted_at=d.get("posted_date"),
                description=strip_html(d.get("description", "")),
            ))
            if len(jobs) >= max_results:
                break
        page += 1
        if len(raw_jobs) < page_size:
            break
    return jobs


ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "workday": fetch_workday,
    "oracle_hcm": fetch_oracle_hcm,
    "successfactors": fetch_successfactors,
    "icims": fetch_icims,
    "smartrecruiters": fetch_smartrecruiters,
}


def fetch_jobs(entry: dict, *, max_results: int = 60,
                session: Optional[requests.Session] = None) -> list[Job]:
    ats = entry.get("ats")
    adapter = ADAPTERS.get(ats)
    if adapter is None:
        raise AdapterError(f"Unknown ATS type: {ats!r}")
    return adapter(entry, max_results=max_results, session=session)


# --------------------------------------------------------------------------
# detect: turn a pasted careers-page / job-board URL into a watchlist entry
# --------------------------------------------------------------------------

def detect_ats(url: str) -> Optional[dict]:
    """Best-effort detection of ATS type + config from a URL the user pastes.

    Returns a dict with an ``"ats"`` key and whatever fields that adapter
    needs, or ``None`` if the URL doesn't match a known ATS pattern.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc
    path = parsed.path
    qs = parse_qs(parsed.query)

    if "greenhouse.io" in host:
        # boards.greenhouse.io/<slug>, job-boards.greenhouse.io/<slug>,
        # or boards-api.greenhouse.io/v1/boards/<slug>/jobs
        parts = [p for p in path.split("/") if p]
        if "boards" in parts:
            idx = parts.index("boards")
            if idx + 1 < len(parts):
                return {"ats": "greenhouse", "board": parts[idx + 1]}
        if parts:
            return {"ats": "greenhouse", "board": parts[0]}
        return None

    if "lever.co" in host:
        parts = [p for p in path.split("/") if p]
        if "postings" in parts:
            idx = parts.index("postings")
            if idx + 1 < len(parts):
                return {"ats": "lever", "board": parts[idx + 1]}
        if parts:
            return {"ats": "lever", "board": parts[0]}
        return None

    if "myworkdayjobs.com" in host:
        tenant = host.split(".")[0]
        parts = [p for p in path.split("/") if p]
        # path looks like /en-US/<site>/job/... or /<site>/job/...
        site = None
        for i, p in enumerate(parts):
            if p == "job" and i > 0:
                site = parts[i - 1]
                break
        if site is None and parts:
            site = parts[-1] if parts[-1].lower() not in ("job",) else None
        if site is None:
            return {"ats": "workday", "host": host, "tenant": tenant}
        return {"ats": "workday", "host": host, "tenant": tenant, "site": site}

    if "oraclecloud.com" in host and "CandidateExperience" in path:
        parts = [p for p in path.split("/") if p]
        site = None
        if "sites" in parts:
            idx = parts.index("sites")
            if idx + 1 < len(parts):
                site = parts[idx + 1]
        return {"ats": "oracle_hcm", "host": host, "site": site}

    if "successfactors" in host or "sapsf.com" in host:
        entry: dict = {"ats": "successfactors", "host": host}
        if "company" in qs:
            entry["company_id"] = qs["company"][0]
        return entry

    if "icims.com" in host:
        return {"ats": "icims", "host": host}

    if "smartrecruiters.com" in host:
        parts = [p for p in path.split("/") if p]
        if parts:
            return {"ats": "smartrecruiters", "company": parts[0]}
        return None

    return None
