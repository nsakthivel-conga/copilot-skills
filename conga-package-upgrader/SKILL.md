---
name: conga-package-upgrader
---

# Conga Package Upgrader Skill

**Purpose:** Upgrade Conga.Platform.* or Conga.Revenue.* packages → build → test → draft PR.

---

## Quickstart

**Example invocations:**
- `"Upgrade platform packages"` — current repo
- `"Upgrade revenue packages"` — current repo
- `"Upgrade all Conga packages"` — current repo, runs both namespaces
- `"Upgrade platform packages to 202603.1"` — current repo, override version
- `"Upgrade all Conga packages for Conga.Revenue.Asset.API"` — single named project
- `"Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal"` — multiple projects, processed one by one
- `"Upgrade platform packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal to 202603.1"` — multi-project with version override

**Workflow:** Resolve projects → for each project: Scan → Platform: NuGet MCP latest → sprint-1 → OData resolve → patch · Revenue: conflict-check → patch → build → test → push → draft PR.

---

## Tools Required

| Tool | Purpose |
|------|---------|
| **NuGet MCP** (VS 2026 in-box) | Version discovery **and** patching for `Conga.Revenue.*` |
| **Python 3.10+** | `upgrade_packages.py` — scan, OData resolve, patch Platform, PR body |
| **.NET SDK 8.0+** | Build & test |
| **Git + gh CLI** | Branch, commit, push, PR |

**Setup NuGet MCP once:** Copilot Chat → ⚙ Tools menu → tick **NuGet**.

---

## Git Remote Layout

> ⚠️ **Fork-only rule (enforced throughout this skill):**
> All branch pushes and draft PRs **must** target your personal fork (`origin`).
> **Never push directly to `upstream` or `congaengr`.**
> Changes reach the original repo **only** via a reviewed and approved PR.

| Remote | URL pattern | Purpose |
|--------|-------------|---------|
| `origin` | `https://github.com/<your-user>/<Repo>` | Your personal fork — push here |
| `upstream` | `https://github.com/congaengr/<Repo>` | Original repo — read-only (fetch/merge only) |
| `congaengr` | `https://github.com/congaengr/<Repo>` | Alias for upstream — treat as read-only |

Verify before starting any project:
```powershell
git remote -v
# origin   https://github.com/<your-user>/<Repo> (fetch)
# origin   https://github.com/<your-user>/<Repo> (push)
# upstream https://github.com/congaengr/<Repo>   (fetch)
```
If `origin` points to `congaengr`, **stop** — correct it before proceeding:
```powershell
git remote set-url origin https://github.com/<your-user>/<Repo>
```

---

## Version Schemes

**Conga.Platform.*** — Sprint versioning
```
202604.2.3 = YYYYMM.sprint.minor
```
Target: one sprint back (applied to NuGet MCP absolute latest, not installed version):
- `202604.2` → `202604.1` · `202604.1` → `202603.2` · `202601.1` → `202512.2`

Pick highest minor in target sprint via Artifactory OData `$filter`.

**Conga.Revenue.*** — Sprint versioning (same format)
```
202605.1.7 = YYYYMM.sprint.minor
```
Target: **absolute latest** — use `NuGet_MCP_update_package_version` directly (discovers + patches in one call).

**Override:** Specify version in prompt: `"Upgrade platform packages to 202603.1"`

---

## PowerShell Rules

- Use `;` to chain commands (never `&&`)
- Use `--body-file` for PR body (never inline `@"..."@`)
- First `gh` call may be slow (auth cache)

---

## Workflow Steps

### Step 0 — Determine namespace and target projects

**Namespace:** detect from keywords (`"platform"` / `"revenue"` / `"all"`). Ask if unclear.

**Target projects:**
- If project names are provided in the prompt (e.g. `for Conga.Revenue.Asset.API, Conga.Revenue.Renewal`), resolve each to its root path:
  - Assume sibling directories under the shared source root (e.g. `C:\Users\<user>\SourceCode\<ProjectName>`)
  - If a path cannot be resolved, ask the user to confirm the full path before proceeding
- If **no projects** are specified, default to the **current workspace root** (the open solution directory)

