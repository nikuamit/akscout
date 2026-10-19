from datetime import datetime, timezone


def render_markdown(ranked: list[dict], *, title: str = "JobScout report") -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {title}",
        "",
        f"_Generated {now} - {len(ranked)} jobs_",
        "",
        "| Score | Title | Company | Location | Link |",
        "|---|---|---|---|---|",
    ]
    for r in ranked:
        job = r["job"]
        safe_title = job.title.replace("|", "-")
        lines.append(
            f"| {r['score']} | {safe_title} | {job.company} | {job.location} "
            f"| [{job.source}]({job.url}) |"
        )
    return "\n".join(lines) + "\n"
