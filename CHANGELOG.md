# Changelog

## v0.1.0 - 2026-10-21

First tagged release.

- CLI: `detect`, `org`, `scan`, `outreach`, `init`, `daily`, `track`, `dashboard`.
- 8 ATS adapters (Greenhouse, Lever, Workday, Oracle Cloud HCM, SuccessFactors,
  iCIMS, SmartRecruiters, Ashby), each with retry/backoff on 429/5xx and
  fixture-based tests against trimmed real responses.
- Scoring matcher tuned so Senior/Lead/Staff Data Engineer roles in
  Bengaluru/remote on the target stack score 70+, generic SWE roles score
  under 40, and over-demanding years-of-experience requirements are
  penalised - covered by a hypothesis property test plus title/location
  variant coverage.
- Local SQLite application tracker with stages, a keyword-based rejection
  reason classifier, an evergreen/"not-really-hiring" posting flag, and a
  stale-application ghosting sweep.
- `jobscout daily`: scan new postings, shortlist, flag evergreen reqs,
  draft outreach via Claude (saved locally, never sent; optional Gmail
  draft via the user's own OAuth credentials, also never sent).
- Local Streamlit dashboard (Hiring Now / Pipeline / Metrics / Insights /
  Follow-ups).
- Daily GitHub Action scan + CI test workflow.
