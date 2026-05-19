---
name: conga-package-upgrader
description: |
  Upgrade Conga.Platform.* or Conga.Revenue.* NuGet packages across one or more
  repos: scan installed versions, resolve latest compatible targets, apply via
  NuGet MCP, build, test, push to fork, and open a draft PR — all in one flow.
  Runs one project at a time with an explicit confirmation gate before any file
  is modified.
---

# Conga Package Upgrader Skill

## The Core Idea

Manual NuGet upgrades are slow and error-prone across multiple repos. This skill is different:

1. **Version resolution layer** — Platform packages target one sprint back from absolute latest (resolved via Artifactory OData). Revenue packages always target the absolute latest sprint build. Both are discovered in parallel via NuGet MCP in a single message.
2. **Safe-apply layer** — Only `PrimaryChange` edits from NuGet MCP are written to `.csproj` files. Transitive promotions are silently discarded — exactly as Visual Studio’s NuGet UI behaves — to prevent NU1605 downgrade errors.
3. **Verification layer** — `dotnet build` and `dotnet test` run on the upgraded branch before a draft PR is opened. A confirmation gate before Step 5 ensures no files are touched without explicit approval.

> Copilot resolves, applies, and proposes; the developer reviews the diff and approves the PR.

---

## Upgrade Phases

| Phase | What happens | Tools used |
|-------|-------------|------------|
| **0 — Resolve projects** | Detect namespace, identify target repo paths | — |
| **0.5 — Sync** | Verify fork remote, detect branch, fast-forward to upstream | `git` CLI |
| **1 — Scan** | Find all Conga package references in the solution | `upgrade_packages.py scan` |
| **2 — Discover** | Fetch latest versions for every package (parallel NuGet MCP calls) | NuGet MCP |
| **3 — OData resolve** | Find highest Platform minor in target sprint via Artifactory | `upgrade_packages.py find-target-version` |
| **4 — Confirm** | Show upgrade plan, skip already-at-latest, wait for approval | — |
| **5 — Apply** | Single combined NuGet MCP call; PrimaryChange edits only | NuGet MCP |
| **6 — PR body** | Write 2-line PR body via `create_file` tool | Copilot file tool |
| **7 — Build** | `dotnet build --no-restore` | `dotnet` CLI |
| **8 — Test** | `dotnet test --no-build` | `dotnet` CLI |
| **10 — Push** | Commit + push to personal fork | `git` CLI |
| **11 — Draft PR** | Open cross-fork draft PR | `gh` CLI |

---

## ⚡ Quick Start

```
Upgrade platform packages
Upgrade revenue packages
Upgrade all Conga packages
Upgrade platform packages to 202603.1
Upgrade all Conga packages for Conga.Revenue.Asset.API
Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal
Upgrade platform packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal to 202603.1
```

**Workflow summary:** Resolve projects → for each project: Scan → Platform: NuGet MCP latest → sprint-1 → OData resolve → patch · Revenue: conflict-check → patch → build → test → push → draft PR.

---

## Prerequisites

| Tool | Purpose |
|------|---------|
| **NuGet MCP** (VS 2026 in-box) | Version discovery **and** patching for `Conga.Revenue.*` |
| **Python 3.10+** | `upgrade_packages.py` — scan, OData resolve, patch Platform, PR body |
| **.NET SDK 8.0+** | Build & test |
| **Git + gh CLI** | Branch, commit, push, PR |

**Setup NuGet MCP once:** Copilot Chat → ⚙ Tools menu → tick **NuGet**.

