# Copilot Skills

> Team-defined AI workflows for Visual Studio 2022 (`View > GitHub Copilot Chat`).
> **Setup and installation:** see `README.md` in [`congaengr/copilot-skills`](https://github.com/congaengr/copilot-skills).

## Available Skills

| Skill | Invoke With |
|-------|-------------|
| **PR Porter** 🚀 🔷 | `Port my PR #123 from master to release/2025.1 for REVREN-456` |
| **Sprint Bootstrapper** 🌿 | `Bootstrap sprint for <Project>, branch <branch-name>, IMAGE_TAG <new-tag>` · `Bootstrap sprint for repo <owner/repo>, project <Project>, branch <branch-name>, IMAGE_TAG <new-tag>` |
| **xUnit Testing** 🔷 | `Using my xUnit skill, create tests for QuoteCreationProcessor` |
| **Package Upgrader** 📦 🔷 | `Upgrade Conga Platform packages` · `Upgrade Conga Revenue packages` · `Upgrade all Conga packages` · `Upgrade all Conga packages for Conga.Revenue.Asset.API, Conga.Revenue.Renewal` |
| **Log Analyzer** 🔍 | `Analyze logs for trace abc123 in dev` · `Analyze logs for trace abc123 in dev, deployment rls04` |

> 🔷 **.NET skill** — requires a .NET SDK and a .NET solution in the workspace.

---

## Skills

### PR Porter 🚀

> ⚠️ **Copilot: Before executing, you MUST read and follow all instructions in `../copilot-skills/conga-pr-porter/SKILL.md` (relative to the workspace root). Do NOT proceed without loading that file first.**

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

> ⚠️ **Copilot: Before executing, you MUST read and follow all instructions in `../copilot-skills/conga-sprint-bootstrapper/SKILL.md` (relative to the workspace root). Do NOT proceed without loading that file first.**

Two-step sprint handover against **any GitHub repo**

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

> ⚠️ **Copilot: Before executing, you MUST read and follow all instructions in `../copilot-skills/conga-package-upgrader/SKILL.md` (relative to the workspace root). Do NOT proceed without loading that file first. Do NOT use `dotnet package search` — follow the SKILL.md workflow exactly (Steps 0–11).**

Upgrades `Conga.Platform.*` or `Conga.Revenue.*` NuGet packages
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

**Key rules:** confirms version plan per project before touching files · NuGet MCP applies versions (requires VS 2026) · build must pass · test failures require explicit consent · draft PR per project via `gh` CLI.

Full workflow, version schemes, conflict detection, multi-project rules: see `conga-package-upgrader/SKILL.md`.

---

### Log Analyzer 🔍

> ⚠️ **Copilot: Before executing, you MUST read and follow all instructions in `../copilot-skills/conga-log-analyzer/SKILL.md` (relative to the workspace root). Do NOT proceed without loading that file first.**

Downloads Grafana Loki logs by TraceId, analyzes errors/exceptions, and identifies root cause. Uses Python (stdlib only, zero dependencies).

```
Analyze logs for trace abc123 in dev
Analyze logs for trace abc123 in dev, deployment rls04
Analyze logs for trace abc123 in staging
Analyze logs with query '{service_name="platform-objectdb-api"} |= "abc123"' in dev
Analyze local logs from downloads/abc123_20260305/raw-logs.json
```

**Key rules:** provide either `--trace-id` or `--loki-query` · `dev`/`qa` auto-defaults to `rls04` deployment · outputs five files: `summary.md`, `error-analysis.md`, `performance.md`, `timeline.md`, `raw-logs.json` · requires `config.json` with Grafana API keys (copy from `config.template.json`) · Python 3.10+ (no pip packages needed).

Full parameters, output file descriptions, and setup: see `conga-log-analyzer/SKILL.md`.

---

### xUnit Testing

> ⚠️ **Copilot: Before executing, you MUST read and follow all instructions in `../copilot-skills/conga-xunit-testing/SKILL.md`

Generates xUnit tests following Conga conventions (Arrange-Act-Assert, Moq, `[Fact]`/`[Theory]`).

```
Using my xUnit skill, create tests for QuoteCreationProcessor
Using my xUnit skill, test the timeout fix
```

---

## Quick Reference

| What You Want | Say to Copilot |
|---------------|----------------|
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
| Analyze logs by TraceId | `Analyze logs for trace abc123 in dev` |
| Analyze logs with deployment filter | `Analyze logs for trace abc123 in dev, deployment rls04` |
| Analyze logs with custom Loki query | `Analyze logs with query '{service_name="platform-objectdb-api"} |= "abc123"' in dev` |
| Re-analyze previously downloaded logs | `Analyze local logs from downloads/abc123_20260305/raw-logs.json` |
