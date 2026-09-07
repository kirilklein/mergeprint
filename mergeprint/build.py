"""Inline raw.json + config + holidays into template.html -> out/index.html.

Usage: python3 -m mergeprint.build [--raw raw.json] [--out
out/index.html] [--anonymize-repos]
                                     [--public-only] [--exclude-repo GLOB
...] [--config FILE]

All aggregation happens in the page itself, so holidays, timezone and
days off can be
changed in the browser without rebuilding. Only PR-level timestamps,
sizes and repo names
are inlined; never titles, bodies or URLs.
"""

import argparse
import datetime as dt
import json
import os
from html import escape
from pathlib import Path

from .settings import add_repo_args, cli_config, repo_filter

D = os.path.dirname(os.path.abspath(__file__))
DEMO_URL = "https://kirilklein.github.io/mergeprint/"
DEMO_IMAGE = f"{DEMO_URL}screenshot.png"
DEMO_DESCRIPTION = (
    "Private, local-first GitHub pull request analytics for throughput, "
    "backlog, merge time, PR size, and engineering trends."
)
DEMO_IMAGE_ALT = (
    "Mergeprint dashboard showing synthetic GitHub pull request trends"
)


def demo_head():
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "Mergeprint",
            "url": DEMO_URL,
            "description": DEMO_DESCRIPTION,
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Linux, macOS, Windows",
            "softwareRequirements": "Python 3.9 or newer and GitHub CLI",
            "downloadUrl": "https://pypi.org/project/mergeprint/",
            "codeRepository": "https://github.com/kirilklein/mergeprint",
            "license": "https://opensource.org/license/mit",
            "image": DEMO_IMAGE,
            "offers": {"@type": "Offer", "price": 0, "priceCurrency": "USD"},
        },
        separators=(",", ":"),
    )
    return f"""<meta name="description" content="{DEMO_DESCRIPTION}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{DEMO_URL}">
<link rel="sitemap" type="application/xml" href="{DEMO_URL}sitemap.xml">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Mergeprint">
<meta property="og:title" content="Mergeprint — Private GitHub PR analytics">
<meta property="og:description" content="{DEMO_DESCRIPTION}">
<meta property="og:url" content="{DEMO_URL}">
<meta property="og:image" content="{DEMO_IMAGE}">
<meta property="og:image:width" content="1440">
<meta property="og:image:height" content="1080">
<meta property="og:image:alt" content="{DEMO_IMAGE_ALT}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Mergeprint — Private GitHub PR analytics">
<meta name="twitter:description" content="{DEMO_DESCRIPTION}">
<meta name="twitter:image" content="{DEMO_IMAGE}">
<script type="application/ld+json">{structured_data}</script>"""


def demo_intro():
    return """<aside class="product-card" aria-labelledby="about-mergeprint">
      <div>
        <span class="eyebrow">OPEN-SOURCE GITHUB ANALYTICS</span>
        <h2 id="about-mergeprint">
          Understand your pull request history without sending it to
          another service.
        </h2>
        <p>
          Mergeprint uses the GitHub CLI to build a private, self-contained
          HTML report on your computer. Explore PR throughput, backlog,
          merge time, sizes, repository activity, and period-over-period
          trends.
        </p>
        <div class="product-actions">
          <code>uvx mergeprint</code>
          <a href="https://github.com/kirilklein/mergeprint">
            View source and documentation →
          </a>
        </div>
      </div>
      <ul>
        <li>Private repositories supported</li>
        <li>No analytics or dashboard account</li>
        <li>One portable HTML report</li>
        <li>Synthetic data in this live demo</li>
      </ul>
    </aside>"""


def main(argv=None):
    cfg = cli_config(argv)
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--raw", default="raw.json")
    ap.add_argument("--out", default="out/index.html")
    ap.add_argument(
        "--anonymize-repos",
        action="store_true",
        help="replace repository names with repo-1, repo-2, ...",
    )
    ap.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    add_repo_args(ap, cfg)
    a = ap.parse_args(argv)
    raw = json.loads(Path(a.raw).read_text(encoding="utf-8"))
    keep = repo_filter(a, raw.get("private", []))

    loc = {
        (repo, pr["number"]): pr
        for repo, rows in raw["loc"].items()
        for pr in rows
    }
    repos, prs = [], []
    for line in raw["prs"]:
        num, created, closed, merged, repo = line.split("\t")
        if not keep(repo):
            continue
        if repo not in repos:
            repos.append(repo)
        size_data = loc.get((repo, int(num)))
        size = (
            [
                size_data["additions"],
                size_data["deletions"],
                size_data["changedFiles"],
            ]
            if size_data
            else None
        )
        prs.append(
            [created, closed, merged, repos.index(repo), size, int(num)]
        )
    issues = []
    for line in raw["issues"]:
        _, created, _, _, repo = line.split("\t")
        if keep(repo):
            if repo not in repos:
                repos.append(repo)
            issues.append([created, repos.index(repo)])
    loc_idx = [repos.index(r) for r in raw["loc"] if r in repos]
    if a.anonymize_repos:
        repos = [f"repo-{i + 1}" for i in range(len(repos))]

    data = {
        "account": raw["account"],
        "start": raw["start"],
        "end": raw["end"],
        "repos": repos,
        "prs": prs,
        "locRepos": loc_idx,
        "issues": issues,
        "backlogComplete": raw.get("backlog_complete", False),
        "collectedAt": raw.get("collected_at"),
        "anonymized": a.anonymize_repos,
        "bigPr": cfg["big_pr"],
        "settings": {
            "country": cfg["country"],
            "timezone": cfg["timezone"],
            "holidays": cfg["holidays"],
            "offDays": cfg["off_days"],
            "events": cfg["events"],
        },
        "holidays": json.loads(
            Path(D, "holidays.json").read_text(encoding="utf-8")
        ),
    }

    blob = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")

    def fmt(value):
        date = dt.date.fromisoformat(value)
        return f"{date.day} {date:%b %Y}"

    page_title = (
        "Mergeprint — Private GitHub pull request analytics"
        if a.demo
        else f"{escape(data['account'])} · Mergeprint"
    )
    html = (
        Path(D, "template.html")
        .read_text(encoding="utf-8")
        .replace("__PAGE_TITLE__", page_title)
        .replace("__SEO_HEAD__", demo_head() if a.demo else "")
        .replace("__PRODUCT_INTRO__", demo_intro() if a.demo else "")
        .replace("__ACCOUNT__", escape(data["account"]))
        .replace("__RANGE__", f"{fmt(raw['start'])} - {fmt(raw['end'])}")
        .replace("__DATA__", blob)
    )
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    Path(a.out).write_text(html, encoding="utf-8")
    print(
        f"wrote {a.out}: {len(prs)} PRs, "
        f"{len(data['issues'])} issues, {len(repos)} repos"
    )


if __name__ == "__main__":
    main()