### Git Remote Layout

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
# upstream DISABLED                               (push)
```

If `origin` and `upstream` both point to `congaengr` — **you have no personal fork yet**. Fix before proceeding:
```powershell
# Step 1 — create your fork in browser: https://github.com/congaengr/<Repo> → Fork → <your-user>
git remote set-url origin https://github.com/<your-user>/<Repo>
git remote set-url --push upstream DISABLED
git remote set-url --push congaengr DISABLED   # only if congaengr remote exists
git remote -v  # verify
```

### Version Schemes

**Conga.Platform.*** — Sprint versioning:
```
202604.2.3 = YYYYMM.sprint.minor
```
Target: one sprint back from NuGet MCP absolute latest:
- `202604.2` → `202604.1` · `202604.1` → `202603.2` · `202601.1` → `202512.2`

Pick highest minor in target sprint via Artifactory OData `$filter`.

**Conga.Revenue.*** — Sprint versioning (same format):
```
202605.1.7 = YYYYMM.sprint.minor
```
Target: **absolute latest** — use `NuGet_MCP_update_package_version` directly.

**Override:** Specify version in prompt: `"Upgrade platform packages to 202603.1"`

---

## Operations

### Step 0 — Determine Namespace and Target Projects

**Namespace:** detect from keywords (`"platform"` / `"revenue"` / `"all"`). Ask if unclear.

**Target projects:**
- Names provided (e.g. `for Conga.Revenue.Asset.API, Conga.Revenue.Renewal`) → resolve each to its root path under the shared source root (e.g. `C:\Users\<user>\SourceCode\<ProjectName>`)
- No projects specified → default to the **current workspace root**
- Path cannot be resolved → ask the user to confirm before proceeding

**Processing order:** run the complete Steps 1–11 for one project before starting the next.

> **Example resolution:**
> - Prompt: `"Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal"`
> - Resolved roots: `C:\Users\<user>\SourceCode\Conga.Revenue.Asset.API`, `C:\Users\<user>\SourceCode\Conga.Revenue.Renewal`
> - Process `Conga.Revenue.Asset.API` (Steps 1–11) → then `Conga.Revenue.Renewal` (Steps 1–11)

---

### Step 0.5 — Verify Remotes, Detect Branch, Sync Upstream

> Run once per project before scanning. Skip only if the user says they are already on a clean, up-to-date branch.

```powershell
cd "<project-root>"

# GUARD: verify origin is NOT congaengr — hard stop if fork is missing
$originUrl = git remote get-url origin 2>$null
if (!$originUrl -or $originUrl -match "congaengr") {
    Write-Error "BLOCKED: origin = '$originUrl' points to the org repo — personal fork is missing."
    Write-Host "Fix: 1. Fork the repo in browser  2. git remote set-url origin https://github.com/<your-user>/<Repo>"
    exit 1
}
Write-Host "origin guard passed: $originUrl"

# Detect working branch — do NOT assume master
$targetBranch = git rev-parse --abbrev-ref HEAD
Write-Host "Working branch: $targetBranch"

# Determine sync remote: prefer 'upstream', fall back to 'congaengr'
$syncRemote = if (git remote | Select-String "^upstream$") { "upstream" } else { "congaengr" }

# Skip fetch if already fetched within the last 60 seconds (multi-project speed)
$fetchHead = Get-Item ".git\FETCH_HEAD" -ErrorAction SilentlyContinue
if (!$fetchHead -or ((Get-Date) - $fetchHead.LastWriteTime).TotalSeconds -gt 60) {
    git -c http.sslVerify=false fetch $syncRemote --quiet
}

git merge "$syncRemote/$targetBranch" --ff-only --quiet
git status --short   # must be empty — no uncommitted changes before scan
```

> **`$targetBranch` is set here and reused in Steps 10 and 11** — do not recompute it later.

| Check | Action if failed |
|---|---|
| `origin` = `congaengr` (guard exits) | Create personal fork; `git remote set-url origin https://github.com/<your-user>/<Repo>` |
| `origin` URL missing entirely | `git remote add origin https://github.com/<your-user>/<Repo>` |
| Local commits ahead | Stash or abort — do not upgrade on top of uncommitted work |
| `--ff-only` fails (diverged) | Run `git merge $syncRemote/$targetBranch` manually, resolve, then continue |
| `upstream` remote missing | `git remote add upstream https://github.com/congaengr/<Repo>` |

---

### Step 1 — Scan Solution

> ⏳ `[Project N/M: <name>] [Step 1/11] Scanning...`

```powershell
# Single call scans both Conga.Platform.* and Conga.Revenue.* in one pass
python "..\copilot-skills\conga-package-upgrader\upgrade_packages.py" scan \`
  --solution-path "<root>" \`
  --all-prefixes
```

Output JSON has a `namespaces` key with a sub-map per prefix, each with `current_sprint` and `packages`.

> **Fallback:** run two separate calls with `--prefix Conga.Platform.` then `--prefix Conga.Revenue.` if `--all-prefixes` output is insufficient.

---

### Step 2 — Discover Versions for All Packages

> ⚠️ **PARALLEL EXECUTION MANDATORY — enforced rule, not a tip:**
> Issue **all** `NuGet_MCP_get_latest_package_version` calls in a **single assistant message**.
> Copilot dispatches every call concurrently, reducing wait from O(N×latency) to O(latency).
> **Never call them one by one across separate messages** — sequential calls multiply latency and risk mid-run timeouts.