**Processing order:** upgrades are run **one project at a time**, sequentially. Steps 1–11 repeat fully for each project before moving to the next.

> **Example resolution:**
> - Prompt: `"Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal"`
> - Resolved roots: `C:\Users\nsakthivel\SourceCode\Conga.Revenue.Asset.API`, `C:\Users\nsakthivel\SourceCode\Conga.Revenue.Renewal`
> - Process `Conga.Revenue.Asset.API` (Steps 1–11) → then `Conga.Revenue.Renewal` (Steps 1–11)

---

### Step 0.5 — Sync project to latest upstream master

> **Run once per project before scanning. Uses plain `git` CLI — no extra tools needed.**
> Skip this step only if the user explicitly says they are already on a clean, up-to-date master.

> ⚠️ **Fork-only reminder:** `origin` must be your personal fork. This step reads from `upstream` only.
> All subsequent pushes (Step 10) and PRs (Step 11) target `origin` — **never `upstream` or `congaengr`**.

```powershell
cd "<project-root>"
git remote -v                               # verify: origin = your fork, upstream = congaengr
git checkout master

# Determine sync remote: prefer 'upstream', fall back to 'congaengr'
$syncRemote = if (git remote | Select-String "^upstream$") { "upstream" } else { "congaengr" }

# Skip fetch if already fetched within the last 60 seconds (multi-project speed)
$fetchHead = Get-Item ".git\FETCH_HEAD" -ErrorAction SilentlyContinue
if (!$fetchHead -or ((Get-Date) - $fetchHead.LastWriteTime).TotalSeconds -gt 60) {
    git -c http.sslVerify=false fetch $syncRemote --quiet
}

git merge "$syncRemote/master" --ff-only --quiet
git status --short   # must be empty — no uncommitted changes before scan
```

| Check | Action if failed |
|---|---|
| `origin` points to `congaengr` | `git remote set-url origin https://github.com/<your-user>/<Repo>` |
| Not on master | `git checkout master` first |
| Local commits ahead | Stash or abort — do not upgrade on top of uncommitted work |
| `--ff-only` fails (diverged) | Run `git merge upstream/master` manually, resolve, then continue |
| `upstream` remote missing | `git remote add upstream https://github.com/congaengr/<Repo>` |

> **Why this matters:** scanning on a stale or feature branch gives wrong "current version" baselines.
> Step 4's "already at latest" check is only reliable when scanning from the true production state.

---

### Step 1 — Scan solution

> Repeat Steps 1–11 for **each project** in the resolved list (Step 0). Show progress banner with project name:
> `⏳ [Project 1/2: Conga.Revenue.Asset.API] [Step 1/11] Scanning...`

```powershell
# Both scans use the same script path — note: folder is conga-package-upgrader (not platform)
python "..\copilot-skills\conga-package-upgrader\upgrade_packages.py" scan --solution-path "<root>"
python "..\copilot-skills\conga-package-upgrader\upgrade_packages.py" scan --solution-path "<root>" --prefix "Conga.Revenue."
```
Run both when `"Upgrade all Conga packages"` is requested.
Parse JSON output: `prefix`, `current_sprint`, `packages` map.

> **Note:** Both calls read the same `.csproj` files. A future `--all-prefixes` flag would merge them into one pass.

> The script reports `"No packages found"` if `--prefix` does not match. Always pass `--prefix Conga.Revenue.` for Revenue.

---

### Step 2 — Discover versions for all packages

> **Speed tip:** Call `NuGet_MCP_get_latest_package_version` for **all** packages at once in a single
> message — Copilot issues them in parallel. Do NOT call them one by one in separate messages.

Call `NuGet_MCP_get_latest_package_version` for **every** package found in Step 1.

**Platform packages:**
1. NuGet MCP returns the absolute latest (e.g. `202604.2.11`).
2. Apply the sprint-1 rule to derive target sprint prefix:
   - `202604.2` → `202604.1` · `202604.1` → `202603.2` · `202601.1` → `202512.2`

