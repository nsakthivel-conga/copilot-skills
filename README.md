# Conga Copilot Skills

> Team-defined AI workflows for GitHub Copilot Chat in Visual Studio 2022/2026.

---

## Repository Structure

```
copilot-skills/
??? COPILOT_SKILLS.md           ? Copy into each project repo root
??? mcp.json                    ? Copy into each project's .vscode/ folder
??? conga_common.py             ? Shared Python library used by skill scripts
??? conga-log-analyzer/         ? Grafana Loki log analysis skill
??? conga-platform-upgrader/    ? NuGet package upgrade skill
??? conga-pr-porter/            ? PR cherry-pick + port skill
??? conga-sprint-bootstrapper/  ? Release branch + IMAGE_TAG bump skill
??? csharp-xunit-testing/       ? xUnit test generation skill
```

---

## One-Time Machine Setup

| Tool | Purpose | Install |
|------|---------|---------|
| **GitHub CLI** | PR creation | `winget install GitHub.cli` then `gh auth login` |
| **Python 3.10+** | Skill scripts | verify: `python --version` |
| **Node.js** | Atlassian MCP auth | https://nodejs.org |
| **.NET 10 SDK** | NuGet MCP Server | ships with VS 2026 |

**Authenticate Atlassian MCP** (once per machine):
```
npx -y mcp-remote@latest https://mcp.atlassian.com/v1/mcp
```

**Enable NuGet MCP** (VS 2026): Copilot Chat ? ? Tools ? tick **NuGet**

---

## Per-Project Setup (once per repo)

| Step | Action |
|------|--------|
| 1 | Clone this repo: `git clone https://github.com/congaengr/copilot-skills` |
| 2 | Copy `COPILOT_SKILLS.md` into the project repo root |
| 3 | Copy `mcp.json` into the project's `.vscode/` folder |
| 4 | Open the project in Visual Studio — Copilot reads `COPILOT_SKILLS.md` automatically |

> Scripts resolve paths relative to `copilot-skills/` — always run them from
> `cd "<path-to-copilot-skills>/<skill-folder>"`.

---

## Getting Updates

```powershell
cd "C:\Users\<user>\SourceCode\copilot-skills"
git pull origin master
```

Then re-copy `COPILOT_SKILLS.md` and `mcp.json` to any project repos that need the update.

---

## Contributing

1. Fork `congaengr/copilot-skills`
2. Create a branch: `git checkout -b improve-<skill-name>`
3. Make changes, test locally
4. Raise a draft PR to `congaengr/copilot-skills`

See each skill's `SKILL.md` for detailed workflow documentation.