Call `NuGet_MCP_get_latest_package_version` for **every** package found in Step 1 — all in one message.

**Platform packages:**
1. NuGet MCP returns the absolute latest (e.g. `202604.2.11`).
2. Apply the sprint-1 rule: `202604.2` → `202604.1` · `202604.1` → `202603.2` · `202601.1` → `202512.2`

**Revenue packages:**
1. NuGet MCP returns the absolute latest — record it per package.
2. Pass all versions through `find-revenue-version` to detect conflicting (legacy) versions.

> ⚠️ **Never use PowerShell here-strings, `ConvertTo-Json | Out-File`, or `Set-Content` to write this file.**
> Use the `create_file` tool (Copilot file tool) only, with a **timestamped filename**.

Copilot writes the NuGet versions JSON to **`$env:TEMP\conga-nuget-versions-$ts.json`** using `create_file`:
```json
{
  "Conga.Revenue.Controllers":      "202605.1.10",
  "Conga.Revenue.Callbacks":        "<version-from-nuget-mcp>",
  "Conga.Revenue.Common.Services":  "202605.1.10"
}
```

Then run:
```powershell
python "$skillDir\upgrade_packages.py" find-revenue-version \`
  --nuget-versions-file "$env:TEMP\conga-nuget-versions-$ts.json" \`
  --solution-path "<root>"
```

- Version matches `YYYYMM.sprint.minor` (6-digit prefix) → accepted as-is (`[nuget-mcp]`)
- Version does NOT match (e.g. 7-digit prefix `2024011.*`) → legacy/conflicting; falls back to OData `$orderby=Published+desc` (`[odata-fallback]`)

> ⚠️ **Do NOT use `dotnet package search`** — stale search index, wrong versions.

---

### Step 3 — Resolve Highest Platform Minor in Target Sprint

```powershell
python upgrade_packages.py find-target-version \`
  --solution-path "<root>" \`
  --prefix "Conga.Platform." \`
  --sprint "<target-sprint>"
```

Outputs JSON `{"PackageName": "resolved_version"}`.

**Why OData is the only reliable approach:**

| Method | Why it fails |
|--------|-------------|
| `NuGet_MCP_get_latest_package_version` | Absolute latest only — no prefix/sprint filter |
| `NuGet_MCP_update_package_version` | Rejects wildcards (`202604.1.*` → `Invalid version format`) |
| NuGet v3 flat container `index.json` | `405` (disabled on this Artifactory instance) |
| Artifactory AQL | Empty results (NuGet packages not stored as Maven artifacts) |
| `dotnet package search` | Stale search index, wrong versions |

> Use `Version` not `NormalizedVersion`: Artifactory v2 only exposes `Version`; `NormalizedVersion` → `400 Bad Request`.

---

### Step 4 — Compare Versions and Confirm with User

Compare resolved target versions (Steps 2–3) against current installed versions (Step 1 scan).

- `resolved == current` → **✅ Already at latest** — skip
- `resolved != current` → **[UPGRADE] Will upgrade**

**Show the combined status table:**

```
Package Upgrade Plan — Conga.Revenue.Asset.API

Platform (target sprint: 202604.2)
  [UPGRADE] Authorization.Middleware   202602.1.8  →  202604.2.11
  ✅        ClientSDK                  202604.2.11     already at target

Revenue (absolute latest)
  [UPGRADE] Controllers               202604.1.10 →  202605.1.10
  ✅        Common.Services            202605.1.10     already at latest
  [UPGRADE] Runtime.DataProvider      202604.1.4  →  202605.1.12
```

**If ALL packages already at latest → stop immediately:**
```
✅ All packages are already at the latest versions. No upgrade needed.
   Platform: all at 202604.2.*    Revenue: all at 202605.1.*
Skipping Steps 5–11 (no changes to apply, build, or PR).
```

**If some packages need upgrading → wait for approval:**
```
3 package(s) will be upgraded, 2 already at latest — proceed? (yes/no)
```

> **Gate:** Wait for explicit approval before modifying any files.
> Only packages marked [UPGRADE] are passed to Step 5.

---

### Step 5 — Apply All Versions in a Single NuGet MCP Call

