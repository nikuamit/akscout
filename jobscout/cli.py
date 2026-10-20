from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import click
import requests
import yaml
from rich.console import Console
from rich.table import Table

from jobscout import tracker
from jobscout.profile import load_profile, save_profile, find_watchlist_entry, ProfileError
from jobscout.sources.ats import fetch_jobs, detect_ats, AdapterError
from jobscout.matcher import rank_jobs
from jobscout.report import render_markdown
from jobscout.storage import load_seen, save_seen, job_key

console = Console()
err_console = Console(stderr=True)


@click.group()
def main():
    """jobscout - scan ATS boards, score matches against your profile, draft outreach."""


@main.command()
@click.option("--resume", "resume_path", required=True, type=click.Path(exists=True),
              help="Path to your resume PDF.")
@click.option("-o", "--output", "output_path", required=True, type=click.Path(),
              help="Where to write the draft profile YAML.")
def init(resume_path, output_path):
    """Extract a draft profile (skills, titles, years) from a resume PDF."""
    try:
        from jobscout.resume import extract_profile
    except ImportError:
        raise click.ClickException(
            "Resume parsing needs the 'resume' extra. Install with: pip install 'jobscout[resume]'"
        )
    profile = extract_profile(resume_path)
    save_profile(output_path, profile)
    console.print(f"[green]Wrote draft profile to {output_path}[/green]")
    console.print(
        "[yellow]This is a best-effort extraction - review it and merge what's "
        "useful into your real profile.[/yellow]"
    )


@main.command()
@click.argument("url")
def detect(url):
    """Detect the ATS type and config fields for a pasted careers-page URL."""
    result = detect_ats(url)
    if result is None:
        console.print(f"[red]Could not detect a known ATS for {url}[/red]")
        raise SystemExit(1)
    console.print(yaml.safe_dump(result, sort_keys=False))


@main.command()
@click.argument("name")
@click.option("--profile", "profile_path", default="profiles/amit.yaml", show_default=True,
              type=click.Path(exists=True))
@click.option("--limit", default=10, show_default=True, help="Max jobs to print.")
def org(name, profile_path, limit):
    """Fetch and print jobs for one watchlist entry, to verify it's wired up correctly."""
    profile = load_profile(profile_path)
    entry = find_watchlist_entry(profile, name)
    if entry is None:
        console.print(f"[red]No watchlist entry named {name!r} in {profile_path}[/red]")
        raise SystemExit(1)
    try:
        jobs = fetch_jobs(entry)
    except (AdapterError, requests.RequestException) as exc:
        console.print(f"[red]FAILED ({entry.get('ats')}): {exc}[/red]")
        raise SystemExit(1)

    console.print(f"[bold]{entry['name']}[/bold] ({entry.get('ats')}): {len(jobs)} jobs")
    for j in jobs[:limit]:
        console.print(f"  - {j.title}  [dim]{j.location}[/dim]  {j.url}")


# Greenhouse/Lever always return their full board in one response, so this
# only actually limits the paginated ATSs (Workday, Oracle HCM,
# SmartRecruiters, iCIMS). 200 is a deliberate balance: large Workday
# tenants (800+ postings) will still miss some jobs past that window, but
# live-testing showed fully enumerating one (Novartis, ~43 requests) is slow
# enough to risk a server-side read timeout - see each entry's `search_text`
# in profiles/amit.yaml for how relevant titles get surfaced within it.
COLLECT_MAX_RESULTS = 200


def _collect_jobs(profile: dict) -> list:
    all_jobs = []
    for entry in profile.get("watchlist", []):
        try:
            all_jobs.extend(fetch_jobs(entry, max_results=COLLECT_MAX_RESULTS))
        except (AdapterError, requests.RequestException) as exc:
            # One company's site timing out, 500ing, or failing DNS
            # shouldn't take down the whole scan - warn and keep going.
            err_console.print(f"[yellow]warning: {entry.get('name')}: {exc}[/yellow]")
    return all_jobs


@main.command()
@click.option("--profile", "profile_path", default="profiles/amit.yaml", show_default=True,
              type=click.Path(exists=True))
@click.option("--new-only", is_flag=True, help="Only include jobs not seen in a previous scan.")
@click.option("--top", default=20, show_default=True, help="Number of jobs to keep in the report.")
@click.option("--out", "out_path", default="reports/latest.md", show_default=True,
              type=click.Path())
