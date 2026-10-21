# AKScout

A small CLI job-search agent (package name `akscout`, Python module/import
path and original CLI command both still `jobscout` - either `jobscout` or
`akscout` works on the command line after install). It scans company career pages across several
Applicant Tracking Systems (ATS), scores the results against your profile,
tracks your application pipeline locally, and can draft a tailored outreach
email for a specific posting.

Project site (pitch, architecture, live stats): **https://nikuamit.github.io/akscout/**
See [CHANGELOG.md](CHANGELOG.md) for release notes and [INTERVIEW.md](INTERVIEW.md)
for the design decisions and bugs behind this project, if you want the story
rather than just the docs.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

`.[all]` pulls in every optional extra: resume parsing (`pypdf`) and the
Anthropic SDK used by `jobscout outreach`. Install just `.` for the core
scan/match features without those.

## Set up your profile

1. (Optional) Extract a draft profile from your resume:

   ```bash
   jobscout init --resume resume.pdf -o profiles/me.yaml
   ```

   This is a best-effort heuristic extraction (email, rough years of
   experience, and any recognized skill/title keywords). Review it and merge
   anything useful into your real profile by hand - it's not meant to be
   used as-is. `resume.pdf` and `profiles/me.yaml` are both gitignored and
   should never be committed.

2. Edit a profile YAML (see `profiles/amit.yaml` for a full example) with:
   - `name`, `title`, `location`, `years_experience`, `remote_ok`, `email`
   - `target_titles`, `skills`, `locations`, `industries` - the vocabulary
     the matcher scores against
   - `weights` - how much each scoring component counts (see
     [Matching](#matching) below)
   - `watchlist` - the companies to scan, each with an `ats` type and the
     fields that adapter needs (see [Supported ATS](#supported-ats))

## Commands

### `jobscout detect <url>`

Paste any company careers-page or job-board URL and jobscout will guess the
ATS type and the config fields a watchlist entry needs:

```bash
$ jobscout detect https://boards.greenhouse.io/databricks
ats: greenhouse
board: databricks
```

Use this to build new watchlist entries, then sanity-check them with `org`
below before trusting them.

### `jobscout org <name> --profile <path>`

Fetches live jobs for a single watchlist entry by name, so you can verify a
slug/tenant/site is actually correct:

```bash
jobscout org "Walmart Global Tech" --profile profiles/amit.yaml
```

### `jobscout scan --profile <path> [--new-only] [--top N] [--out path] [--seen-path path]`

Scans every entry in the watchlist, scores every job found, writes the top
`N` (default 20) to a markdown report, and prints the same table to the
terminal. `--new-only` skips jobs already recorded in the seen-jobs cache
(`data/seen.json` by default) - the cache is updated after every run with
everything that was fetched, so the next `--new-only` run only shows
genuinely new postings.

### `jobscout outreach <job-url> [--profile <path>]`

Fetches the text of a job posting and asks Claude to draft a short,
single-paragraph recruiter outreach email tailored to it, printed to
stdout. Requires:

- `ANTHROPIC_API_KEY` in the environment (the command exits with a clear
  message if it's missing - no silent no-op).
- The `anthropic` package (`pip install 'jobscout[ai]'` or `.[all]`).

The model defaults to `claude-sonnet-5-5`; override it with the
`JOBSCOUT_MODEL` environment variable.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
jobscout outreach "https://boards.greenhouse.io/databricks/jobs/1234" \
  --profile profiles/amit.yaml
```

### `jobscout daily [--threshold N] [--top N] [--outreach-dir path] [--gmail-draft --to <email>]`

The one-command daily routine: scans for new postings, shortlists everything
scoring `--threshold` or above (default 70) into the tracker, flags
evergreen/perpetual reqs inline (`NOT-REALLY-HIRING` - see
[Not-really-hiring detection](#not-really-hiring-detection)), and - if
`ANTHROPIC_API_KEY` is set - drafts outreach for the top `--top` (default 5)
new matches. Drafts are saved as `.txt` files under `outreach/` (gitignored,
**never sent**). Pass `--gmail-draft --to <email>` to also save each one as
a Gmail draft (see [Gmail drafts](#gmail-drafts-optional) below) - that's
still just a draft sitting in your Gmail; nothing is ever sent automatically.

### `jobscout track <add|update|contact|reject|list|metrics|sweep-ghosted>`

Manages a local SQLite pipeline (`data/applications.db`, gitignored - this
is your personal job-search data and never gets committed):

```bash
jobscout track add "https://..." --title "Senior Data Engineer" --company Acme
jobscout track update 1 --stage applied
jobscout track contact 1 --name "Jane Doe" --email jane@acme.com   # you supply this yourself - nothing is looked up automatically
jobscout track reject 1 "Unfortunately we're moving forward with other candidates."
jobscout track list --stage applied
jobscout track metrics
jobscout track sweep-ghosted --stale-days 21   # flips stale applied/outreach_sent rows to 'ghosted'
```

`reject` classifies the rejection text into one of a handful of categories
(experience_mismatch, role_closed_or_filled, skills_mismatch, compensation,
location_or_remote, timing_or_priorities, no_feedback, other) using the same
keyword-heuristic style as the rest of the project - see
`jobscout/tracker.py`.

#### Not-really-hiring detection

`jobscout/tracker.is_not_really_hiring()` flags a posting as evergreen/
perpetual rather than a real open req, based only on the posting's own text:
phrases like "talent community", "general application", "future
opportunities", or a `posted_at` more than 120 days old. It's a heuristic,
not a certainty - review flagged postings yourself.

### `jobscout dashboard`

Launches a local Streamlit dashboard (`jobscout/dashboard.py`) with five
tabs: **Hiring Now** (the latest `scan` report), **Pipeline** (applications
grouped by stage), **Metrics** (response rate, interview conversion, stage
counts), **Insights** (top companies by average score, rejection-reason
breakdown), and **Follow-ups** (applications with no contact in 14+ days -
read-only, separate from the harder 21-day `sweep-ghosted` cutoff). Needs
the `dashboard` extra: `pip install 'jobscout[dashboard]'`.

### Gmail drafts (optional)

`jobscout daily --gmail-draft --to <email>` can also save an outreach email
as a Gmail draft via the Gmail API - still just a draft, still never sent.
This needs:

1. The `gmail` extra: `pip install 'jobscout[gmail]'`.
2. Your own Google Cloud OAuth client: create a project in
   [Google Cloud Console](https://console.cloud.google.com/), enable the
   Gmail API, create an OAuth client ID (type "Desktop app"), and download
   it as `credentials.json` in the repo root (gitignored).

The first run opens a browser for one-time consent and caches a token at
`data/.gmail_token.json` (also gitignored). Without this set up, `daily`
just skips the Gmail step with a warning and keeps the local `.txt` file.

## Supported ATS

| ATS | Watchlist entry fields | Notes |
|---|---|---|
| `greenhouse` | `board` | Public JSON API, no auth needed. |
| `lever` | `board` | Public JSON API, no auth needed. |
| `workday` | `host`, `tenant`, `site` | Paginates the `wday/cxs` jobs API. |
| `oracle_hcm` | `host`, `site`, `site_number` (default `CX_1`) | Oracle Fusion Cloud Recruiting's `recruitingCEJobRequisitions` REST endpoint. **Must** pass `expand=requisitionList.secondaryLocations` or the API silently omits every job - see `jobscout/sources/ats.py`. |
| `successfactors` | `host`, `company_id` (optional) | No public JSON API, so this scrapes the server-rendered `/search/` page. Fetches one page. |
| `icims` | `host`, `country` (optional) | Only works on iCIMS "Jibe" career sites that expose a public `/api/jobs` endpoint - many older iCIMS sites don't, since iCIMS has no self-service public API. |
| `smartrecruiters` | `company` (the SmartRecruiters company identifier) | Public, documented Postings API. The list endpoint doesn't expose full job description text (only the per-posting detail endpoint does, at the cost of one request per job), so matching for this ATS runs on title/location only. |
| `ashby` | `board` | Public, documented Job Board API, no auth needed - same single-response shape as Greenhouse/Lever. |

All eight have fixture-based tests under `tests/fixtures/`. Every adapter
retries 429 (respecting `Retry-After`) and 500/502/503/504 with exponential
backoff; connection-level failures (timeouts, DNS, resets) propagate
immediately so `scan`/`daily` can skip just that one company and keep going.

Greenhouse and Lever return a company's entire board in one response, so
`jobscout scan` always processes every job from those two - there's nothing
to paginate or gain by truncating. The paginated ATSs (Workday, Oracle HCM,
SmartRecruiters, iCIMS) are capped at 200 jobs per company during a scan,
because fully enumerating a large Workday tenant (800+ postings, ~40
requests) risks a server-side read timeout. A watchlist entry for one of
those can set `search_text` (e.g. `search_text: data`) to bias that capped
window toward relevant titles via the ATS's own relevance ranking, instead
of getting whatever order the API happens to return.

## Matching

`jobscout/matcher.py` scores each job 0-100 from four additive components
and one penalty, each capped by a weight in the profile's `weights` section:

- **title** - full credit if the job title contains one of your
  `target_titles`; a small bonus if it also carries a seniority word
  (senior/lead/staff/principal); cut to 30% if it looks junior/intern.
- **skills** - points per overlapping skill keyword found in the title or
  description, capped at the weight.
- **location** / **industry** - bonus points if the location matches your
  `locations` (or the job is remote and you're `remote_ok`), or the company/
  description matches your `industries`. These only apply once a job clears
  a relevance bar (a title hit, or 2+ overlapping skills) - otherwise an
  unrelated role (say, a Business Analyst posting) doesn't get a free bump
  just for being in the right city at the right kind of company.
- **experience penalty** - subtracted when the posting asks for
  substantially more years than `years_experience` (a configurable grace
  period before the penalty kicks in, scaled per year over that, capped).

Tuned defaults mean a Senior/Lead/Staff Data Engineer role in
Bengaluru/remote that uses your stack scores 70+, a generic
software-engineering role scores under 40, and a role asking for far more
years than you have gets penalised proportionally. See
`tests/test_matcher.py` for the exact rules encoded as tests.

## Automation

`.github/workflows/daily-scan.yml` runs `jobscout scan --new-only` every day
at 08:30 IST (03:00 UTC), and on manual `workflow_dispatch`. It commits
`reports/latest.md` and `data/seen.json` back to `main` only when they
changed. `ANTHROPIC_API_KEY` is read from an optional repo secret - the
workflow doesn't need it (`scan` never calls the Anthropic API) but it's
wired through in case that changes. To add it: repo **Settings -> Secrets
and variables -> Actions -> New repository secret**.

## Public site

`site/` is a static page (pitch, architecture diagram, tech stack, live
stats) deployed to GitHub Pages at https://nikuamit.github.io/akscout/ by
`.github/workflows/pages.yml` on every push to `main`, every GitHub
Release, and manual `workflow_dispatch`. The stats it fetches
(`site/data/public.json`) come from `scripts/generate_public_stats.py`,
which only ever reads real repo state (companies watched, ATS adapters
supported, test count, latest commit/release) - it never includes anything
from the tracker (applications, contacts, rejection reasons, response
rate), since that file is served publicly.

## Testing

```bash
pytest -q          # fast, fully mocked - no network calls
pytest -m live      # hits real ATS APIs - run occasionally, not in CI
```

Adapter tests replay trimmed, real ATS responses saved under
`tests/fixtures/`, plus a `responses`-mocked edge-case suite (pagination,
429/5xx retry+backoff, malformed JSON, null fields, unicode/script-tag
sanitization, duplicate ids, redirects, and more - see
`tests/test_ats_edge_cases.py`). The matcher has a `hypothesis` property
test asserting every score stays in [0, 100] across randomized inputs, plus
title/location-spelling variant coverage (`tests/test_matcher_properties.py`).
The outreach and Gmail-draft tests use mocked clients, so the suite never
makes a real API call or network request outside the explicit `live` marker.

## Security

Never commit `resume.pdf`, `profiles/me.yaml`, `.env`, `credentials.json`,
`data/applications.db`, `outreach/`, phone numbers, or API keys -
`.gitignore` covers all of these by default. `data/applications.db` and
`outreach/` hold personal job-search data (your pipeline, contacts,
rejection notes, drafted emails) and should never be committed; the public
site only ever reads `scripts/generate_public_stats.py`'s output, which
deliberately excludes all of it.
