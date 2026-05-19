---
name: conga-sprint-bootstrapper
description: |
  Two-step sprint handover for one or multiple GitHub repos: cut a release branch
  from master, then bump IMAGE_TAG in all build.properties files under CICDAutomation/
  via a draft PR. Uses GitHub CLI throughout — no local clone required.
---

# Conga Sprint Bootstrapper Skill ??

## The Core Idea

Standard sprint handover is error-prone manual work. This skill is different:

1. **Branch layer** — Release branches are cut directly from the upstream master SHA via the GitHub API. No local clone, no accidental divergence.
2. **Tag bump layer** — `IMAGE_TAG` and `NUGET_TAG` are updated on your fork working branch and proposed via a cross-fork draft PR. The upstream branches page stays clean.
3. **Gate layer** — Two explicit confirmation gates separate branch creation from tag bumping. You can do Step 1 today and Step 2 tomorrow.

> GitHub API handles all file I/O; Copilot handles all orchestration.

---

## Two Steps

| Step | What happens | Where |
|------|-------------|-------|
| **Step 1** | Cut release branch from master SHA | Upstream repo (permanent) |
| **Step 2** | Bump `IMAGE_TAG` + `NUGET_TAG`, open draft PR | Your fork ? upstream PR |

---

## ? Quick Start

```
Bootstrap sprint for Asset.API, branch release-202604-2, IMAGE_TAG 202605.1
Bootstrap sprint for Renewal and Billing, branch release-202604-2, IMAGE_TAG 202605.1
```

Copilot will:
1. Pre-flight repos (check access, find files, show current tags)
2. Ask **"Proceed with Step 1?"** ? creates release branches
3. Ask **"Proceed with Step 2?"** ? bumps IMAGE_TAG, creates draft PRs

---

## Invocation Formats

```bash
# Single repo — inferred from workspace
Bootstrap sprint for <Project>, branch <branch-name>, IMAGE_TAG <new-tag>

# Single repo — explicit
Bootstrap sprint for repo <owner/repo>, project <Project>, branch <branch-name>, IMAGE_TAG <new-tag>

# Multiple repos — shared settings
Bootstrap sprint for repos <repo1> and <repo2>, branch <branch-name>, IMAGE_TAG <new-tag>

# Multiple repos — per-repo settings
Bootstrap sprint:
  repo <owner/repo1>, branch <branch1>, IMAGE_TAG <tag1>
  repo <owner/repo2>, branch <branch2>, IMAGE_TAG <tag2>
```

---

## Operations

### Pre-flight

Before executing anything:

1. Run `gh auth status` ? get fork owner (e.g. `<your-github-user>`)
2. Parse repos from input (or infer from workspace)
3. Verify each repo exists and is accessible
4. Discover all `build.properties` under `CICDAutomation/` containing `IMAGE_TAG` or `NUGET_TAG`
5. Show summary table of what will change

> Hard failures at any pre-flight check ? stop before executing anything.

---

### Step 1 — Create Release Branches

**Gate 1** — show plan and wait for approval:
```
Step 1: Create release branches
  ? congaengr/Renewal     ? release-202604-2
  ? congaengr/Asset.API   ? release-202604-2
Proceed? (yes/no)
```

For each repo after approval:
```powershell
$masterSha = gh api repos/<owner>/<repo>/git/ref/heads/master --jq '.object.sha'
gh api repos/<owner>/<repo>/git/refs -X POST -f ref="refs/heads/<branch>" -f sha="$masterSha"
```

| Result | Action |
|--------|--------|
| Branch created | `? created` |
| Branch already exists | `? already exists` — skip repo |

---

### Step 2 — Bump IMAGE_TAG via Draft PR

**Gate 2** — show plan and wait for approval:
```
Step 2: Bump IMAGE_TAG via draft PR
  ? congaengr/Renewal     202604.1 ? 202604.2  (2 files)
  ? congaengr/Asset.API   202604.1 ? 202604.2  (2 files)
Proceed? (yes/no)
```

For each repo after approval (Step 1 ? only):

