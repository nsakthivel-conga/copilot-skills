# Conga PR Porter Skill

## Purpose
Port a GitHub PR from one branch to another with JIRA tracking, conflict resolution, build/test verification, and draft PR creation.

## Prerequisites

| Tool | Purpose |
|------|---------|
| **Git** 2.30+ | Branch creation, cherry-pick |
| **`gh` CLI** | PR read/create |
| **Python 3.10+** | TRX parsing, PR body generation |
| **`conga_common.py`** | Shared utilities (TRX parsing, file I/O) |  ← ADD THIS
| **.NET SDK 8.0+** | `dotnet build` and `dotnet test` |
| **JIRA MCP** | Ticket validation, cloning, commenting |

**Note:** All `mcp_com_atlassian_*` JIRA calls require a `cloudId`. Retrieve it once at the start with `mcp_com_atlassian_getAccessibleAtlassianResources` and reuse it throughout.
---

## Operational Rules

### Scope of Changes
- All git operations happen only in the user's local cloned repo
- Never switch or modify the user's current working branch
- The porting branch is created from the latest remote HEAD of the target branch (`git fetch` first)
- Push goes to the user's fork (`upstream` remote), not the org repo directly
- Only the exact files changed in the original PR are ported — list before cherry-pick, verify after
- If cherry-pick touches files outside the original PR's file set — stop and alert the user

### Draft PR
- Always created in draft mode (`gh pr create --draft`)
- PR targets the org repo's target branch

### JIRA Scope
- A new porting JIRA ticket is always created (cloned from the original)
- Only the porting ticket may be updated (add PR link comment)
- The original JIRA ticket must NOT be modified in any way
- Porting ticket title: `Porting to <branch> - <original summary>`
- Porting ticket linked to original via "is cloned by"

### Package Porting Rules
- Only port files changed in the original PR — never modify other files
- For `.csproj` changes, only check packages actually changed in the PR
- If a changed package has a different major version between source and target — prompt user: skip / provide correct version / abort
- If same major version — apply as-is (patch/minor bumps are safe)
- Conga year-based versioning: `2025.10.0.6` → major = `2025.10`
- Standard versioning: `17.8.43` → major = `17`

### What Is NOT Allowed
- Modifying the original JIRA ticket
- Touching branches other than the new porting branch
- Making changes in other repositories or external systems
- Modifying files not changed in the original PR
- Deleting any files, branches, or resources

### PowerShell Terminal Rules

Visual Studio's integrated terminal runs **Windows PowerShell 5.1**, which has two important constraints:

| Problem | Cause | Rule |
|---------|-------|------|
| `&&` is a parse error | PS 5.1 does not support `&&` as a statement separator | **Always use `;`** to chain commands |
| First `gh` call is slow (2–5 s spinner) | Cold auth token read + HTTPS round-trip to `api.github.com` | Expected — do not retry; subsequent calls are faster |

**Command chaining — always use `;` in PowerShell:**
```powershell
# ❌ Fails in PS 5.1
cd "C:\path\to\repo" && gh pr view 123

# ✅ Works in all PS versions
cd "C:\path\to\repo"; gh pr view 123
```

**PR body with `@` mentions — never inline in `--body`; always use `--body-file`:**
```powershell
# ❌ PowerShell expands @ as a splat operator
gh pr create --body "Reviewers: @user-conga"

# ✅ Write body to a temp file first, then reference it
gh pr create --body-file pr-body.md
```

### Progress Reporting (Required)

**Before every tool call or terminal command that may take more than 5 seconds, print a progress banner in this exact format:**

```
⏳ [Step N/8] <What is happening> — please wait...
```

**After it completes successfully, print:**

```
✅ [Step N/8] <What finished> — done.
```

**Apply this rule unconditionally to every operation listed below:**

