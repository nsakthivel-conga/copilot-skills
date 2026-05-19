---
name: conga-pr-porter
description: |
  Port a merged GitHub PR from one branch to another with full JIRA tracking,
  conflict resolution, build/test verification, and draft PR creation.
  Cherry-picks commits onto a new porting branch, clones the JIRA ticket,
  runs dotnet build + test, then opens a draft PR and comments the link on JIRA.
---

# Conga PR Porter Skill

## The Core Idea

Manual PR porting is repetitive and error-prone. This skill is different:

1. **JIRA layer** — A porting ticket is always cloned from the original, linked via “is cloned by”, and updated with the draft PR link. The original ticket is never touched.
2. **Cherry-pick layer** — Exact commit SHAs are cherry-picked one at a time onto a branch created from the target’s latest HEAD. File scope is verified after every commit. Package versions are compared and conflicts are surfaced before they cause build failures.
3. **Verification layer** — `dotnet build` and `dotnet test` run on the ported branch. Failures are surfaced with structured alerts and options (auto-fix / manual fix / abort) before a draft PR is created.

> Copilot drives every step; the developer resolves conflicts, approves package decisions, and reviews the draft PR.

---

## Port Phases

| Phase | What happens | Tools used |
|-------|-------------|------------|
| **1 — Validate** | Fetch PR details, resolve or clone JIRA ticket | `gh` CLI, JIRA MCP |
| **2 — Branch** | Create porting branch from target HEAD, push to fork | `git` CLI |
| **3 — Port** | Cherry-pick commits, verify scope, resolve package conflicts | `git` CLI |
| **4 — Build & Test** | `dotnet build` then `dotnet test`, parse TRX results | `dotnet` CLI |
| **5 — Failures** | Structured alerts for build/test failures with fix options | IDE / `dotnet` CLI |
| **6 — Draft PR** | Generate PR body from test results, open draft PR | `python`, `gh` CLI |
| **7 — JIRA** | Post draft PR link as comment on porting ticket | JIRA MCP |
| **8 — Report** | Print full summary with package version log | — |

---

## ⚡ Quick Start

```
Port my PR #123 from master to release/2025.1 for REVREN-456
Port my PR #123 from master to release/2025.1
Port PR https://github.com/org/repo/pull/123 to release/2025.1
```

Resume phrases after manual intervention:

| Situation | Say to Copilot |
|-----------|---------------|
| Conflict resolved | `conflicts resolved, continue` |
| Push done manually | `push done, continue` |
| Build fixed manually | `build fixed, continue` |
| Tests fixed manually | `tests fixed, continue` |

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Git** | 2.30+ | Branch creation, cherry-pick |
| **`gh` CLI** | latest | PR read/create |
| **Python** | 3.10+ | TRX parsing, PR body generation |
| **`conga_common.py`** | — | Shared utilities (TRX parsing, file I/O) |
| **.NET SDK** | 8.0+ | `dotnet build` and `dotnet test` |
| **JIRA MCP** | — | Ticket validation, cloning, commenting |

> All JIRA MCP calls require a `cloudId`. Retrieve it once with `getAccessibleAtlassianResources` and reuse throughout.

---

## Operations

### Step 1 — Validate Inputs & Resolve JIRA Ticket

> ⏳ `[Step 1/8] Fetching PR #<N> from GitHub...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json title,body,commits,mergeCommit,headRefName,baseRefName,state
```

> After result: ✅ `[Step 1/8] PR details fetched — title: "<title>", state: <state>.`
> Then: ⏳ `[Step 1/8] Resolving JIRA ticket...` before any JIRA MCP call.

#### JIRA Ticket Decision Tree