**Revenue packages:**
1. NuGet MCP returns the absolute latest — record it per package.
2. Pass all NuGet MCP versions through `find-revenue-version` to detect **conflicting (legacy) versions**:
```powershell
# Write NuGet MCP versions to a file first (avoids PowerShell JSON quoting issues)
$nugetVersions = @{
  "Conga.Revenue.Controllers"       = "202605.1.10"
  "Conga.Revenue.Callbacks"         = "<version-from-nuget-mcp>"
  # ... one entry per package from Step 2 NuGet MCP queries
} | ConvertTo-Json
$nugetVersions | Out-File "$env:TEMP\nuget_versions.json" -Encoding utf8NoBOM
python upgrade_packages.py find-revenue-version `
  --nuget-versions-file "$env:TEMP\nuget_versions.json"
```
- If a version matches sprint format `YYYYMM.sprint.minor` (6-digit date prefix, e.g. `202412.2.3`, `202501.1.5`, `202604.2.11`) → accepted as-is (`[nuget-mcp]`), no extra HTTP call.
- If a version **does not** match sprint format (e.g. `2024011.2.2` has a 7-digit prefix) → legacy/conflicting; script falls back to OData `$orderby=Published+desc` to get the true latest by publish date (`[odata-fallback]`).

> **Why this matters:** legacy versions like `2024011.*` have a 7-digit date prefix that sorts *higher* than `202604.*` lexicographically, causing NuGet MCP to return a stale Nov-2024 build. The conflict check is **format-based** (6-digit `YYYYMM` prefix via regex), not year-based — so it works correctly across year boundaries: e.g. in January 2025 the latest packages may still be `202412.*` (prior year), which a year-prefix filter would incorrectly exclude.

> ⚠️ **Do NOT use `dotnet package search`** — stale search index, wrong versions.

---

### Step 3 — Resolve highest Platform minor in target sprint
```powershell
python upgrade_packages.py find-target-version `
  --solution-path "<root>" `
  --prefix "Conga.Platform." `
  --sprint "<target-sprint>"
```
`--solution-path` auto-discovers all `Conga.Platform.*` packages — no manual list needed.
Outputs JSON `{"PackageName": "resolved_version"}`.

**Why OData is the only reliable approach:**
`NuGet_MCP_get_latest_package_version` — absolute latest only, no prefix filter.
`NuGet_MCP_update_package_version` — rejects wildcards (`202604.1.*` → `Invalid version format`).
NuGet v3 flat container `index.json` — `405` (disabled on this Artifactory instance).
Artifactory AQL — empty results (NuGet packages not stored as Maven artifacts).
`dotnet package search` — stale search index, wrong versions.

> `Version` not `NormalizedVersion`: Artifactory v2 only exposes `Version`; `NormalizedVersion` → `400 Bad Request`.

---

### Step 4 — Compare versions and confirm with user

**Before showing the plan, compare resolved target versions (Steps 2–3) against current installed versions (Step 1 scan).**

For each package:
- If `resolved version == current version` → mark as **✅ Already at latest** — skip it
- If `resolved version != current version` → mark as **📦 Will upgrade**

**Show the combined status table:**

```
Package Upgrade Plan — Conga.Revenue.Asset.API

Platform (target sprint: 202604.2)
  📦 Authorization.Middleware   202602.1.8  →  202604.2.11
  ✅ ClientSDK                  202604.2.11     already at target

Revenue (absolute latest)
  📦 Controllers               202604.1.10 →  202605.1.10
  ✅ Common.Services            202605.1.10     already at latest
  📦 Runtime.DataProvider      202604.1.4  →  202605.1.12
```

**If ALL packages are already at latest → stop immediately:**
```
✅ All packages are already at the latest versions. No upgrade needed.
   Platform: all at 202604.2.*
   Revenue:  all at 202605.1.*
Skipping Steps 5–11 (no changes to apply, build, or PR).
```

**If some packages need upgrading** — show only the packages that will change and wait for approval:
```
3 package(s) will be upgraded, 2 already at latest — proceed? (yes/no)
```

**Gate:** Wait for explicit approval before modifying any files.

> Only packages marked 📦 are passed to Step 5. Packages marked ✅ are not touched.

