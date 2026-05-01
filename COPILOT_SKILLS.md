# Copilot Skills

> Team-defined AI workflows for Visual Studio 2022/2026 (`View > GitHub Copilot Chat`).
> **Setup and installation:** see `README.md` in [`congaengr/copilot-skills`](https://github.com/congaengr/copilot-skills).

## Available Skills

| Skill | Invoke With |
|-------|-------------|
| **Log Analyzer** ⭐ | `Analyze trace abc123 in dev rls04` |
| **PR Porter** 🚀 | `Port my PR #123 from master to release/2025.1 for REVREN-456` |
| **Sprint Bootstrapper** 🌿 | `Bootstrap sprint for <Project>, branch <branch-name>, IMAGE_TAG <new-tag>` · `Bootstrap sprint for repo <owner/repo>, project <Project>, branch <branch-name>, IMAGE_TAG <new-tag>` |
| **xUnit Testing** | `Using my xUnit skill, create tests for QuoteCreationProcessor` |
| **Package Upgrader** 📦 | `Upgrade Conga Platform packages` · `Upgrade Conga Revenue packages` · `Upgrade all Conga packages` · `Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal` |

---

## Skills

### Log Analyzer ⭐

Downloads Grafana Loki logs by TraceId and produces `summary.md`, `error-analysis.md`, `performance.md`, `timeline.md`, `raw-logs.json`.

```
Analyze trace abc123 in dev rls04
Analyze trace abc123 in dev rls04 - show error details and root cause
Analyze trace abc123 in dev rls04 - show performance analysis
Analyze the logs in downloads/abc123_20260305/raw-logs.json
```

**Terminal (if needed):**
```powershell
cd "<copilot-skills-root>\conga-log-analyzer"
python log_downloader.py --trace-id "abc123" --environment dev --deployment-env rls04
# Re-analyze a saved file:
python log_downloader.py --analyze-local "downloads/abc123_20260305/raw-logs.json"
```

Full CLI options and repo-url mappings: see `conga-log-analyzer/SKILL.md`.

---

### PR Porter 🚀

Ports a merged PR to another branch — cherry-pick → build → test → draft PR → JIRA comment.

```
Port my PR #123 from master to release/2025.1 for REVREN-456
Port my PR #123 from master to release/2025.1
Port PR https://github.com/congaengr/Conga.Revenue.Renewal/pull/123 to release/2025.1
```

**Key rules:** one porting JIRA per port · branch named after JIRA ticket · draft PR always · never modify the original JIRA ticket.

Full workflow, conflict resolution, and package-version rules: see `conga-pr-porter/SKILL.md`.

---

### Sprint Bootstrapper 🌿

Two-step sprint handover against **any GitHub repo** — handles **one or multiple repos in a single command**: cut a release branch from master, then bump `IMAGE_TAG` in **all** `build.properties` files under `CICDAutomation/` via a draft PR. Uses GitHub API throughout — no local clone required. Repos are inferred from the current workspace or provided explicitly. Pre-flights all repos before executing anything; per-repo failures are isolated so other repos continue.

```
Bootstrap sprint for repo Conga.Revenue.Asset.API project, branch name : release-202604-1, IMAGE_TAG : 202604.2
Bootstrap sprint for Renewal, branch release/2025.1, IMAGE_TAG 2025.2.0
Bootstrap sprint for repo congaengr/Conga.Revenue.Billing, project Billing, branch release/2025.1, IMAGE_TAG 2025.2.0
Bootstrap sprint for repos congaengr/Conga.Revenue.Renewal project Renewal and congaengr/Conga.Revenue.Billing project Billing, branch release/2025.1, IMAGE_TAG 2025.2.0
Bootstrap sprint:
  repo congaengr/Conga.Revenue.Renewal, project Renewal, branch release/2025.1, IMAGE_TAG 2025.2.0
  repo congaengr/Conga.Revenue.Billing, project Billing, branch release/2025.3, IMAGE_TAG 2025.4.0
```

**Key rules:** parse all repos first · pre-flight all before confirming · two consolidated confirmation gates (one per step) · per-repo failure isolation · release branches via GitHub API · IMAGE_TAG bumped in **all** `build.properties` under `CICDAutomation/` via GitHub API (no local clone needed) · always via draft PRs · never commits directly to master.

Full workflow, multi-repo input formats, confirmation gates, and error handling: see `conga-sprint-bootstrapper/SKILL.md`.

---

### Package Upgrader 📦

Upgrades `Conga.Platform.*` or `Conga.Revenue.*` NuGet packages — one or multiple projects, sequentially.
- **Platform** → sprint-1 from absolute latest (e.g. `202605.1` → target `202604.2.*-highest`), resolved via Artifactory OData
- **Revenue** → absolute latest sprint version; auto-detects legacy version conflicts (7-digit prefix e.g. `2024011.*`) and falls back to OData publish-date ordering
- **No project specified** → defaults to current workspace root
- **Named projects** → resolved as sibling directories under source root, processed one by one

```
Upgrade Conga Platform packages
Upgrade Conga Revenue packages
Upgrade all Conga packages
Upgrade all Conga packages for Conga.Revenue.Asset.API
Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal
Upgrade platform packages to 202603.1
Upgrade platform packages for REVREN-456
```

**Key rules:** confirms version plan per project before touching files · NuGet MCP applies versions (requires VS 2026; `patch` subcommand is fallback) · build must pass · test failures require explicit consent · draft PR per project via `gh` CLI.

Full workflow, version schemes, conflict detection, multi-project rules: see `conga-package-upgrader/SKILL.md`.

---

### xUnit Testing

Generates xUnit tests following Conga conventions (Arrange-Act-Assert, Moq, `[Fact]`/`[Theory]`).

```
Using my xUnit skill, create tests for QuoteCreationProcessor
Using my xUnit skill, test the timeout fix
```

---

## Quick Reference

| What You Want | Say to Copilot |
|---------------|----------------|
| Error analysis | `Analyze trace xyz in dev rls04 - show errors` |
| Performance analysis | `Analyze trace xyz in dev rls04 - show performance` |
| Re-analyze local file | `Analyze the logs in downloads/xyz_20260305/raw-logs.json` |
| Port a PR (with JIRA) | `Port my PR #123 from master to release/2025.1 for REVREN-456` |
| Port a PR (auto-clone JIRA) | `Port my PR #123 from master to release/2025.1` |
| Resume after conflict | `conflicts resolved, continue` |
| Create tests | `Using my xUnit skill, create tests for <Class>` |
| Cut release branch + bump IMAGE_TAG (current repo) | `Bootstrap sprint for <Project>, branch <release/X.Y>, IMAGE_TAG <new-tag>` |
| Cut release branch + bump IMAGE_TAG (any repo) | `Bootstrap sprint for repo <owner/repo>, project <Project>, branch <release/X.Y>, IMAGE_TAG <new-tag>` |
| Cut release branch + bump IMAGE_TAG (multiple repos) | `Bootstrap sprint for repos <owner/repo1> project <P1> and <owner/repo2> project <P2>, branch <release/X.Y>, IMAGE_TAG <new-tag>` |
| Sprint bootstrap — branch only | `Bootstrap sprint for ...` then type `no` at confirmation gate 2 |
| Async review | `Review this code against our async patterns skill` |
| Upgrade platform packages | `Upgrade Conga Platform packages` |
| Upgrade revenue packages | `Upgrade Conga Revenue packages` |
| Upgrade all Conga packages | `Upgrade all Conga packages` |
| Upgrade named project(s) | `Upgrade all Conga packages for Conga.Revenue.Asset.API` |
| Upgrade multiple projects | `Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal` |
| Upgrade with JIRA | `Upgrade platform packages for REVREN-456` |
| Upgrade to specific sprint | `Upgrade platform packages to 202603.1` |
