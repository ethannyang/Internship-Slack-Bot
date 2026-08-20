#!/usr/bin/env python3
"""
Internship Slack Bot
---------------------
Scrapes selected category sections of SimplifyJobs/Summer2027-Internships
(README.md) and posts any new listings as thread replies under one running
Slack message per category (so e.g. "Software Engineering" and "Product
Management" each get their own thread in the same channel).

Designed to run unattended on a schedule (see .github/workflows/pm-internships.yml).

Environment variables required:
  SLACK_BOT_TOKEN     Slack bot token (xoxb-...) with chat:write scope
  SLACK_CHANNEL_ID    Channel ID to post into (e.g. C0123456789)

State (posted listing IDs + each category's thread timestamp) is kept in
state.json, which the GitHub Actions workflow commits back to the repo
after every run so the bot remembers what it has already posted.

Note: this repo only tracks Software Engineering, Product Management,
Data Science/AI/ML, Quantitative Finance, and Hardware Engineering. It does
not have Consulting or Marketing sections - those would need a different
source.
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
import urllib.error

README_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Add/remove entries here to change which categories the bot tracks.
# 'heading' must match (case-insensitively, as a substring) the '## ' heading
# text in the README for that section.
CATEGORIES = [
    {
        "slug": "software_engineering",
        "heading": "Software Engineering Internship Roles",
        "parent_text": ":computer: *Summer 2027 Software Engineering Internships* — new postings are added to this thread as they appear in [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships).",
    },
    {
        "slug": "product_management",
        "heading": "Product Management Internship Roles",
        "parent_text": ":briefcase: *Summer 2027 Product Management Internships* — new postings are added to this thread as they appear in [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships).",
    },
    # Other categories available in this repo, if you want to add them later:
    # {"slug": "data_science_ai_ml", "heading": "Data Science, AI & Machine Learning Internship Roles", "parent_text": ":robot_face: *Summer 2027 Data Science / AI / ML Internships* — new postings are added to this thread."},
    # {"slug": "quant_finance", "heading": "Quantitative Finance Internship Roles", "parent_text": ":chart_with_upwards_trend: *Summer 2027 Quantitative Finance Internships* — new postings are added to this thread."},
    # {"slug": "hardware_engineering", "heading": "Hardware Engineering Internship Roles", "parent_text": ":wrench: *Summer 2027 Hardware Engineering Internships* — new postings are added to this thread."},
]


def fetch_readme() -> str:
    req = urllib.request.Request(README_URL, headers={"User-Agent": "internship-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def extract_section(readme: str, heading: str) -> str:
    """Return the markdown table block under the given '## ' heading, up to the next '## ' heading."""
    lines = readme.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("## ") and heading.lower() in line.lower():
            start = i + 1
            break
    if start is None:
        raise RuntimeError(f"Could not find section heading containing {heading!r}")

    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("## "):
            end = i
            break

    return "\n".join(lines[start:end])


ROW_RE = re.compile(r"^\|(.+)\|\s*$")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
COMPANY_RE = re.compile(r"\*\*\[([^\]]+)\]\(([^)]+)\)\*\*")
APPLY_RE = re.compile(r"\[!\[Apply\]\([^)]*\)\]\(([^)]+)\)")


def split_row(row: str):
    """Split a markdown table row into cells, respecting the leading/trailing pipes."""
    m = ROW_RE.match(row.strip())
    if not m:
        return None
    # Naive split on unescaped pipes (table cells in this README don't contain literal pipes)
    return [c.strip() for c in m.group(1).split("|")]


def parse_listings(section_md: str):
    listings = []
    last_company = None

    for raw_line in section_md.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        # skip header / separator rows
        if line.startswith("| ---") or re.match(r"^\|[\s-]+\|", line):
            continue
        cells = split_row(line)
        if not cells or len(cells) < 5:
            continue
        company_cell, role_cell, location_cell, application_cell, age_cell = cells[:5]

        if company_cell.strip() in ("Company", ""):
            continue

        if "↳" in company_cell:
            company = last_company
        else:
            cm = COMPANY_RE.search(company_cell)
            company = cm.group(1) if cm else re.sub(r"[*_🔥]", "", company_cell).strip()
            last_company = company

        if not company:
            continue

        role = re.sub(r"\s+", " ", role_cell).strip()

        apply_match = APPLY_RE.search(application_cell)
        if apply_match:
            link = apply_match.group(1)
        else:
            # fall back to first link in the cell (covers any format change)
            lm = LINK_RE.search(application_cell)
            link = lm.group(2) if lm else None

        if not link:
            # No application link usually means the role is closed - skip it
            continue

        location = re.sub(r"\s+", " ", location_cell).strip()
        age = age_cell.strip()

        uid = hashlib.sha256(f"{company}|{role}|{location}|{link}".encode("utf-8")).hexdigest()[:16]

        listings.append(
            {
                "id": uid,
                "company": company,
                "role": role,
                "location": location,
                "link": link,
                "age": age,
            }
        )

    return listings


def default_state():
    return {"categories": {c["slug"]: {"posted_ids": [], "thread_ts": None} for c in CATEGORIES}}


def load_state():
    state = default_state()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            saved = json.load(f)
        if "categories" in saved:
            for slug, cat_state in saved["categories"].items():
                state["categories"].setdefault(slug, {"posted_ids": [], "thread_ts": None})
                state["categories"][slug].update(cat_state)
        elif "posted_ids" in saved:
            # Legacy single-category format from an earlier version of this script.
            # Assume it was tracking Product Management and migrate it forward.
            state["categories"].setdefault("product_management", {"posted_ids": [], "thread_ts": None})
            state["categories"]["product_management"]["posted_ids"] = saved.get("posted_ids", [])
            state["categories"]["product_management"]["thread_ts"] = saved.get("thread_ts")
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def slack_api(method: str, payload: dict, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Slack API error from {method}: {result}")
    return result


def ensure_thread_parent(cat_state: dict, parent_text: str, token: str, channel: str) -> str:
    if cat_state.get("thread_ts"):
        return cat_state["thread_ts"]
    result = slack_api(
        "chat.postMessage",
        {"channel": channel, "text": parent_text},
        token,
    )
    cat_state["thread_ts"] = result["ts"]
    return cat_state["thread_ts"]


def format_listing(listing: dict) -> str:
    return (
        f"*<{listing['link']}|{listing['company']} — {listing['role']}>*\n"
        f"{listing['location']}"
    )


def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    dry_run = os.environ.get("DRY_RUN") == "1"

    if not dry_run and (not token or not channel):
        print("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID must be set (or set DRY_RUN=1).", file=sys.stderr)
        sys.exit(1)

    readme = fetch_readme()
    state = load_state()
    total_new = 0

    for cat in CATEGORIES:
        slug = cat["slug"]
        section = extract_section(readme, cat["heading"])
        listings = parse_listings(section)

        cat_state = state["categories"][slug]
        posted_ids = set(cat_state.get("posted_ids", []))
        new_listings = [l for l in listings if l["id"] not in posted_ids]

        print(f"[{slug}] Found {len(listings)} current listings, {len(new_listings)} new.")

        if not new_listings:
            continue

        if dry_run:
            for l in new_listings:
                print(f"--- [{slug}] ---")
                print(format_listing(l))
            continue

        thread_ts = ensure_thread_parent(cat_state, cat["parent_text"], token, channel)

        for listing in reversed(new_listings):  # oldest-looking first
            slack_api(
                "chat.postMessage",
                {
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "text": format_listing(listing),
                    "unfurl_links": False,
                },
                token,
            )
            posted_ids.add(listing["id"])

        cat_state["posted_ids"] = list(posted_ids)
        total_new += len(new_listings)
        print(f"[{slug}] Posted {len(new_listings)} new listing(s) to thread {thread_ts}.")

    if not dry_run:
        save_state(state)

    if total_new == 0:
        print("No new listings across any tracked category.")


if __name__ == "__main__":
    main()