```
User provides a PORTING JIRA ticket?
│
├─ YES ▶ @jira get_issue <ticket>
│          ├─ Exists ▶ Use as porting ticket ▶ Step 2
│          └─ Not found ▶ "Ticket not found. Verify number."
│
└─ NO ▶ Extract ORIGINAL JIRA from PR title/branch (pattern: [A-Z][A-Z0-9]+-\d+)
          ├─ Found ▶ @jira get_issue <original>
          │           Prompt user:
          │           "(a) Create porting ticket automatically
          │            (b) Provide existing porting ticket number"
          │
          │  ├─ (a) CREATE
          │  │    @jira get_issue <original>
          │  │      fields: summary, description, issuetype, project, priority,
          │  │              components, labels, fixVersions
          │  │
          │  │    Compose new ticket description:
          │  │
          │  │      ## [Port] Porting to `<branch>`
          │  │      | Field        | Value        |
          │  │      |--------------|--------------|
          │  │      | Original     | <ticket>     |
          │  │      | Original PR  | #<number>    |
          │  │      | Target       | <branch>     |
          │  │
          │  │      ## Description
          │  │      <original description — copied verbatim>
          │  │
          │  │      ## Acceptance Criteria
          │  │      <customfield_15890 — omit if empty>
          │  │
          │  │      ## Steps to Reproduce
          │  │      <customfield_10106 — omit if empty>
          │  │
          │  │      ## Design Description
          │  │      <customfield_15701 — omit if empty>
          │  │
          │  │    @jira create_issue
          │  │      summary:     "Porting to <branch> - <original summary>"
          │  │      issueType, project, priority, components, labels: same as original
          │  │      description: composed above
          │  │      + copy any required fields that caused create to fail
          │  │        (e.g. customfield_11501, customfield_15716, customfield_15867)
          │  │
          │  │    @jira link_issues <new-ticket> "is cloned by" <original-ticket>
          │  │    ▶ Use new ticket as porting ticket
          │  │
          │  └─ (b) PROVIDE ▶ Wait ▶ @jira get_issue ▶ validate ▶ use
          │
          └─ Not found ▶ "Could not find JIRA ticket in PR. Please provide one."
                          ▶ Wait ▶ validate ▶ continue
```

---

### Step 2 — Create Branch

> ⏳ `[Step 2/8] Detecting remote configuration...`

```powershell
git remote -v   # detect fork vs direct-clone
```

> ✅ `[Step 2/8] Remotes detected — workflow: <fork|direct-clone>.`

```powershell
# Fork workflow (origin=fork, upstream=org)
git fetch upstream <target-branch>
git checkout -b <jira-ticket> upstream/<target-branch>
git push -u origin <jira-ticket>

# Direct-clone workflow (origin=org only)
git fetch origin <target-branch>
git checkout -b <jira-ticket> origin/<target-branch>
git push -u origin <jira-ticket>
```

#### Push Failure Alert

If `git push` fails — **STOP and show:**

```
⚠️  PUSH FAILED — Action Required
────────────────────────────────────────────────────────────
Branch : <jira-ticket>
Remote : <upstream/origin>
Error  : <exact error message>

  [401/403 Authentication]   → gh auth login → retry push → "push done, continue"
  [Branch protection]        → verify fork branch not protected → "push done, continue"
  [Network / timeout]        → check VPN → retry push → "push done, continue"
  [Branch already exists]    → git push upstream <ticket> --force-with-lease → "push done, continue"
────────────────────────────────────────────────────────────
```

---

### Step 3 — Port Changes

#### 3.0 List and Confirm Files

> ⏳ `[Step 3/8] Fetching list of files changed in PR #<N>...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json files --jq '.files[].path'
```

Show file list to user — wait for confirmation before proceeding. Stop if any file is unexpected.

#### 3.1 Cherry-Pick Commits

> ⏳ `[Step 3/8] Fetching commit SHAs for PR #<N>...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json commits --jq '.commits[].oid'
```

```bash
git cherry-pick <sha-1>   # one at a time
git cherry-pick <sha-2>
```

#### 3.2 Conflict Detection

After each cherry-pick:

```bash
git status --short
git diff --name-only --diff-filter=U
```

If conflicts detected — **STOP and show:**

```
⚠️  CHERRY-PICK CONFLICT — Action Required
────────────────────────────────────────────────────────────
Commit : <sha>     Branch : <porting-branch>
Conflict in: <file1>, <file2>

  1. Open conflicting file(s) in Visual Studio / VS Code
  2. Resolve conflict markers (<<<<<<< / ======= / >>>>>>>)
  3. git add <file>
  4. git diff --check   (verify no markers remain)
  5. Say: "conflicts resolved, continue"

⛔ Do NOT run git cherry-pick --continue yourself — Copilot will do it.
────────────────────────────────────────────────────────────
```

After `conflicts resolved, continue`:

```bash
git diff --check
git cherry-pick --continue --no-edit
git status --short
```

#### 3.3 Verify File Scope

```bash
git diff --name-only origin/<target-branch>...HEAD
```

Files outside the original PR → STOP: `⚠️ SCOPE WARNING: Unexpected files modified: <list>`
Options: `(a) Revert and continue  (b) Abort`

#### 3.4 Package Version Conflict Detection

For each `.csproj` changed in the PR, after cherry-pick:

1. Diff to find modified `PackageReference` lines
2. Compare PR version vs target version vs major version of each

