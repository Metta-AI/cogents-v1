# Daily Thread Update Instructions

Cross-reference the Asana Thread Roadmap with GitHub engineering activity to produce
a business-readable report showing how each thread's goals are progressing.

## Step 1: Fetch threads from Asana

```python
project_id = "1213471594342425"

# Find the current month's section
sections = asana.list_sections(project_id)
if hasattr(sections, 'error'):
    print(f"ERROR: {sections.error}")
else:
    # Pick the section matching current month
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    month_name = now.strftime("%B")
    year = now.strftime("%Y")
    target_section = None
    for s in sections:
        if month_name in s["name"] and year in s["name"]:
            target_section = s
            break
    if not target_section and sections:
        target_section = sections[-1]  # fallback to latest section
    print(f"Using section: {target_section}")
```

Then fetch all tasks in that section with full details:

```python
tasks = asana.list_tasks(project_id, limit=100)
threads = []
for t in tasks:
    detail = asana.get_task(t.id)
    if hasattr(detail, 'error') or not detail.name.strip():
        continue
    if target_section and detail.section and target_section["name"] not in detail.section:
        continue
    # Get comments for context
    stories = asana.get_stories_for_task(t.id)
    comments = []
    if not hasattr(stories, 'error'):
        comments = [{"author": s.author, "text": s.text[:300], "date": s.created_at} for s in stories]
    threads.append({
        "name": detail.name,
        "assignee": detail.assignee,
        "notes": detail.notes[:500],
        "custom_fields": detail.custom_fields,
        "section": detail.section,
        "url": detail.url,
        "id": detail.id,
        "completed": detail.completed,
        "comments": comments,
    })
print(f"Found {len(threads)} threads")
for t in threads:
    print(f"  {t['name']} -> {t['assignee']} ({t['custom_fields'].get('Stage', '')})")
```

## Step 2: Map owners to GitHub usernames

Use the team mappings from the brief. For each thread's assignee, find their GitHub
login. If not in the table, mark as `[GitHub user unknown]` and proceed without
GitHub data for that thread.

## Step 3: Determine reporting window

Find the previous report to set the SINCE timestamp:

```python
folder_id = "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq"
recent = google_docs.list_files(folder_id, order_by="createdTime desc", limit=1)
if hasattr(recent, 'error') or not recent:
    # No previous report — use 14 days ago
    import datetime
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)).isoformat()
else:
    since = recent[0].created_time
print(f"SINCE: {since}")
```

## Step 4: Gather GitHub activity per owner

For each GitHub username, fetch from all Metta-AI repos:

```python
import datetime
repos = github.list_org_repos("Metta-AI", limit=50)
repo_names = [(r.full_name.split("/")[0], r.full_name.split("/")[1]) for r in repos] if not hasattr(repos, 'error') else []
since_dt = datetime.datetime.fromisoformat(since.replace("Z", "+00:00"))

# For each mapped owner, gather PRs and commits
for owner, github_login in owner_mappings.items():
    for repo_owner, repo_name in repo_names:
        # Merged PRs
        prs = github.list_pull_requests(repo_owner, repo_name, state="closed", limit=50)
        # Commits
        commits = github.list_commits(repo_owner, repo_name, author=github_login, since=since_dt, limit=50)
        # ... collect and filter
```

## Step 5: Correlate activity to threads

For each thread, build an activity profile. Frame activity in terms of the thread's
goal — don't just list PRs, explain what they accomplish.

- **Direct attribution**: PRs and commits by the thread's owner default to that thread.
- **Cross-thread**: If an owner has work clearly related to a different thread, note it.
- **Branch work**: Commits on unmerged branches show in-progress effort. Summarize what
  is being built, not individual commits.
- **No visible activity**: Say so plainly.

Use thread comments to enrich the narrative — look for progress updates, blockers,
scope changes, and stakeholder decisions.

## Step 6: Synthesize report

Produce the report in this structure:

```
# Daily Thread Update -- YYYY-MM-DD
**Period:** SINCE to NOW
**Threads:** N this month | M with activity | K dormant

## Key Observations
- [3-6 bullet points: cross-cutting themes, accomplishments, risks]

### THREAD_NAME
**Owner:** NAME (@github)
**Stage:** X | **Phase:** Y | **Status:** Z | **Priority:** P
**Goal:** 1-2 sentence summary from Asana notes

Since the last report, [what moved toward the goal]. Reference PRs inline
only when they add context. Weave in Asana comment context naturally.

Overall, [1-3 factual sentences on trajectory]. Flag mismatches between
Asana status and GitHub activity.

## Dormant Threads
- THREAD_NAME (Owner) — STAGE, STATUS
```

Sort active threads by activity volume (most active first). Dormant threads go at
the bottom as a compact list — no full sections.

## Step 7: Publish to Google Docs

Create a doc and format it:

```python
import datetime
today = datetime.date.today().isoformat()
doc = google_docs.create_doc(f"Daily Thread Update — {today}", "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq")
if hasattr(doc, 'error'):
    print(f"ERROR: {doc.error}")
else:
    # Insert text at index 1
    # Then apply heading styles, bullet lists, and Asana links via batch_update
    # Thread headings link to https://app.asana.com/0/1213471594342425/TASK_GID
    google_docs.batch_update(doc.id, requests)
    print(f"Published: {doc.url}")
    # Notify Discord
    discord.send("1483962779336446114", f"Daily Thread Update ready: {doc.url}")
```
