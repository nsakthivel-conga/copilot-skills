# Conga Copilot Skills

> Team-defined AI workflows for GitHub Copilot Chat in Visual Studio 2022.
> **Single reference for setup, installation, and onboarding.**
> Skills usage and quick reference: see **`COPILOT_SKILLS.md`**.

---

## Repository Structure

```
copilot-skills/
+-- README.md                  <- You are here: setup and onboarding
+-- COPILOT_SKILLS.md          <- Skill index, invocation list, and quick reference
+-- copilot-instructions.md    <- Copy to each project .github/ folder
+-- mcp.json                   <- Copy to each project .vscode/ folder (for MCP tools)
+-- conga_common.py            <- Shared Python library used by scripts
+-- conga-log-analyzer/        <- Grafana Loki log analysis
+-- conga-package-upgrader/    <- NuGet package upgrade (Platform + Revenue)
+-- conga-pr-porter/           <- PR cherry-pick and port
+-- conga-sprint-bootstrapper/ <- Release branch + IMAGE_TAG bump
+-- csharp-xunit-testing/      <- xUnit test generation
```

---

## Step 1 - One-Time Machine Setup

| Tool | Purpose | Install |
|------|---------|---------|
| **GitHub CLI** | PR creation | `winget install GitHub.cli` then `gh auth login` |
| **Python 3.10+** | Skill scripts | Verify: `python --version` |
| **Node.js** | Atlassian MCP auth | https://nodejs.org |
| **.NET 8+ SDK** | Build & test (.NET skills: PR Porter, Package Upgrader, xUnit Testing) | Verify: `dotnet --list-sdks` |
| **.NET 10 SDK** | NuGet MCP Server (Package Upgrader) | Ships with VS 2026; verify: `dotnet --list-sdks` |

```powershell
# GitHub CLI auth (once)
gh auth login    # GitHub.com -> HTTPS -> Login with a web browser
gh auth status   # confirm: "Logged in to github.com as <your-username>"

# Atlassian MCP auth (once, run in VS terminal)
npx -y mcp-remote@latest https://mcp.atlassian.com/v1/mcp
# Browser opens -> sign in -> token cached automatically
```

> **NuGet MCP** (VS 2026 only): Copilot Chat -> Tools menu -> tick **NuGet**

---

## Step 2 - Clone This Repo

```powershell
cd "C:\Users\<user>\SourceCode"
git clone https://github.com/congaengr/copilot-skills
```

---

## Step 3 - Per-Project Setup (once per repo)

> **Dynamic Linking:** To enable Copilot to find the skills dynamically, you must configure your project to point to this sibling directory.

| | Action |
|-|--------|
| 1 | Create a `copilot-skills/` folder in your project repo root (if it doesn't exist) |
| 2 | Copy `copilot-instructions.md` from this repo into the project's `.github/` folder |
| 3 | Copy `mcp.json` into the project `.vscode/` folder (if using MCP tools) |
| 4 | Open project in Visual Studio - Copilot automatically reads skills from this sibling branch! |

---

## Step 4 - Using Skills

Open Copilot Chat (`View > GitHub Copilot Chat`) and type naturally:

```
Upgrade all Conga packages
Analyze trace abc123 in dev rls04
Port my PR #123 from master to release/2025.1 for REVREN-456
Bootstrap sprint for Asset.API, branch release-202605-1, IMAGE_TAG 202605.2
Using my xUnit skill, create tests for QuoteCreationProcessor
```

Full invocation list and quick reference: **`COPILOT_SKILLS.md`** (in this repo).  
Detailed workflow per skill: **`<skill-name>/SKILL.md`** in this repo.

---

## Keeping Up to Date

Because your projects use dynamic links, you only need to pull the latest changes here. All projects instantly see the updates!

```powershell
cd "C:\Users\<user>\SourceCode\copilot-skills"
git pull origin master
```

---

## Contributing

1. Fork `congaengr/copilot-skills`
2. Create a branch: `git checkout -b improve-<skill-name>`
3. Make changes, test locally
4. Raise a draft PR to `congaengr/copilot-skills`

See each skill's `SKILL.md` for detailed workflow documentation.
