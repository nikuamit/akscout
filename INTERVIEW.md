# Talking about AKScout in an interview

Notes on why this exists and the real engineering decisions/bugs behind it -
written so I can talk about it fluently, not as user-facing documentation
(that's the [README](README.md)).

## The problem

Job search for a Senior/Lead Data Engineer role is mostly manual: open
twenty company career pages, search each one for "data engineer," skim
locations, repeat daily. None of that needs a human - it needs a scraper,
a scorer, and a place to track what happened after you applied. AKScout is
that, built for my own search, not a demo project.

## Architecture decisions

**Adapters over a scraper.** Every ATS (Greenhouse, Lever, Workday, Oracle
Cloud HCM, SmartRecruiters, iCIMS, SuccessFactors, Ashby) exposes either a
real public JSON API or a server-rendered page I can parse without a
headless browser. That rules out some companies (Flipkart, Swiggy, Zoho -
pure client-rendered SPAs with no public API), but it means the whole tool
has zero browser-automation dependency, runs in a few seconds per company,
and works unattended in a GitHub Action.

**Score components are additive and capped, not multiplicative.** Title,
skills, location, and industry each contribute up to a fixed weight, with
one subtractive experience-gap penalty. This was deliberate: a
multiplicative model (e.g. title_score * location_score) makes a 0 in any
one dimension zero out everything else, which is too brittle for real,
messy job postings. Additive-with-a-relevance-gate (see below) turned out
to need its own fix once I ran it against live data.

**The daily workflow is one command, not a pipeline of five.** `jobscout
daily` scans, shortlists, flags evergreen reqs, and drafts outreach in one
call because that's the actual loop I run every morning. Splitting it into
separate commands you chain yourself would be more "composable" but
slower to actually use.

## Real bugs found by testing against live data, not just unit tests

These are the ones worth describing in an interview - each came from
checking live results against reality, not from code review:

1. **A silently-truncating API cap dropped the exact jobs the tool exists
   to find.** Greenhouse/Lever return a company's *entire* board in one
   response (no pagination), but the code sliced it to the first 60
   anyway. Databricks' actual "Data Engineering" titled roles sat at
   indices 499, 500, and 652 of an 899-job board sorted roughly
   alphabetically - invisible to every scan. Fix: stop truncating a
   response that was already fully fetched.

2. **Workday's `total` field lies after page 1.** It's accurate on the
   first page of results and reports `0` on every page after that. My
   pagination loop used `offset >= total` to know when to stop, so every
   Workday company (Novartis, MSD, Takeda, Pfizer, AstraZeneca, Lilly,
   Walmart, Visa) was silently capped at exactly 2 pages (40 jobs)
   regardless of whether the tenant had 100 or 900 open roles. Fix: capture
   `total` once, from the first page only.

3. **Oracle's recruiting API drops a whole field based on an undocumented
   query param.** `recruitingCEJobRequisitions` omits `requisitionList`
   from every response unless the request also passes
   `expand=requisitionList.secondaryLocations` - with no error, just an
   empty list. Caught by noticing Uber's watchlist entry returned 0 jobs
   when it obviously has open roles.

4. **A sanitizer bug that only showed up once I wrote an adversarial test
   for it.** `strip_html` stripped tags before unescaping HTML entities. A
   literal `&lt;3` in a job description becomes a real `<` after
   unescaping, and the (greedy) tag-stripping regex then ate everything up
   to the next genuine `>` it could find - silently truncating the
   description. Fixed by unescaping first and requiring a letter right
   after `<`/`</` for something to count as a tag at all. The fix had to
   satisfy both a synthetic adversarial case *and* a real fixture
   (Greenhouse double-encodes its own HTML, so the tags only become real
   tags after one unescape pass) - getting the order of operations right
   for both at once was the actual puzzle.

5. **Location matching was too permissive for "remote."** "Remote -
   Canada" and "Remote US" were scoring as if they were open to an
   India-based candidate, because the matcher only checked for the
   substring "remote." Fixed by only crediting the location bonus for
   *open* remote (or a named local city) - a country-restricted remote
   listing for a different country now scores 0 there, not the full bonus.

6. **A relevance-gating fix that came from reading the actual output, not
   from a test failing.** Early on, a Business Analyst posting in
   Bengaluru at a fintech company was scoring right at the 40-point
   "generic role" ceiling purely from location + industry bonuses, with
   zero title or skill relevance. Fixed by gating those bonuses behind an
   actual relevance bar (a title hit, or 2+ overlapping skills) - a role
   with no real connection to the target profile doesn't get credit for
   being in the right city at the right kind of company.

7. **"Associate" isn't a universal junior signal.** The junior-title
   penalty included "associate," which is right for tech ("Associate
   Engineer") and wrong for pharma/finance, where "Associate Director" is
   a senior rung on the corporate ladder - confirmed on real Novartis and
   AstraZeneca postings. Removed it from the junior-term list rather than
   trying to special-case by industry.

8. **A profile gap, not a code bug: "BLR" matched nothing.** Writing a
   test for Bengaluru spelling variants against the real (not augmented)
   default profile showed that bare "BLR" - a common shorthand in Indian
   job postings - didn't match any configured location, while every other
   spelling did. Fixed in data (`profiles/amit.yaml`), not code, since the
   matcher's substring approach was already correct; the vocabulary was
   incomplete.

## Testing philosophy

Fixture-based tests replay *trimmed real responses*, not hand-written
approximations of what an API "probably" returns - several of the bugs
above only existed because of a quirk in the real response shape
(Greenhouse's double-encoded HTML, Oracle's missing-unless-you-ask-for-it
field, Workday's second-page `total`). A hypothesis property test
(`score_job` always returns `[0, 100]`) exists because the scoring function
combines several independently-evolving weighted components, which is
exactly the kind of code where "I eyeballed a few examples" stops being
convincing. Live checks are real but marked `@pytest.mark.live` and
excluded from the default run - useful for occasionally re-verifying an
ATS hasn't changed shape, not for CI.

## What I'd do differently with more time

- A headless-browser adapter (Playwright) would unlock Flipkart, Swiggy,
  PhonePe, Zoho - all client-rendered SPAs with no public API. Deliberately
  out of scope so far: it's a materially heavier dependency (a real browser
  binary) and a less reliable scraping surface than a documented API.
- The "not-really-hiring" heuristic is simple keyword/age matching. A
  company that reposts the same req every 90 days to dodge that check
  would slip through - a sturdier signal would track req-ID churn across
  scans, not just posting age.
- SmartRecruiters' list endpoint doesn't expose description text without
  an extra per-job request, so matching for that ATS runs on title/location
  only - a real precision gap I chose not to pay for with N+1 requests per
  scan.
