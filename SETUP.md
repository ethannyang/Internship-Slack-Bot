# Internship Slack Bot — Setup

Checks [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
every 6 hours and posts any new listings as replies in a Slack thread — one thread per category
(currently **Software Engineering** and **Product Management**). Runs for free on GitHub Actions —
no server needed.

> **Consulting and Marketing:** this repo only tracks Software Engineering, Product Management,
> Data Science/AI/ML, Quantitative Finance, and Hardware Engineering — it doesn't have consulting
> or marketing listings. If you find a source for those, the bot's structure makes it easy to add
> as a second scraper posting into the same channel; just ask and I'll wire it in.

## 1. Create the Slack app

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**.
2. Name it (e.g. "Internship Bot"), pick your free workspace.
3. Left sidebar → **OAuth & Permissions** → under **Scopes → Bot Token Scopes**, add `chat:write`.
4. Scroll up → **Install to Workspace** → Allow.
5. Copy the **Bot User OAuth Token** (starts `xoxb-`). Keep it secret.

## 2. Get your channel ID

1. In Slack, create or pick the channel to post into (e.g. `#internships`).
2. Invite the bot: in the channel, type `/invite @Internship Bot`.
3. Right-click the channel name → **View channel details** → the Channel ID is at the bottom
   (starts with `C`).

## 3. Push this folder to a GitHub repo

1. Create a new repo on GitHub (public or private — private is fine, Actions is still free for
   reasonable usage).
2. Push the contents of this `pm_internship_bot` folder to it (the workflow file must end up at
   `.github/workflows/pm-internships.yml` in the repo root — if you push this whole folder as the
   repo root, that's already correct).

```
git init
git add .
git commit -m "Internship bot"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

## 4. Add secrets

In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.

- `SLACK_BOT_TOKEN` — the `xoxb-...` token from step 1.
- `SLACK_CHANNEL_ID` — the channel ID from step 2.

## 5. Test it

**Actions** tab → **Post new PM internships to Slack** → **Run workflow** (this uses the
`workflow_dispatch` trigger, so you don't have to wait for the schedule). Check the run logs, then
check Slack — you should see two parent messages ("Summer 2027 Software Engineering Internships"
and "Summer 2027 Product Management Internships"), each with every currently listed role in that
category posted as a thread reply. After that, only new postings will show up.

## How it works

- `scraper.py` fetches the README once, then for each entry in `CATEGORIES` pulls out that
  section's table and parses each row.
- `state.json` tracks, per category, which listings have already been posted (by a hash of
  company + role + location + link) and the Slack timestamp of that category's thread parent. The
  workflow commits this file back to the repo after each run so state persists between runs.
- The included GitHub Actions workflow runs the script every 6 hours. Edit the `cron` line in
  `.github/workflows/pm-internships.yml` to change frequency (cron times are UTC).

## Customizing

- **Add/remove a category**: edit the `CATEGORIES` list at the top of `scraper.py`. A few more are
  already commented out there (Data Science/AI/ML, Quantitative Finance, Hardware Engineering) —
  uncomment to enable, and add a matching empty entry under `"categories"` in `state.json`.
- **Test without posting to Slack**: run `DRY_RUN=1 python scraper.py` locally — it prints new
  listings instead of posting them.
- **Free-tier note**: GitHub Actions gives 2,000 free minutes/month on public repos (unlimited) and
  private repos; this job takes a few seconds per run, so frequency isn't a real constraint.