**2a — Create working branch on your fork:**
```powershell
$masterSha = gh api repos/<owner>/<repo>/git/ref/heads/master --jq '.object.sha'
gh api repos/<fork-owner>/<repo>/git/refs -X POST `
  -f ref="refs/heads/chore/bump-image-tag-<tag>" -f sha="$masterSha"
```

**2b — Update each `build.properties` file on the fork:**
```powershell
$fileInfo = gh api "repos/<fork>/contents/<path>?ref=chore/bump-image-tag-<tag>" | ConvertFrom-Json
$clean    = $fileInfo.content -replace [char]10,"" -replace [char]13,""
$decoded  = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($clean))
$updated  = $decoded -replace "(?m)^IMAGE_TAG=.*", "IMAGE_TAG=<new-tag>"
$updated  = $updated -replace "(?m)^NUGET_TAG=.*",  "NUGET_TAG=<new-tag>"
$encoded  = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($updated))
$encoded | Out-File "$env:TEMP\encoded.txt" -Encoding ascii -NoNewline
$enc = Get-Content "$env:TEMP\encoded.txt" -Raw
gh api "repos/<fork>/contents/<path>" -X PUT `
  -f message="chore: bump IMAGE_TAG to <tag>" `
  -f content="$enc" -f sha="$fileInfo.sha" `
  -f branch="chore/bump-image-tag-<tag>"
```

**2c — Create cross-fork draft PR:**
```powershell
gh pr create --repo <upstream> --draft `
  --title "chore: bump IMAGE_TAG to <tag> [sprint bootstrap]" `
  --body-file "pr-body.md" --base master `
  --head "<fork-owner>:chore/bump-image-tag-<tag>"
```

---

## Constraints

- ? Always run pre-flight before any write operation
- ? Two confirmation gates — Gate 1 before branch creation, Gate 2 before tag bump
- ? Working branch lives on your fork — upstream branches page stays clean
- ? Release branch (Step 1) lives on upstream — it is permanent
- ? Use `;` not `&&` to chain commands (PowerShell 5.1 parse error)
- ? Use `--body-file` for PRs — never inline `--body`
- ? First `gh` call is slow (2–5s) — auth cache cold read; do not retry
- ? Do NOT skip pre-flight — missing `build.properties` is a hard stop
- ? Do NOT execute Step 2 for a repo where Step 1 was skipped
- ? Do NOT proceed past `no` at Gate 1 — cancel everything
- ? `no` at Gate 2 — report Step 1 results only, do not bump tags

---

## Error Handling Reference

| Situation | Action |
|-----------|--------|
| `gh auth status` fails | ? Stop: `Run: gh auth login` |
| Repo not accessible | Hard failure — stop all before executing |
| Fork not found | Hard failure: "Create fork at `https://github.com/<repo>/fork`" |
| No `build.properties` with `IMAGE_TAG` | Hard failure — stop |
| Release branch already exists (Step 1) | `? already exists` — skip repo, continue others |
| Working branch exists on fork (Step 2) | Delete & retry once |
| File update fails (Step 2) | Record `?` — continue other files |
| PR creation fails | `?` — continue to next repo |

---

## Parameters Reference

| Parameter | Required | Example | Description |
|-----------|----------|---------|-------------|
| `repo` | Optional | `congaengr/Renewal` | Inferred from workspace if omitted |
| `project` | Optional | `Renewal` | Filters `CICDAutomation/` subdirs by prefix. Omit ? update all |
| `branch-name` | ? Yes | `release-202603-2` | Release branch name |
| `IMAGE_TAG` | ? Yes | `202604.1` | New tag value for next sprint |

**Prerequisites:** GitHub CLI — `winget install GitHub.cli` ? `gh auth login`

---

## Design Philosophy

> "No local clone. GitHub API writes directly. The upstream stays clean. Your fork carries the transient work."

| Decision | Reason |
|----------|--------|
| **No local clone** | GitHub API reads/writes files directly — faster and cleaner than `git clone` ? edit ? commit ? push |
| **Fork for Step 2** | Working branch on your fork keeps the upstream branches page clean; release branch is permanent so it belongs on upstream |
| **Two gates** | You may want to cut branches today and delay the tag bump (e.g., waiting for final QA sign-off) |
| **Pre-flight first** | Discovering a missing fork or file after partial execution is harder to recover from than stopping upfront |