@click.option("--seen-path", default="data/seen.json", show_default=True, type=click.Path())
def scan(profile_path, new_only, top, out_path, seen_path):
    """Scan every watchlist entry, score the results, and write a markdown report."""
    profile = load_profile(profile_path)
    jobs = _collect_jobs(profile)

    seen = load_seen(seen_path)
    if new_only:
        jobs = [j for j in jobs if job_key(j) not in seen]

    ranked = rank_jobs(jobs, profile)[:top]

    report = render_markdown(ranked, title=f"JobScout report for {profile.get('name', '')}")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(report)

    # `jobs` holds everything fetched this run (already filtered to unseen
    # ones when --new-only is set), so unioning with the old seen set is
    # enough to mark them all seen going forward.
    save_seen(seen | {job_key(j) for j in jobs}, seen_path)

    table = Table(title=f"Top {len(ranked)} matches")
    table.add_column("Score", justify="right")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Location")
    for r in ranked:
        j = r["job"]
        table.add_row(str(r["score"]), j.title, j.company, j.location)
    console.print(table)
    console.print(f"[green]Wrote {len(ranked)} ranked jobs to {out_path}[/green]")


@main.command()
@click.argument("job_url")
@click.option("--profile", "profile_path", default="profiles/amit.yaml", show_default=True,
              type=click.Path(exists=True))
def outreach(job_url, profile_path):
    """Draft a short recruiter outreach email tailored to a job posting."""
    from jobscout.outreach import fetch_job_description, draft_email, OutreachError

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print(
            "[red]ANTHROPIC_API_KEY is not set. Export it and try again, e.g.:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...[/red]"
        )
        raise SystemExit(1)

    profile = load_profile(profile_path)
    try:
        description = fetch_job_description(job_url)
        email = draft_email(description, profile, api_key=api_key)
    except OutreachError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    click.echo(email)


# --------------------------------------------------------------------------
# track: a local SQLite application pipeline (data/applications.db)
# --------------------------------------------------------------------------

DB_OPTION = click.option("--db", "db_path", default=tracker.DEFAULT_DB_PATH, show_default=True,
                          type=click.Path())


@main.group()
def track():
    """Manage your local application tracker (data/applications.db)."""


@track.command("add")
@click.argument("job_url")
@click.option("--title", default="(unknown title)", show_default=True)
@click.option("--company", default="(unknown company)", show_default=True)
@click.option("--source", default="manual", show_default=True)
@click.option("--score", type=int, default=None)
@click.option("--stage", default="shortlisted", show_default=True,
              type=click.Choice(tracker.STAGES))
@DB_OPTION
def track_add(job_url, title, company, source, score, stage, db_path):
    """Add a job to the tracker by URL (title/company default to placeholders -
    pass --title/--company, or add straight from `scan`/`daily` results)."""
    from jobscout.models import Job
    job = Job(id=job_url, title=title, company=company, location="", url=job_url, source=source)
    conn = tracker.connect(db_path)
    app_id = tracker.add_application(conn, job, score=score, stage=stage)
    console.print(f"[green]#{app_id}[/green] {company} - {title} ({stage})")


@track.command("update")
@click.argument("app_id", type=int)
@click.option("--stage", required=True, type=click.Choice(tracker.STAGES))
@click.option("--note", default=None)
@DB_OPTION
def track_update(app_id, stage, note, db_path):
    """Move an application to a new stage."""
    conn = tracker.connect(db_path)
    tracker.update_stage(conn, app_id, stage, note=note)
    console.print(f"[green]#{app_id} -> {stage}[/green]")


@track.command("contact")
@click.argument("app_id", type=int)
@click.option("--name", default=None)
@click.option("--email", default=None)
@click.option("--linkedin", default=None)
@DB_OPTION
def track_contact(app_id, name, email, linkedin, db_path):
    """Record a TA/recruiter contact you've sourced yourself - this never
    looks anyone up automatically."""
    conn = tracker.connect(db_path)
    tracker.set_contact(conn, app_id, name=name, email=email, linkedin=linkedin)
    console.print(f"[green]Updated contact for #{app_id}[/green]")


@track.command("reject")
@click.argument("app_id", type=int)
@click.argument("raw_reason")
@DB_OPTION
def track_reject(app_id, raw_reason, db_path):
    """Record a rejection and classify the reason."""
    conn = tracker.connect(db_path)
    category = tracker.set_rejection(conn, app_id, raw_reason)
    console.print(f"[green]#{app_id} rejected - classified as '{category}'[/green]")


@track.command("sweep-ghosted")
@click.option("--stale-days", default=21, show_default=True)
@DB_OPTION
def track_sweep(stale_days, db_path):
    """Flip anything with no contact in --stale-days to 'ghosted'."""
    conn = tracker.connect(db_path)
    changed = tracker.mark_stale_as_ghosted(conn, stale_days=stale_days)
    console.print(f"[green]Marked {len(changed)} stale application(s) as ghosted[/green]")
    for row in changed:
        console.print(f"  #{row['id']} {row['company']} - {row['title']}")


@track.command("list")
@click.option("--stage", default=None, type=click.Choice(tracker.STAGES))
@DB_OPTION
def track_list(stage, db_path):
    """List tracked applications."""
    conn = tracker.connect(db_path)
    rows = tracker.list_applications(conn, stage=stage)
    table = Table(title=f"Applications{f' ({stage})' if stage else ''}")
    for col in ("ID", "Stage", "Score", "Company", "Title", "TA Contact", "Flag"):
        table.add_column(col)
    for r in rows:
        flag = "NOT-REALLY-HIRING" if r["not_really_hiring"] else ""
        table.add_row(str(r["id"]), r["stage"], str(r["score"] or ""), r["company"], r["title"],
                      r["ta_name"] or "", flag)
    console.print(table)