| Operation | Banner to print before running |
|-----------|-------------------------------|
| `gh pr view` | `⏳ [Step 1/8] Fetching PR #<N> from GitHub...` |
| JIRA `get_issue` | `⏳ [Step 1/8] Fetching JIRA ticket <ticket> from Conga JIRA...` |
| JIRA `create_issue` | `⏳ [Step 1/8] Creating porting JIRA ticket (cloning from <original>)...` |
| JIRA `link_issues` | `⏳ [Step 1/8] Linking porting ticket to original in JIRA...` |
| `git fetch` | `⏳ [Step 2/8] Fetching latest remote branch <target-branch> — this may take a few seconds...` |
| `git checkout -b` | `⏳ [Step 2/8] Creating branch <ticket> from <target-branch>...` |
| `git push` | `⏳ [Step 2/8] Pushing branch <ticket> to origin — please wait...` |
| `gh pr view --json files` | `⏳ [Step 3/8] Listing changed files in PR #<N>...` |
| `gh pr view --json commits` | `⏳ [Step 3/8] Fetching commit SHAs for PR #<N>...` |
| Each `git cherry-pick <sha>` | `⏳ [Step 3/8] Cherry-picking commit <sha> (<N> of <total>)...` |
| `dotnet build` | `⏳ [Step 4/8] Building solution — this typically takes 1–3 minutes, please wait...` |
| `dotnet test` | `⏳ [Step 4/8] Running tests — this may take several minutes, please wait...` |
| `python pr_porter.py generate-pr-body` | `⏳ [Step 6/8] Generating PR body from test results...` |
| `gh pr create` | `⏳ [Step 6/8] Creating draft PR on GitHub...` |
| JIRA `add_comment` | `⏳ [Step 7/8] Adding PR link comment to JIRA ticket <ticket>...` |

**If a command produces no output for more than 10 seconds, print:**

```
⌛ Still waiting for <operation> to complete — this is normal, please do not interrupt...
```

**Never silently proceed from one step to the next.** Always print the next step's banner before running its first command.

---

## Workflow

### Step 1: Validate Inputs & Resolve JIRA Ticket

> **Progress:** Print before running: `⏳ [Step 1/8] Fetching PR #<N> from GitHub...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json title,body,commits,mergeCommit,headRefName,baseRefName,state
```

> After the `gh pr view` result arrives, print: `✅ [Step 1/8] PR details fetched — title: "<title>", state: <state>.`
>
> Then print: `⏳ [Step 1/8] Resolving JIRA ticket...` before any JIRA MCP call.

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
          │  │    Compose new ticket description by combining all fetched fields:
          │  │
          │  │      ## [Port] Porting to `<branch>`
          │  │      | Field        | Value                         |
          │  │      |--------------|-------------------------------|
          │  │      | Original     | <ticket>                      |
          │  │      | Original PR  | #<number>                     |
          │  │      | Target       | <branch>                      |
          │  │
          │  │      ---
          │  │
          │  │      ## Description
          │  │      <original description — copied verbatim>
          │  │
          │  │      ## Acceptance Criteria
          │  │      <customfield_15890 — copied verbatim, omit section if empty>
          │  │
          │  │      ## Steps to Reproduce
          │  │      <customfield_10106 — copied verbatim, omit section if empty>
          │  │
          │  │      ## Design Description
          │  │      <customfield_15701 — copied verbatim, omit section if empty>
          │  │
          │  │    @jira create_issue
          │  │      summary:     "Porting to <branch> - <original summary>"
          │  │      issueType:   <same as original>
          │  │      project:     <same as original>
          │  │      priority:    <same as original>
          │  │      components:  <same as original>
          │  │      labels:      <same as original>
          │  │      description: <composed description above>
          │  │      + copy any other required fields that caused create to fail
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

### Step 2: Create Branch

> **Progress:** Print before running: `⏳ [Step 2/8] Detecting remote configuration...`

```powershell
git remote -v   # detect fork vs direct-clone
```

> After remotes are known, print: `✅ [Step 2/8] Remotes detected — workflow: <fork|direct-clone>.`
>
> Then print: `⏳ [Step 2/8] Fetching latest remote branch <target-branch> — this may take a few seconds...` before `git fetch`.
>
> After fetch: `✅ [Step 2/8] Branch <target-branch> up to date.`
>
> Before `git checkout -b`: `⏳ [Step 2/8] Creating branch <jira-ticket> from <target-branch>...`
>
> Before `git push`: `⏳ [Step 2/8] Pushing branch <jira-ticket> to origin — please wait...`

```powershell
# Fork workflow (origin=fork, upstream=org)
git fetch upstream <target-branch>
git checkout -b <jira-ticket> upstream/<target-branch>
git push -u origin <jira-ticket>

# Direct-clone workflow (origin=org only)
git fetch origin <target-branch>
git checkout -b <jira-ticket> origin/<target-branch>
git push -u origin <jira-ticket>

# NOTE: Use ; not && to chain commands in PowerShell 5.1
# Example: cd "C:\repo"; git fetch upstream main
```