---

### Step 5 — Apply all versions via NuGet MCP or patch fallback

**Primary:** Use a **single** `NuGet_MCP_update_package_version` call with all packages (Platform + Revenue combined):
```
NuGet_MCP_update_package_version(
  solutionDirectory = "<root>",
  projectPaths      = [<all non-test .csproj paths from Step 1>],
  packagesNames     = [<all Platform packages> + <all Revenue packages>],
  packagesVersions  = [<Step 3 OData versions> + <Step 2 latest versions>]
)
```

**Transitive downgrade decision rule:**
If NuGet MCP proposes a transitive dependency change where `currentVersion > proposedVersion`:
- If the downgrade is **caused by** the new `Conga.Platform.*` or `Conga.Revenue.*` package requiring it → **accept it** (the Conga package knows its dependencies)
- If the downgrade is for an unrelated system package (e.g. `System.Security.Cryptography.ProtectedData` 6.0.0→4.5.0) not required by any Conga package → **reject it** and fall back to `patch`

**Fallback:** If NuGet MCP proposes unacceptable transitive downgrades, use `patch` subcommand directly:
```powershell
python "..\copilot-skills\conga-package-upgrader\upgrade_packages.py" patch `
  --solution-path "<root>" --versions-file "$env:TEMP\all_versions.json"
python "..\copilot-skills\conga-package-upgrader\upgrade_packages.py" patch `
  --solution-path "<root>" --prefix "Conga.Revenue." --versions-file "$env:TEMP\revenue_versions.json"
```

> **Why one combined call?** NuGet MCP resolves dependencies holistically. Splitting into two calls
> can cause the second call to conflict with packages applied by the first.

---

### Step 6 — Write PR body directly

Copilot writes `upgrades/pr-body.md` directly from in-memory data (Steps 1–5) — no intermediate
`plan.json` and no `generate-pr-body` script call needed. This eliminates two file I/O operations.

Template:
```markdown
## Upgrade Conga packages: Platform <sprint> + Revenue latest

**Date:** <YYYY-MM-DD HH:MM>

---
### Packages Updated

| Project | Namespace | Package | From | To |
|---------|-----------|---------|------|----|
| `<proj>` | <ns> | `<pkg>` | `<from>` | `<to>` |
...

---
### Build & Test

- **Build:** 0 errors, <N> warnings
- **Tests:** <passed> passed, <skipped> skipped, <failed> failed

---
### Checklist
- [x] `dotnet build` passed
- [x] All unit tests passing
- [x] Only `Conga.*` versions modified
- [x] Draft PR — ready for review
```

Save to: `<copilot-skills-root>\conga-package-upgrader\upgrades\pr-body.md`

> Write this file **after** Step 8 (tests) so build + test results are included.
> `generate-pr-body` script remains as a CLI fallback if Copilot is unavailable.

---

### Step 7 — Build

> **Pre-check:** If Step 5 applied **zero changes** (all packages were already at target versions
> and confirmed at Step 4), skip Steps 7–11 entirely and report:
> ```
> ✅ No package versions were changed — build and PR skipped.
> ```

```powershell
cd "<solution-root>" ; dotnet build --no-restore
```
`--no-restore` skips redundant NuGet restore — packages already in global cache. Saves 5–15s.
Errors are blocking. Warnings are acceptable.

---