```
For each changed PackageReference:
│
├─ Major versions DIFFER (PR major ≠ target major)
│    → STOP and prompt:
│       ⚠️  Package: <name>  PR: <version> (major: x)  Target: <version> (major: y)
│       (a) Skip — keep target  (b) Provide correct version  (c) Abort
│    (a) → git add <file>; git commit --amend --no-edit
│    (b) → apply version; git add <file>; git commit --amend --no-edit
│
├─ Same major AND target version HIGHER than PR version
│    → Keep target version (do NOT downgrade)
│    → Log: "⚠️ <name>: kept target <target-version> (PR had <pr-version>, same major)"
│
└─ Same major AND PR version HIGHER or EQUAL
     → Apply PR version
     → Log: "✅ <name>: <target-version> → <pr-version> (same major, applied)"
```

Collect all package log lines — include in Step 8 report.

---

### Step 4 — Build and Test

> ⏳ `[Step 4/8] Building solution — this typically takes 1–3 minutes, please wait...`

```bash
dotnet build --no-restore 2>&1
dotnet test --no-build --logger "trx;LogFileName=port-test-results.trx" --results-directory ./TestResults 2>&1
```

> ✅ `[Step 4/8] Build succeeded.`
> ✅ `[Step 4/8] Tests complete — <passed> passed, <failed> failed, <skipped> skipped.`

---

### Step 5 — Handle Failures

#### Build Failure Alert

```
⚠️  BUILD FAILED — Action Required
────────────────────────────────────────────────────────────
Branch: <porting-branch>   Errors: <N>
<first 10 error lines>

  (a) Let Copilot attempt to fix the build errors
  (b) Fix manually in IDE → "build fixed, continue"
  (c) Abort the port
────────────────────────────────────────────────────────────
```

- **(a)** Copilot edits files, re-runs build. If still failing after 2 attempts → escalate to (b).
- **(b)** Wait for `build fixed, continue` → re-run `dotnet build` to verify.
- **(c)** `git cherry-pick --abort` then `git checkout <original-branch>`.

#### Test Failure Alert

```
⚠️  TESTS FAILED — Action Required
────────────────────────────────────────────────────────────
Branch: <porting-branch>   Results: <passed> passed, <failed> FAILED, <skipped> skipped

Failed tests:
  ✗ <TestClass.TestMethod1>  Error: <first 120 chars>
  ✗ <TestClass.TestMethod2>  Error: <first 120 chars>

  (a) Let Copilot attempt to fix the failing tests
  (b) Fix manually in IDE → "tests fixed, continue"
  (c) Create draft PR anyway (tests failing — reviewers notified)
  (d) Abort the port
────────────────────────────────────────────────────────────
```

To get full failure details:
```bash
cd "..\ copilot-skills\conga-pr-porter"
python pr_porter.py parse-trx --file <repo-root>/TestResults/port-test-results.trx
```

After any fix → always re-run both build and tests before proceeding.

---

### Step 6 — Create Draft PR

> ⏳ `[Step 6/8] Generating PR body from test results...`

```powershell
cd "..\ copilot-skills\conga-pr-porter"
python pr_porter.py generate-pr-body \`
  --original-pr <number> \`
  --original-repo <org>/<repo> \`
  --target-branch <branch> \`
  --jira-ticket <porting-ticket> \`
  --test-results <repo-root>/TestResults/port-test-results.trx \`
  --commits "<sha1>,<sha2>,<sha3>" \`
  --jira-base-url https://conga.atlassian.net
```

> ⏳ `[Step 6/8] Creating draft PR on GitHub...`

```powershell
cd <repo-root>
gh pr create \`
  --repo <org>/<repo> \`
  --base <target-branch> \`
  --head <fork>:<jira-ticket> \`
  --title "<porting-ticket>: Porting to <target-branch> - <original-title>" \`
  --body-file "..\ copilot-skills\conga-pr-porter/pr-body.md" \`
  --draft
```

> `pr-body.md` is written to the skill directory — always use full relative path.
> Use backtick \` for line continuation in PowerShell — not `\`.

---

### Step 7 — Update JIRA

> ⏳ `[Step 7/8] Adding PR link comment to JIRA ticket <porting-ticket>...`

```
@jira add_comment <porting-ticket> "Draft PR created: <pr-url>"
```

> ✅ `[Step 7/8] JIRA ticket <porting-ticket> updated with PR link.`

---

### Step 8 — Report Results

```
Port complete!
  JIRA Ticket : <porting-ticket> (cloned from <original>)
  Branch      : <porting-ticket>
  Draft PR    : <pr-url>
  Target      : <target-branch>
  Tests       : <N>/<total> passed
  Commits     : <N> cherry-picked