@track.command("metrics")
@DB_OPTION
def track_metrics(db_path):
    """Print pipeline metrics: response rate, interview conversion, stage counts."""
    conn = tracker.connect(db_path)
    console.print(yaml.safe_dump(tracker.metrics(conn), sort_keys=False))


# --------------------------------------------------------------------------
# daily: the one-command daily routine
# --------------------------------------------------------------------------

@main.command()
@click.option("--profile", "profile_path", default="profiles/amit.yaml", show_default=True,
              type=click.Path(exists=True))
@click.option("--threshold", default=70, show_default=True,
              help="Minimum score to shortlist.")
@click.option("--top", default=5, show_default=True,
              help="Max number of new matches to draft outreach for.")
@click.option("--outreach-dir", default="outreach", show_default=True, type=click.Path())
@click.option("--gmail-draft", is_flag=True,
              help="Also save each outreach email as a Gmail draft (never sent). "
                   "Needs the [gmail] extra and your own OAuth credentials.")
@click.option("--to", "gmail_to", default=None,
              help="Recipient address for --gmail-draft (required if that flag is set).")
@click.option("--seen-path", default="data/seen.json", show_default=True, type=click.Path())
@DB_OPTION
def daily(profile_path, threshold, top, outreach_dir, gmail_draft, gmail_to, seen_path, db_path):
    """Scan new postings, shortlist strong matches, flag evergreen reqs,
    and draft outreach (saved locally - nothing is ever sent) for the best
    new ones."""
    profile = load_profile(profile_path)
    jobs = _collect_jobs(profile)

    seen = load_seen(seen_path)
    new_jobs = [j for j in jobs if job_key(j) not in seen]
    ranked = rank_jobs(new_jobs, profile)
    shortlisted = [r for r in ranked if r["score"] >= threshold]

    conn = tracker.connect(db_path)
    for r in shortlisted:
        job = r["job"]
        app_id = tracker.add_application(conn, job, score=r["score"])
        flag_str = " [yellow]NOT-REALLY-HIRING[/yellow]" if tracker.is_not_really_hiring(job) else ""
        console.print(f"#{app_id} [bold]{r['score']}[/bold] {job.company} - {job.title}{flag_str}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    drafted = 0
    if not api_key:
        err_console.print("[yellow]ANTHROPIC_API_KEY not set - skipping outreach drafts.[/yellow]")
    else:
        from jobscout.outreach import draft_email, OutreachError
        Path(outreach_dir).mkdir(parents=True, exist_ok=True)
        for r in shortlisted[:top]:
            job = r["job"]
            if tracker.is_not_really_hiring(job):
                continue  # don't spend a draft on an evergreen/perpetual req
            try:
                email = draft_email(job.description or job.title, profile, api_key=api_key)
            except OutreachError as exc:
                err_console.print(f"[yellow]outreach draft failed for {job.company}: {exc}[/yellow]")
                continue
            safe_company = re.sub(r"[^a-zA-Z0-9]+", "-", job.company.strip()).strip("-").lower()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            out_path = Path(outreach_dir) / f"{today}-{safe_company or 'company'}.txt"
            out_path.write_text(email)
            drafted += 1

            if gmail_draft:
                if not gmail_to:
                    err_console.print("[yellow]--gmail-draft needs --to <email>; "
                                       "saved locally only.[/yellow]")
                else:
                    from jobscout.gmail_draft import create_draft, GmailDraftError
                    try:
                        create_draft(to=gmail_to, subject=f"Interested in {job.title} at {job.company}",
                                     body=email)
                    except GmailDraftError as exc:
                        err_console.print(f"[yellow]Gmail draft failed, kept local file only: "
                                           f"{exc}[/yellow]")

    save_seen(seen | {job_key(j) for j in jobs}, seen_path)
    console.print(f"[green]{len(shortlisted)} shortlisted, {drafted} outreach draft(s) "
                  f"saved to {outreach_dir}/[/green]")


@main.command()
def dashboard():
    """Launch the local Streamlit dashboard (Hiring Now/Pipeline/Metrics/
    Insights/Follow-ups). Needs the 'dashboard' extra:
    pip install 'jobscout[dashboard]'."""
    import shutil
    import subprocess

    if shutil.which("streamlit") is None:
        raise click.ClickException(
            "Streamlit isn't installed. Install it with: pip install 'jobscout[dashboard]'"
        )
    dashboard_path = Path(__file__).parent / "dashboard.py"
    subprocess.run(["streamlit", "run", str(dashboard_path)], check=False)


if __name__ == "__main__":
    main()