### Step 8 — Test
```powershell
cd "<solution-root>"
Remove-Item ".\TestResults" -Recurse -Force -ErrorAction SilentlyContinue
dotnet test --no-build --logger "trx;LogFileName=TestResults.trx" --results-directory .\TestResults
```
`--no-build` skips redundant rebuild — saves 1–2 min on large solutions.
Clean `TestResults\` first to prevent stale `.trx` pickup. Locate `.trx` under `TestResults\`.

---

### Step 9 — (merged into Step 6)

> PR body is now written directly by Copilot in Step 6 (after build + test results are known).
> The `generate-pr-body` script is retained as a CLI fallback only.

---

### Step 10 — Push to fork

> ⚠️ Push **only** to `origin` (your personal fork). Never push to `upstream` or `congaengr`.

```powershell
cd "<solution-root>"
git remote -v   # confirm: origin = https://github.com/<your-user>/<Repo>
git checkout -b package-upgrade-<timestamp>
git add $(git diff --name-only HEAD)   # stage only files actually modified (not TestResults, not temp files)
git commit -m "Upgrade Conga packages: Platform <sprint> + Revenue latest"
git -c http.sslVerify=false push origin HEAD
```

> **Why not `git add .`?** It stages everything — including `TestResults\`, temp files, and VS artifacts.
> `git diff --name-only HEAD` returns only the `.csproj` files that were actually patched.

> If push fails with SSL error: use `git -c http.sslVerify=false push origin HEAD` (corporate proxy cert).
> If `origin` is misconfigured, run `git remote set-url origin https://github.com/<your-user>/<Repo>` then retry.

---

### Step 11 — Create draft PR

> ⚠️ This PR flows **from your fork → original repo** (`congaengr/<Repo>`). No direct commits land on the original repo.
> `--head <your-user>:branch` = your fork · `--base master` = original repo master.
> Parse username from origin URL: `$user = (git remote get-url origin) -replace 'https://github.com/([^/]+)/.*', '$1'`

```powershell
$user = (git remote get-url origin) -replace 'https://github.com/([^/]+)/.*', '$1'
gh pr create --draft --base master `
  --head "${user}:package-upgrade-<timestamp>" `
  --title "Upgrade Conga packages: Platform <sprint> + Revenue latest" `
  --body-file "..\copilot-skills\conga-package-upgrader\upgrades\pr-body.md"
```


---

## Error Handling

| Error | Solution |
|-------|----------|
| NuGet MCP not enabled | Copilot Chat → ⚙ Tools → tick **NuGet**; requires VS 2026. See **Tools Required** fallback above for VS 2022 |
| NuGet MCP 401/403 | Enable NuGet in Copilot Tools; check Artifactory credentials |
| Package not found | Verify feed access; check package name spelling |
| Build failure | Review errors; may need code changes beyond package upgrade |
| Test failure | Review failures; assess if blocking or expected |
| `gh` auth error | Run `gh auth login` |
| Push lands on wrong remote | `git remote -v` — ensure `origin` = your fork URL, then re-push |
| PR targets wrong repo | Verify `--head <your-user>:branch`; never use `congaengr` as `--head` |

---

## Multi-Project Processing

### Project resolution
| Prompt | Resolved projects |
|--------|------------------|
| `"Upgrade all Conga packages"` | Current workspace root only |
| `"Upgrade all Conga packages for Conga.Revenue.Asset.API"` | `<source-root>\Conga.Revenue.Asset.API` |
| `"Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal"` | Both, processed sequentially |

### Sequential execution rule
Run the **complete Steps 1–11 for one project before starting the next**.
Do NOT interleave steps across projects.

### Progress banners for multi-project runs
```
⏳ [Project 1/2: Conga.Revenue.Asset.API] [Step 1/11] Scanning...
✅ [Project 1/2: Conga.Revenue.Asset.API] [Step 11/11] Draft PR created.
⏳ [Project 2/2: Conga.Revenue.Renewal] [Step 1/11] Scanning...
```

### Per-project confirmation gate (Step 4)
Show the upgrade plan for **each project separately** and wait for approval before patching that project's `.csproj` files.

### Both namespaces within a project
When `"all"` is requested for a project:
- Steps 1–4: scan both Platform + Revenue, single combined confirm gate per project
- Step 5: `NuGet_MCP_update_package_version` for Platform first, then Revenue (two calls per project)
- Steps 7–11: single combined build → test → PR per project

---

## Progress Banners

Use concise status updates:
```
⏳ [Step N/11] <action>...
✅ [Step N/11] <result>
```

Examples:
- `⏳ [Step 1/11] Scanning solution...`
- `✅ [Step 1/11] Found 3 Platform + 5 Revenue packages.`
- `⏳ [Step 7/11] Building solution — please wait...`
- `✅ [Step 7/11] Build succeeded (0 errors, 1246 warnings).`