> ⚠️ **TRANSITIVE PROMOTION RULE — apply before writing any file:**
> - `"PrimaryChange"` → the `<PackageReference>` version you asked to change → **always apply**
> - `"PromoteTransitiveDependency"` → NuGet MCP wants to pin a transitive dep → **always skip — never write to .csproj**
>
> Applying transitive promotions causes **NU1605 downgrade build errors**.
> Visual Studio’s NuGet UI never writes transitive deps — replicate that behaviour exactly.

**Primary — one combined `NuGet_MCP_update_package_version` call (Platform + Revenue together):**
```
NuGet_MCP_update_package_version(
  solutionDirectory = "<root>",
  projectPaths      = [<all non-test .csproj paths>],
  packagesNames     = [<all Platform packages> + <all Revenue packages>],
  packagesVersions  = [<Step 3 OData versions>  + <Step 2 latest versions>]
)
```

From the returned edit plan, apply **only** edits where `role == "PrimaryChange"`. Discard every `role == "PromoteTransitiveDependency"` without writing anything.

> Even when NuGet MCP returns status `"Unresolvable"`, `requiredEdits` is still populated.
> Apply only `PrimaryChange` edits — `dotnet restore` resolves transitive deps automatically.

**Fallback — `patch` script (use if NuGet MCP times out or is unavailable):**

Copilot writes the versions JSON to **`$env:TEMP\all-versions-$ts.json`** using `create_file`:
```json
{
  "Conga.Platform.Authorization.Middleware": "202604.2.11",
  "Conga.Revenue.Controllers":               "202605.1.10"
}
```
Then apply:
```powershell
python "..\copilot-skills\conga-package-upgrader\upgrade_packages.py" patch \`
  --solution-path "<root>" \`
  --versions-file "$env:TEMP\all-versions-$ts.json"
```

---

### Step 6 — Write PR Body

**Step 6a — Compute run timestamp (once):**
```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"   # computed ONCE — reused in Steps 10 and 11
```

**Step 6b — Write `pr-body.md` using Copilot’s `create_file` tool ONLY.**

> ⚠️ **MANDATORY: always use the `create_file` tool — never PowerShell (`Set-Content`, `Out-File`, here-strings).**
> `|` characters in markdown are parsed as pipeline operators → terminal timeouts. No exceptions.
> Target path: `C:\Users\<user>\AppData\Local\Temp\conga-pr-body-$ts.md`

PR body is **exactly 2 lines**:
```markdown
Upgrade Conga packages for <RepoName>: Platform → <platform-sprint> · Revenue → latest (<revenue-sprint>).
Build: 0 errors, <N> warnings. Tests: <passed> passed, <failed> failed, <skipped> skipped.
```

If tests were not run:
```markdown
Build: 0 errors, <N> warnings. Tests: not run — verify manually.
```

> Run Step 6 **after** Step 8 (tests) so counts are accurate.
> Do not add package version tables, before/after lists, or any other content.

---

### Step 7 — Build

> **Pre-check:** If Step 5 applied zero changes, skip Steps 7–11:
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
Clean `TestResults\` first to prevent stale `.trx` pickup.

---

### Step 10 — Push to Fork

> ⚠️ Push **only** to `origin` (your personal fork). Never push to `upstream` or `congaengr`.

```powershell
cd "<solution-root>"

# Re-verify origin just before push
$originUrl = git remote get-url origin
if ($originUrl -match "congaengr") {
    Write-Error "BLOCKED: push aborted — origin still points to $originUrl"
    exit 1
}
$user = $originUrl -replace 'https://github.com/([^/]+)/.*', '$1'
if ($user -eq "congaengr") {
    Write-Error "BLOCKED: user resolved to 'congaengr' — origin is misconfigured"
    exit 1
}

git checkout -b "package-upgrade-$ts"
git add $(git diff --name-only HEAD)
git commit -m "Upgrade Conga packages: Platform <sprint> + Revenue latest"
git -c http.sslVerify=false push origin HEAD
```

> `$ts` is the same value computed in Step 6 — reuse it here for the branch name.
> `$user` and `$targetBranch` are reused in Step 11 — do not recompute them.

---

### Step 11 — Create Draft PR

> ⚠️ This PR flows **from your fork → original repo** (`congaengr/<Repo>`). No direct commits land on the original repo.

```powershell
gh pr create --draft --base $targetBranch \`
  --head "${user}:package-upgrade-$ts" \`
  --title "Upgrade Conga packages: Platform <sprint> + Revenue latest" \`
  --body-file "$env:TEMP\conga-pr-body-$ts.md"
```

> `$targetBranch` ensures the PR targets the correct base branch (e.g. `release-2025-10`) not a hardcoded `master`.

