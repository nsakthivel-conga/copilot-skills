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

### Step 1 — Scan solution

> Repeat Steps 1–11 for **each project** in the resolved list (Step 0). Show progress banner with project name:
> `⏳ [Project 1/2: Conga.Revenue.Asset.API] [Step 1/11] Scanning...`

```powershell
cd "..\copilot-skills\conga-platform-upgrader"

# Platform packages
python upgrade_packages.py scan --solution-path "<root>"

# Revenue packages
python upgrade_packages.py scan --solution-path "<root>" --prefix "Conga.Revenue."
```
Run both when `"Upgrade all Conga packages"` is requested.
Parse JSON output: `prefix`, `current_sprint`, `packages` map.

> The script reports `"No packages found"` if `--prefix` does not match. Always pass `--prefix Conga.Revenue.` for Revenue.

---

### Step 2 — Discover versions for all packages
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

### Step 4 — Confirm with user
Show combined upgrade plan (all versions from Steps 2–3):
- **Platform** packages: current → resolved version from Step 3
- **Revenue** packages: current → absolute latest from Step 2

**Gate:** Wait for explicit approval before modifying any files.

---

### Step 5 — Apply all versions via NuGet MCP
Use `NuGet_MCP_update_package_version` for **both** Platform and Revenue — exact versions are known, no wildcards needed.

**Platform** (versions from Step 3):
```
NuGet_MCP_update_package_version(
  solutionDirectory = "<root>",
  projectPaths      = [<non-test .csproj paths from Step 1 Platform scan>],
  packagesNames     = ["Conga.Platform.Authorization.Middleware", "Conga.Platform.ClientSDK", ...],
  packagesVersions  = ["202604.1.8", "202604.1.9", ...]   <- exact versions from Step 3 OData
)
```

**Revenue** (absolute latest from Step 2):
```
NuGet_MCP_update_package_version(
  solutionDirectory = "<root>",
  projectPaths      = [<non-test .csproj paths from Step 1 Revenue scan>],
  packagesNames     = ["Conga.Revenue.Controllers", "Conga.Revenue.Common.Services", ...],
  packagesVersions  = ["<latest>", "<latest>", ...]   <- from Step 2 NuGet MCP query
)
```

> **Why NuGet MCP for Platform too?**  
> Exact versions are known after Step 3. `NuGet_MCP_update_package_version` accepts exact versions  
> and edits `.csproj` files directly — no PowerShell JSON-quoting issues, no Python script needed.

> **`patch` subcommand** in `upgrade_packages.py` remains available as a manual fallback
> if NuGet MCP is unavailable.

---

### Step 6 — Record changes for PR body
Write `upgrades/changes.json` from the before (Step 1 scan) and after (Step 5 applied) version maps:
```powershell
# Save before-versions from Step 1 scan output
# Save after-versions from Steps 2-3 resolved output
python upgrade_packages.py record-changes `
  --solution-path "<root>" `
  --prefix "Conga.Platform." `
  --before "<root>\upgrades\before_platform.json" `
  --after  "<root>\upgrades\after_platform.json" `
  --target-sprint "<sprint>"
```
Run once per namespace. Writes `upgrades/changes.json` used by `generate-pr-body`.

---

### Step 7 — Build
```powershell
cd "<solution-root>" ; dotnet build
```
Errors are blocking. Warnings are acceptable.

---

### Step 8 — Test
```powershell
dotnet test --logger "trx;LogFileName=TestResults.trx"
```
Locate `.trx` file for PR body.

---

### Step 9 — Generate PR body
```powershell
cd "..\copilot-skills\conga-platform-upgrader"
python upgrade_packages.py generate-pr-body `
  --changes-json "<root>\upgrades\changes.json" `
  --trx-path "<path-to-trx>"
```
Writes `upgrades/pr-body.md`.

---

### Step 10 — Push to fork
```powershell
cd "<solution-root>"
git checkout -b package-upgrade-<timestamp>
git add .
git commit -m "Upgrade Conga packages: Platform <sprint> + Revenue latest"
git push origin HEAD
```

---

### Step 11 — Create draft PR
```powershell
gh pr create --draft --base master `
  --head <user>:package-upgrade-<timestamp> `
  --title "Upgrade Conga packages: Platform <sprint> + Revenue latest" `
  --body-file "..\copilot-skills\conga-platform-upgrader\upgrades\pr-body.md"
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
