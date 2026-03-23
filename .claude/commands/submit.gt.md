Lint, test, create a Graphite PR, merge, and announce to Discord #cogents.

**Announce at start:** "Submitting via Graphite: sync, test, submit, merge, announce"

## Steps

1. Run `git status` to check for uncommitted changes
   - If there are uncommitted changes, run `uv run ruff check src/` first, then stage and commit with a descriptive message
2. Run `gt sync -f` to sync with remote and clean up merged branches
3. If not already on a feature branch (i.e. on `main`), create one:
   - Run `gt create -a -m "<short description of changes>"` to create a new Graphite branch with all changes
   - If already on a non-main branch, just ensure changes are committed
4. Run `uv run pytest tests/ -q` to execute unit tests
   - **If tests fail AND the same tests fail on main:** The failures are pre-existing. Fix them first in a separate branch, merge that fix via this same `/submit.gt` process (recursive), then rebase your original branch on top of the now-fixed main and continue.
   - If tests fail and they're from your changes: stop and show the failures. Do NOT submit broken code. Ask the user how to proceed.
5. Run `gt submit --no-interactive --publish` to push the branch and create a PR (not draft)
   - After submit, get the PR number from `gh pr list --head $(git branch --show-current) --json number --jq '.[0].number'`
   - Update the PR body with a description following the format in AGENTS.md:
     - **Problem**: What was wrong or ambiguous
     - **Summary**: Concrete behavioral changes
     - **Testing**: Verification commands run
   - Run `gh pr edit <number> --body "..."`
6. Merge the PR:
   - Run `gh pr merge <number> --squash --auto`
   - Poll with `gh pr view <number> --json state --jq .state` every 15 seconds
   - If CI checks fail: read logs with `gh run view`, fix, commit, `gt submit --no-interactive --publish`
   - If stuck after 3 minutes, try `gh pr merge <number> --squash --admin`
   - Once `state` is `MERGED`, continue
7. Run `gt sync -f` to pull merged changes back to local main
8. Build a 1-3 sentence summary of what was merged
9. Post to Discord #cogents using `/announce`:
   - Keep under 2000 characters
   - Include PR as `[PR #N](<https://github.com/...>)` (angle brackets suppress embed)
   - If tied to an Asana task, include it as `[Task name](<https://app.asana.com/0/1213428766379931/TASK_GID>)`
   - Run: `/announce <summary>`