#### Push Error Handling

If `git push` fails — **STOP and show this alert**:

```
⚠️  PUSH FAILED — Action Required
─────────────────────────────────────────────────────────
Branch : <jira-ticket>
Remote : <upstream/origin>
Error  : <exact error message>

Common causes and fixes:

  [401/403 Authentication]
    → Run:  gh auth login
    → Then: git push upstream <jira-ticket>
    → Say:  "push done, continue"

  [Branch protection / required review]
    → The remote may block direct pushes to protected branches
    → Verify target branch is not protected on your fork
    → Say:  "push done, continue" after manual push succeeds

  [Network / timeout]
    → Check your internet connection and VPN
    → Retry: git push upstream <jira-ticket>
    → Say:  "push done, continue"

  [Branch already exists on remote]
    → If the branch is yours and clean:
         git push upstream <jira-ticket> --force-with-lease
    → Say:  "push done, continue"
─────────────────────────────────────────────────────────
```

After user says **"push done, continue"** — proceed to Step 3.

### Step 3: Port Changes

#### 3.0 List and Confirm Files

> **Progress:** Print: `⏳ [Step 3/8] Fetching list of files changed in PR #<N>...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json files --jq '.files[].path'
```

> After the list arrives, print it to the user and wait for confirmation before proceeding.

Show the file list to the user before proceeding. If any file is unexpected — stop and confirm.

#### 3.1 Cherry-Pick Commits

> **Progress:** Print: `⏳ [Step 3/8] Fetching commit SHAs for PR #<N>...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json commits --jq '.commits[].oid'
```

> After SHAs are known, print: `✅ [Step 3/8] Found <N> commit(s) to cherry-pick.`
>
> Before each cherry-pick, print: `⏳ [Step 3/8] Cherry-picking commit <sha> (<current> of <total>)...`
>
> After each successful cherry-pick, print: `✅ [Step 3/8] Commit <sha> applied cleanly.`

```bash
git cherry-pick <sha-1>
git cherry-pick <sha-2>
# one at a time
```

#### 3.2 Conflict Detection

After each cherry-pick:

```bash
git status --short
git diff --name-only --diff-filter=U
```

If conflicts detected — **STOP immediately** and show this alert:

```
⚠️  CHERRY-PICK CONFLICT — Action Required
─────────────────────────────────────────────────────────
Commit : <sha>
Branch : <porting-branch>
Conflict in:
  - <file1>
  - <file2>

To resolve:
  1. Open the conflicting file(s) in Visual Studio or VS Code
  2. Look for conflict markers:
       <<<<<<< HEAD          ← keep what you want from this section
       <target branch code>
       =======
       <incoming code from cherry-pick>
       >>>>>>> <sha>
  3. Edit the file to the correct merged state (remove all markers)
  4. In Source Control panel (or terminal): stage the resolved file
       git add <file>
  5. Verify no unresolved markers remain:
       git diff --check
  6. Say: "conflicts resolved, continue"

⛔ Do NOT run git cherry-pick --continue yourself — Copilot will do it.
─────────────────────────────────────────────────────────
```

After user says **"conflicts resolved, continue"**:

```bash
git diff --check          # verify no markers remain
git cherry-pick --continue --no-edit
git status --short        # confirm clean state
```

#### 3.3 Verify File Scope

```bash
git diff --name-only origin/<target-branch>...HEAD
```

If files outside the original PR appear — STOP:

```
⚠️  SCOPE WARNING: Unexpected files modified: <list>
(a) Revert and continue  (b) Abort
```

#### 3.4 Package Version Conflict Detection

For each `.csproj` changed in the PR, after cherry-pick apply:

1. Diff to find modified `PackageReference` lines
2. For each changed package compare three values:
   - **PR version** (from original PR source branch)
   - **Target version** (current HEAD of target branch)
   - **Major version** of each (standard: `17.8.43` → `17`; Conga year-based: `2025.10.0.6` → `2025.10`)

3. Apply the following decision for each package:

```
For each changed PackageReference:
│
├─ Major versions DIFFER (PR major ≠ target major)
│    → STOP and prompt:
│
│       ⚠️  Package version conflict in <file>:
│         Package:        <name>
│         PR version:     <source-version>  (major: <x>)
│         Target version: <target-version>  (major: <y>)
│         (a) Skip — keep target version
│         (b) Provide correct version for target branch
│         (c) Abort
│
│    After resolution:
│    (a) → keep target version; git add <file>; git commit --amend --no-edit
│    (b) → apply user-provided version; git add <file>; git commit --amend --no-edit
│
├─ Same major AND target version is HIGHER than PR version
│    → Automatically keep target branch version (do NOT downgrade)
│    → Apply no change to that package line (target version already in place)
│    → Log: "⚠️ <name>: kept target <target-version> (PR had <pr-version>, same major — target is higher)"
│
└─ Same major AND PR version is HIGHER than or EQUAL to target version
     → Apply PR version (safe upgrade or no change)
     → Log: "✅ <name>: <target-version> → <pr-version> (same major, applied)"
```

4. Collect all package log lines — include in Step 8 final report.

### Step 4: Build and Test

> **Progress:** Print before build: `⏳ [Step 4/8] Building solution — this typically takes 1–3 minutes, please wait...`
>
> Print before tests: `⏳ [Step 4/8] Running tests — this may take several minutes depending on test count, please wait...`

```bash
dotnet build --no-restore 2>&1
dotnet test --no-build --logger "trx;LogFileName=port-test-results.trx" --results-directory ./TestResults 2>&1
```

> After build: `✅ [Step 4/8] Build succeeded.` or immediately show the BUILD FAILED alert.
>
> After tests: `✅ [Step 4/8] Tests complete — <passed> passed, <failed> failed, <skipped> skipped.` or show TESTS FAILED alert.

### Step 5: Handle Failures

#### Build Failure

If `dotnet build` returns errors — **STOP and show this alert**:

```
⚠️  BUILD FAILED — Action Required
─────────────────────────────────────────────────────────
Branch  : <porting-branch>
Errors  : <N>

<paste first 10 error lines here>

Options:
  (a) Let Copilot attempt to fix the build errors
  (b) Fix manually in IDE, then say: "build fixed, continue"
  (c) Abort the port
─────────────────────────────────────────────────────────
```

- **(a) Auto-fix** → Copilot analyses errors, edits files, re-runs `dotnet build`
  - If build passes after fix → proceed to tests
  - If build still fails after 2 attempts → escalate to option (b)
- **(b) Manual fix** → wait for user to say **"build fixed, continue"**
  - Re-run `dotnet build` to verify before proceeding
- **(c) Abort** → `git cherry-pick --abort` (if in progress) then `git checkout <original-branch>`

#### Test Failure

If `dotnet test` reports failures — **STOP and show this alert**:

```
⚠️  TESTS FAILED — Action Required
─────────────────────────────────────────────────────────
Branch   : <porting-branch>
Results  : <passed> passed, <failed> FAILED, <skipped> skipped

Failed tests:
  ✗ <TestClass.TestMethod1>
    Error: <first 120 chars of error message>
  ✗ <TestClass.TestMethod2>
    Error: <first 120 chars of error message>
  ... (run parse-trx for full details)

Options:
  (a) Let Copilot attempt to fix the failing tests
  (b) Fix manually in IDE, then say: "tests fixed, continue"
  (c) Create draft PR anyway (tests failing — reviewers will be notified)
  (d) Abort the port
─────────────────────────────────────────────────────────
```

To get full failure details:
```bash
cd "../.github/copilot/skills/conga-pr-porter"
python pr_porter.py parse-trx --file <repo-root>/TestResults/port-test-results.trx
```

- **(a) Auto-fix** → Copilot analyses failures, edits source/test files, re-runs tests
- **(b) Manual fix** → wait for user to say **"tests fixed, continue"**
  - Re-run `dotnet test` to verify before proceeding
- **(c) Continue with failures** → proceed to Step 6; PR body will show failed count
- **(d) Abort** → `git checkout <original-branch>`

After fix → always re-run both build and tests before proceeding.

### Step 6: Create Draft PR