---

## Constraints

### File I/O
- ✅ Use `create_file` tool for every intermediate file (NuGet versions, plan.json, pr-body)
- ✅ Always use a timestamped filename so `create_file` never fails on a pre-existing file
- ❌ Never write JSON/text files with PowerShell here-strings, `ConvertTo-Json | Out-File`, or `Set-Content` — `|` inside JSON values is parsed as a pipeline operator → terminal timeout

### NuGet MCP
- ✅ Issue **all** `NuGet_MCP_get_latest_package_version` calls in a single assistant message (parallel)
- ✅ Apply **only** `PrimaryChange` edits from NuGet MCP plan
- ❌ Never apply `PromoteTransitiveDependency` edits — causes NU1605 downgrade errors
- ❌ Do NOT use `dotnet package search` — stale index, wrong versions

### Fork safety
- ✅ Push only to `origin` (personal fork) — never to `upstream` or `congaengr`
- ✅ Re-verify origin URL just before push (Step 10 guard)
- ❌ Never push directly to the org repo

### PowerShell Terminal
- ✅ Use `;` to chain commands — never `&&` (PS 5.1 parse error)
- ✅ Use `--body-file` for PR body — never inline `@"..."@`
- ✅ First `gh` call may be slow (auth cache) — expected; do not retry

### Progress Banners
- ✅ Print `⏳ [Project N/M: <name>] [Step N/11] <action>...` before every step
- ✅ Print `✅ [Step N/11] <result>` after every success
- ❌ Never silently proceed from one step to the next

---

## Multi-Project Processing

| Prompt | Resolved projects |
|--------|------------------|
| `"Upgrade all Conga packages"` | Current workspace root only |
| `"Upgrade all Conga packages for Conga.Revenue.Asset.API"` | `<source-root>\Conga.Revenue.Asset.API` |
| `"Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal"` | Both, processed sequentially |

- Run **complete Steps 1–11 for one project before starting the next** — do NOT interleave
- Show upgrade plan for **each project separately** and wait for approval before patching `.csproj` files
- When `"all"` is requested: single combined `NuGet_MCP_update_package_version` call with all Platform + Revenue packages together; single PR per project

---

## Error Handling Reference

| Error | Solution |
|-------|----------|
| NuGet MCP not enabled | Copilot Chat → ⚙ Tools → tick **NuGet**; requires VS 2026 |
| NuGet MCP activation failure | Transient — wait 5s and retry automatically (up to 3 attempts); restart Copilot Chat if all fail |
| NuGet MCP 401/403 | Enable NuGet in Copilot Tools; check Artifactory credentials |
| Package not found | Verify feed access; check package name spelling |
| Build failure | Review errors; may need code changes beyond package upgrade |
| Test failure | Review failures; assess if blocking or expected |
| `gh` auth error | Run `gh auth login` |
| Push lands on wrong remote | `git remote -v` — ensure `origin` = your fork URL, then re-push |
| PR targets wrong repo | Verify `--head <your-user>:branch`; never use `congaengr` as `--head` |
| Origin guard fires | Fork repo in browser → `git remote set-url origin https://github.com/<your-user>/<Repo>` → `git remote set-url --push upstream DISABLED` → rerun |
| `--base` targets wrong branch | `$targetBranch` is auto-detected in Step 0.5 — verify you are on the correct branch before running |

---

## Design Philosophy

> "Resolve versions once. Apply only what you asked for. Verify before proposing. Push only to your fork."

| Decision | Reason |
|----------|--------|
| **Parallel NuGet MCP calls** | O(latency) instead of O(N×latency) — a 10-package solution takes the same time as a 1-package solution |
| **OData for Platform sprint resolution** | No other Artifactory API reliably returns the highest minor within a specific sprint prefix — NuGet MCP and v3 flat container both fall short |
| **Skip transitive promotions** | NuGet MCP pins transitives at versions lower than the graph already requires — writing them causes NU1605; VS NuGet UI never does this |
| **create_file for all temp files** | PowerShell pipeline operator `|` appears inside JSON values and markdown tables — writing via terminal silently corrupts or times out |
| **Fork-only push with pre-push guard** | Prevents accidental force-pushes to the shared org repo; the re-verification in Step 10 catches remote drift since Step 0.5 |
| **Confirmation gate at Step 4** | Scanning and version resolution are read-only; the gate ensures no `.csproj` file is touched before the developer sees and approves the exact diff |
