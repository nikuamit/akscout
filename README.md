# jobscout

A small CLI job-search agent. It scans company career pages across several
Applicant Tracking Systems (ATS), scores the results against your profile,
and can draft a tailored outreach email for a specific posting.

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

All seven have fixture-based tests under `tests/fixtures/`.

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

## Testing

```bash
pytest -q
```

Adapter tests replay trimmed, real ATS responses saved under
`tests/fixtures/`; the outreach tests use a mocked Anthropic client, so the
suite never makes a real API call or network request.

## Security

Never commit `resume.pdf`, `profiles/me.yaml`, `.env`, phone numbers, or API
keys - `.gitignore` covers the first three by default.
