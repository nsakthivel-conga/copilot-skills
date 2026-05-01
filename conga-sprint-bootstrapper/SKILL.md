# Conga Sprint Bootstrapper Skill 🌿

## Purpose

Two-step sprint handover for **one or multiple GitHub repos**:
1. Cut a release branch from master (e.g., `release-202604-2`)
2. Bump `IMAGE_TAG` in all `build.properties` files under `CICDAutomation/` via draft PR

Uses **GitHub CLI** throughout — no local clone required.

---

## Quickstart

```
Bootstrap sprint for Asset.API, branch release-202604-2, IMAGE_TAG 202605.1
Bootstrap sprint for Renewal and Billing, branch release-202604-2, IMAGE_TAG 202605.1
```

Copilot will:
1. Pre-flight repos (check access, find files, show current tags)
2. Ask **"Proceed with Step 1?"** → creates release branches
3. Ask **"Proceed with Step 2?"** → bumps IMAGE_TAG, creates draft PRs

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

## Parameters

| Parameter | Required | Example | Description |
|-----------|----------|---------|-------------|
| `repo` | Optional | `congaengr/Renewal` | Inferred from workspace if omitted |
| `project` | Optional | `Renewal` | Filters `CICDAutomation/` subdirs by prefix. Omit → update all. |
| `branch-name` | ✅ Yes | `release-202603-2` | Release branch name |
| `IMAGE_TAG` | ✅ Yes | `202604.1` | New tag value for next sprint |

---

## Prerequisites

| Tool | Purpose | Setup |
|------|---------|-------|
| **GitHub CLI** | All operations | `winget install GitHub.cli` → `gh auth login` |

---

## Workflow

### Phase 0 — Pre-flight

1. Check `gh auth status` → get fork owner (`nsakthivel-conga`)
2. Parse repos from input (or infer from workspace)
3. Verify each repo exists and you have a fork
4. Discover all `build.properties` under `CICDAutomation/` with `IMAGE_TAG` or `NUGET_TAG`
5. Show summary table

Hard failures → stop before executing anything.

---

### Confirmation Gates

**Gate 1** — Approve Step 1 (create release branches):
```
Step 1: Create release branches
  ✅ congaengr/Renewal     → release-202604-2
  ✅ congaengr/Asset.API   → release-202604-2
Proceed? (yes/no)
```

**Gate 2** — Approve Step 2 (bump IMAGE_TAG):
```
Step 2: Bump IMAGE_TAG via draft PR
  ✅ congaengr/Renewal     202604.1 → 202604.2  (2 files)
  ✅ congaengr/Asset.API   202604.1 → 202604.2  (2 files)
Proceed? (yes/no)
```

---

### Step 1 — Create Release Branches

For each repo:
```powershell
$masterSha = gh api repos/<owner>/<repo>/git/ref/heads/master --jq '.object.sha'
gh api repos/<owner>/<repo>/git/refs -X POST -f ref="refs/heads/<branch>" -f sha="$masterSha"
```

Branch exists → `❌ already exists` → skip repo  
Success → `✅ created`

---

### Step 2 — Bump IMAGE_TAG via GitHub API

For each repo (Step 1 ✅ only):

**2a — Create working branch on your fork:**
```powershell
$masterSha = gh api repos/<owner>/<repo>/git/ref/heads/master --jq '.object.sha'
gh api repos/<fork-owner>/<repo>/git/refs -X POST `
  -f ref="refs/heads/chore/bump-image-tag-<tag>" -f sha="$masterSha"
```

**2b — Update each `build.properties` file on the fork:**
```powershell
# Read file from fork branch
$fileInfo = gh api "repos/<fork>/contents/<path>?ref=chore/bump-image-tag-<tag>" | ConvertFrom-Json

# Decode Base64 content
$clean = $fileInfo.content -replace [char]10,"" -replace [char]13,""
$decoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($clean))

# Replace IMAGE_TAG and NUGET_TAG lines
$updated = $decoded -replace "(?m)^IMAGE_TAG=.*", "IMAGE_TAG=<new-tag>"
$updated = $updated -replace "(?m)^NUGET_TAG=.*", "NUGET_TAG=<new-tag>"

# Encode and write back to fork branch
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($updated))
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

## Error Handling

| Situation | Action |
|-----------|--------|
| `gh auth status` fails | Stop: `⛔ Run: gh auth login` |
| Repo not accessible | Hard failure — stop before executing |
| Fork not found | Hard failure: "Create fork at `https://github.com/<repo>/fork`" |
| No `build.properties` with `IMAGE_TAG` | Hard failure — stop |
| Release branch already exists (Step 1) | `❌ already exists` — skip repo |
| Working branch exists on fork (Step 2) | Delete & retry once |
| File update fails (Step 2) | Record `⚠` — continue other files |
| PR creation fails | `❌` — continue to next repo |
| `no` at Gate 1 | Cancel all |
| `no` at Gate 2 | Report Step 1 only |

---

## PowerShell Rules

- Use `;` not `&&` (PS 5.1 parse error)
- First `gh` call is slow (2–5s) — auth cache cold read
- Use `--body-file` for PRs (not inline `--body`)

---

## Key Design Decisions

### Why no local clone?
GitHub API can read/write files directly. Faster and cleaner than `git clone` → edit → commit → push.

### Why fork for Step 2?
The working branch (`chore/bump-image-tag-<tag>`) lives on **your fork** → upstream branches page stays clean. The release branch (Step 1) is on upstream because it's permanent.

### Why two confirmation gates?
You might want to create release branches but delay the IMAGE_TAG bump (e.g., waiting for final testing). Separate gates = more control.

---

## Examples

```bash
# Current repo only
Bootstrap sprint for Asset, branch release-202604-2, IMAGE_TAG 202605.1

# Explicit repo
Bootstrap sprint for repo congaengr/Conga.Revenue.Renewal, branch release-202604-2, IMAGE_TAG 202605.1

# Multiple repos, shared settings
Bootstrap sprint for Renewal and Billing, branch release-202604-2, IMAGE_TAG 202605.1

# Multiple repos, different settings
Bootstrap sprint:
  repo Renewal, branch release-202604-2, IMAGE_TAG 202605.1
  repo Billing, branch release-202603-1, IMAGE_TAG 202604.1