Package Version Summary:
  ✅ <package>: <pr-version> applied  (same major, PR version is higher)
  ⚠️  <package>: kept <target-version>  ← target was higher (same major — no downgrade)
  ⚠️  <package>: <resolved-version>  ← major version conflict resolved manually
  (omit section if PR had no .csproj changes)
```

---

## Constraints

### Scope
- ✅ All git operations only in the user’s local cloned repo
- ✅ Porting branch created from latest remote HEAD of target (`git fetch` first)
- ✅ Push to user’s fork (`origin`), not the org repo directly
- ✅ Only exact files changed in the original PR are ported — list before cherry-pick, verify after
- ❌ Do NOT switch or modify the user’s current working branch
- ❌ Do NOT modify files outside the original PR’s file set
- ❌ Do NOT delete any files, branches, or resources

### JIRA
- ✅ Always clone a new porting JIRA ticket from the original
- ✅ Link porting ticket to original via “is cloned by”
- ✅ Porting ticket title: `Porting to <branch> - <original summary>`
- ✅ Only the porting ticket may be updated (add PR link comment)
- ❌ The original JIRA ticket must NOT be modified in any way

### Draft PR
- ✅ Always created in draft mode (`gh pr create --draft`)
- ✅ PR targets the org repo’s target branch
- ✅ PR body written to file — use `--body-file` always
- ❌ Never pass `--body` inline — PowerShell 5.1 treats `@` as a splat operator

### PowerShell Terminal
- ✅ Use `;` to chain commands — never `&&` (PS 5.1 parse error)
- ✅ Use backtick \` for line continuation — never `\`
- ✅ First `gh` call is slow (2–5s) — expected; do not retry

### Progress Reporting
- ✅ Print `⏳ [Step N/8] <action>...` before every slow operation
- ✅ Print `✅ [Step N/8] <result>` after every success
- ✅ Print `⏳ Still waiting for <operation>...` if no output for 10+ seconds
- ❌ Never silently proceed from one step to the next

---

## Tool Reference

| Operation | Tool | When |
|-----------|------|------|
| Fetch PR details | `gh pr view` | Step 1 |
| Validate JIRA ticket | JIRA MCP `get_issue` | Step 1 |
| Clone JIRA ticket | JIRA MCP `create_issue` + `link_issues` | Step 1 |
| Create porting branch | `git checkout -b` + `git push` | Step 2 |
| List PR changed files | `gh pr view --json files` | Step 3.0 |
| Cherry-pick commits | `git cherry-pick` | Step 3.1 |
| Detect conflicts | `git status --short` + `git diff --diff-filter=U` | Step 3.2 |
| Build | `dotnet build --no-restore` | Step 4 |
| Test | `dotnet test --no-build` | Step 4 |
| Parse TRX results | `python pr_porter.py parse-trx` | Step 5 |
| Generate PR body | `python pr_porter.py generate-pr-body` | Step 6 |
| Create draft PR | `gh pr create --draft` | Step 6 |
| Add JIRA comment | JIRA MCP `add_comment` | Step 7 |

---

## Error Handling Reference

| Scenario | Alert | Resume Phrase |
|----------|-------|---------------|
| JIRA ticket not found | "Ticket not found. Verify number." | Provide correct ticket |
| No JIRA + can’t extract from PR | "Porting JIRA required. Please provide one." | Provide ticket number |
| JIRA clone fails | "Failed to create ticket. Provide one manually." | Provide ticket number |
| PR not merged | "PR #N is not merged yet." | — |
| Cherry-pick conflict | ⚠️ CHERRY-PICK CONFLICT alert | `conflicts resolved, continue` |
| Push failure | ⚠️ PUSH FAILED alert | `push done, continue` |
| Build failure | ⚠️ BUILD FAILED alert + options (a/b/c) | `build fixed, continue` |
| Test failure | ⚠️ TESTS FAILED alert + options (a/b/c/d) | `tests fixed, continue` |
| `gh` not installed | "Install: `winget install GitHub.cli`" | — |
| JIRA MCP not configured | "Add JIRA MCP server to mcp.json." | — |

---

## Design Philosophy

> "Port exactly what was merged. Verify before proposing. Never touch the original ticket."

| Decision | Reason |
|----------|--------|
| **Always clone JIRA ticket** | Keeps the original ticket clean; porting work tracked separately |
| **File scope check after cherry-pick** | Cherry-picks can silently pull in unrelated changes; catching this early prevents scope creep |
| **Package version comparison** | Major version mismatches between branches cause subtle runtime bugs — surfacing them at port time is safer than discovering them in QA |
| **Draft PR always** | Gives reviewers a chance to inspect before merge; signals that porting work needs review |
| **Build + test before PR** | Broken ports should never reach reviewers; automated verification catches issues at the source |
