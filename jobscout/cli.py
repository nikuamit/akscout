from __future__ import annotations

import os

import click
import requests
import yaml
from rich.console import Console
from rich.table import Table

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
    from pathlib import Path
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


if __name__ == "__main__":
    main()
