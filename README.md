# Conga Copilot Skills

> Team-defined AI workflows for GitHub Copilot Chat in Visual Studio 2022/2026.
> **Single reference for setup, installation, and onboarding.**
> Skills usage and quick reference: see **`COPILOT_SKILLS.md`**.

---

## Repository Structure

```
copilot-skills/
+-- README.md                  <- You are here: setup and onboarding
+-- COPILOT_SKILLS.md          <- Copy to each project root: skill invocations and quick reference
+-- mcp.json                   <- Copy to each project .vscode/ folder
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
| **.NET 10 SDK** | NuGet MCP Server | Ships with VS 2026; verify: `dotnet --list-sdks` |

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

| | Action |
|-|--------|
| 1 | Copy `COPILOT_SKILLS.md` into the project repo root |
| 2 | Copy `mcp.json` into the project `.vscode/` folder |
| 3 | Open project in Visual Studio - Copilot reads `COPILOT_SKILLS.md` automatically |

> **Recommended instead of copying:** Add to VS Code `settings.json` once so Copilot always reads the live file:
> ```json
> "github.copilot.chat.codeGeneration.instructions": [
>   { "file": "C:\\Users\\<user>\\SourceCode\\copilot-skills\\COPILOT_SKILLS.md" }
> ]
> ```
> No re-copy needed when skills are updated.

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

Full invocation list and quick reference: **`COPILOT_SKILLS.md`** in your project root.  
Detailed workflow per skill: **`<skill-name>/SKILL.md`** in this repo.

---

## Keeping Up to Date

```powershell
cd "C:\Users\<user>\SourceCode\copilot-skills"
git pull origin master
# If not using settings.json tip: re-copy COPILOT_SKILLS.md + mcp.json to project repos
```

---

## Contributing

1. Fork `congaengr/copilot-skills`
2. Create a branch: `git checkout -b improve-<skill-name>`
3. Make changes, test locally
4. Raise a draft PR to `congaengr/copilot-skills`

See each skill's `SKILL.md` for detailed workflow documentation.