```powershell
# Step 6a: Generate PR body with formatted test results table
# pr_porter.py writes pr-body.md to the skill directory (next to the script)
# > Progress: print before running: ⏳ [Step 6/8] Generating PR body from test results...
cd "../.github/copilot/skills/conga-pr-porter"
python pr_porter.py generate-pr-body `
  --original-pr <number> `
  --original-repo <org>/<repo> `
  --target-branch <branch> `
  --jira-ticket <porting-ticket> `
  --test-results <repo-root>/TestResults/port-test-results.trx `
  --commits "<sha1>,<sha2>,<sha3>" `
  --jira-base-url https://conga.atlassian.net
# ✅ [Step 6/8] PR body written to pr-body.md.

# Step 6b: Create draft PR using the generated body
# > Progress: print before running: ⏳ [Step 6/8] Creating draft PR on GitHub...
# IMPORTANT: Never pass --body with @ mentions inline — PowerShell 5.1 treats @ as a
# splat operator and will fail. Always write the body to a file and use --body-file.
cd <repo-root>
gh pr create `
  --repo <org>/<repo> `
  --base <target-branch> `
  --head <fork>:<jira-ticket> `
  --title "<porting-ticket>: Porting to <target-branch> - <original-title>" `
  --body-file "../.github/copilot/skills/conga-pr-porter/pr-body.md" `
  --draft
# ✅ [Step 6/8] Draft PR created: <pr-url>
```

> **Note:** `pr-body.md` is written to the skill directory (`conga-pr-porter/`), not the repo root.
> Always use the full relative path when passing it to `gh pr create --body-file`.
> Use backtick (`` ` ``) for line continuation in PowerShell — **not** `\`.

### Step 7: Update JIRA

> **Progress:** Print: `⏳ [Step 7/8] Adding PR link comment to JIRA ticket <porting-ticket>...`

```
@jira add_comment <porting-ticket> "Draft PR created: <pr-url>"
```

> After comment is posted: `✅ [Step 7/8] JIRA ticket <porting-ticket> updated with PR link.`

### Step 8: Report Results

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
  ⚠️  <package>: kept <target-version>  ← target was higher than PR's <pr-version> (same major — no downgrade applied)
  ⚠️  <package>: <resolved-version>  ← major version conflict resolved manually by user
  (omit this section entirely if the PR contained no .csproj changes)
```

> The ⚠️ lines are informational — they tell reviewers exactly where the ported version
> differs from the original PR so they can confirm the target branch version is correct.

---

## Tool Responsibilities

| Operation | Tool |
|-----------|------|
| Validate JIRA ticket | JIRA MCP `get_issue` |
| Clone JIRA ticket | JIRA MCP `create_issue` + `link_issues` |
| Add JIRA comment | JIRA MCP `add_comment` |
| Read/create GitHub PR | `gh` CLI |
| Git branch/cherry-pick | `git` CLI |
| Build & test | `dotnet` CLI |
| Parse .trx test results | `python pr_porter.py parse-trx` |
| Generate PR body | `python pr_porter.py generate-pr-body` |

---

## Error Handling

| Scenario | Alert Shown | Resume Phrase |
|----------|-------------|---------------|
| JIRA ticket not found | "Ticket not found. Verify number." | Provide correct ticket |
| No JIRA + can't extract from PR | "Porting JIRA required. Please provide one." | Provide ticket number |
| JIRA clone fails | "Failed to create ticket. Provide one manually." | Provide ticket number |
| PR not merged | "PR #N is not merged yet." | — |
| Cherry-pick conflict | ⚠️ CHERRY-PICK CONFLICT alert with file list + IDE steps | `conflicts resolved, continue` |
| Push failure | ⚠️ PUSH FAILED alert with cause + fix steps | `push done, continue` |
| Build failure | ⚠️ BUILD FAILED alert with error lines + options (a/b/c) | `build fixed, continue` |
| Test failure | ⚠️ TESTS FAILED alert with failed test list + options (a/b/c/d) | `tests fixed, continue` |
| `gh` not installed | "Install: `winget install GitHub.cli`" | — |
| JIRA MCP not configured | "Add JIRA MCP server to mcp.json." | — |

---

## Quick Reference

| Trigger | Command |
|---------|---------|
| Port with JIRA | `Port my PR #123 from master to release/2025.1 for REVREN-456` |
| Port without JIRA | `Port my PR #123 from master to release/2025.1` |
| Port with URL | `Port PR https://github.com/org/repo/pull/123 to release/2025.1` |
| Resume after conflict | `conflicts resolved, continue` |
| Skip tests | `Port PR #123 to release/2025.1, skip tests` |
