# Conga PR Porter Skill

## Purpose
Port a GitHub PR from one branch to another with JIRA tracking, conflict resolution, build/test verification, and draft PR creation.

## Prerequisites

| Tool | Purpose |
|------|---------|
| **Git** 2.30+ | Branch creation, cherry-pick |
| **`gh` CLI** | PR read/create |
| **Python 3.10+** | TRX parsing, PR body generation |
| **`conga_common.py`** | Shared utilities (TRX parsing, file I/O) |  â† ADD THIS
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
- Only the exact files changed in the original PR are ported â€” list before cherry-pick, verify after
- If cherry-pick touches files outside the original PR's file set â€” stop and alert the user

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
- Only port files changed in the original PR â€” never modify other files
- For `.csproj` changes, only check packages actually changed in the PR
- If a changed package has a different major version between source and target â€” prompt user: skip / provide correct version / abort
- If same major version â€” apply as-is (patch/minor bumps are safe)
- Conga year-based versioning: `2025.10.0.6` â†’ major = `2025.10`
- Standard versioning: `17.8.43` â†’ major = `17`

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
| First `gh` call is slow (2â€“5 s spinner) | Cold auth token read + HTTPS round-trip to `api.github.com` | Expected â€” do not retry; subsequent calls are faster |

**Command chaining â€” always use `;` in PowerShell:**
```powershell
# âŒ Fails in PS 5.1
cd "C:\path\to\repo" && gh pr view 123

# âœ… Works in all PS versions
cd "C:\path\to\repo"; gh pr view 123
```

**PR body with `@` mentions â€” never inline in `--body`; always use `--body-file`:**
```powershell
# âŒ PowerShell expands @ as a splat operator
gh pr create --body "Reviewers: @user-conga"

# âœ… Write body to a temp file first, then reference it
gh pr create --body-file pr-body.md
```

### Progress Reporting (Required)

**Before every tool call or terminal command that may take more than 5 seconds, print a progress banner in this exact format:**

```
â³ [Step N/8] <What is happening> â€” please wait...
```

**After it completes successfully, print:**

```
âœ… [Step N/8] <What finished> â€” done.
```

**Apply this rule unconditionally to every operation listed below:**

| Operation | Banner to print before running |
|-----------|-------------------------------|
| `gh pr view` | `â³ [Step 1/8] Fetching PR #<N> from GitHub...` |
| JIRA `get_issue` | `â³ [Step 1/8] Fetching JIRA ticket <ticket> from Conga JIRA...` |
| JIRA `create_issue` | `â³ [Step 1/8] Creating porting JIRA ticket (cloning from <original>)...` |
| JIRA `link_issues` | `â³ [Step 1/8] Linking porting ticket to original in JIRA...` |
| `git fetch` | `â³ [Step 2/8] Fetching latest remote branch <target-branch> â€” this may take a few seconds...` |
| `git checkout -b` | `â³ [Step 2/8] Creating branch <ticket> from <target-branch>...` |
| `git push` | `â³ [Step 2/8] Pushing branch <ticket> to origin â€” please wait...` |
| `gh pr view --json files` | `â³ [Step 3/8] Listing changed files in PR #<N>...` |
| `gh pr view --json commits` | `â³ [Step 3/8] Fetching commit SHAs for PR #<N>...` |
| Each `git cherry-pick <sha>` | `â³ [Step 3/8] Cherry-picking commit <sha> (<N> of <total>)...` |
| `dotnet build` | `â³ [Step 4/8] Building solution â€” this typically takes 1â€“3 minutes, please wait...` |
| `dotnet test` | `â³ [Step 4/8] Running tests â€” this may take several minutes, please wait...` |
| `python pr_porter.py generate-pr-body` | `â³ [Step 6/8] Generating PR body from test results...` |
| `gh pr create` | `â³ [Step 6/8] Creating draft PR on GitHub...` |
| JIRA `add_comment` | `â³ [Step 7/8] Adding PR link comment to JIRA ticket <ticket>...` |

**If a command produces no output for more than 10 seconds, print:**

```
âŒ› Still waiting for <operation> to complete â€” this is normal, please do not interrupt...
```

**Never silently proceed from one step to the next.** Always print the next step's banner before running its first command.

---

## Workflow

### Step 1: Validate Inputs & Resolve JIRA Ticket

> **Progress:** Print before running: `â³ [Step 1/8] Fetching PR #<N> from GitHub...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json title,body,commits,mergeCommit,headRefName,baseRefName,state
```

> After the `gh pr view` result arrives, print: `âœ… [Step 1/8] PR details fetched â€” title: "<title>", state: <state>.`
>
> Then print: `â³ [Step 1/8] Resolving JIRA ticket...` before any JIRA MCP call.

#### JIRA Ticket Decision Tree

```
User provides a PORTING JIRA ticket?
â”‚
â”œâ”€ YES â–¶ @jira get_issue <ticket>
â”‚          â”œâ”€ Exists â–¶ Use as porting ticket â–¶ Step 2
â”‚          â””â”€ Not found â–¶ "Ticket not found. Verify number."
â”‚
â””â”€ NO â–¶ Extract ORIGINAL JIRA from PR title/branch (pattern: [A-Z][A-Z0-9]+-\d+)
          â”œâ”€ Found â–¶ @jira get_issue <original>
          â”‚           Prompt user:
          â”‚           "(a) Create porting ticket automatically
          â”‚            (b) Provide existing porting ticket number"
          â”‚
          â”‚  â”œâ”€ (a) CREATE
          â”‚  â”‚    @jira get_issue <original>
          â”‚  â”‚      fields: summary, description, issuetype, project, priority,
          â”‚  â”‚              components, labels, fixVersions
          â”‚  â”‚
          â”‚  â”‚    Compose new ticket description by combining all fetched fields:
          â”‚  â”‚
          â”‚  â”‚      ## [Port] Porting to `<branch>`
          â”‚  â”‚      | Field        | Value                         |
          â”‚  â”‚      |--------------|-------------------------------|
          â”‚  â”‚      | Original     | <ticket>                      |
          â”‚  â”‚      | Original PR  | #<number>                     |
          â”‚  â”‚      | Target       | <branch>                      |
          â”‚  â”‚
          â”‚  â”‚      ---
          â”‚  â”‚
          â”‚  â”‚      ## Description
          â”‚  â”‚      <original description â€” copied verbatim>
          â”‚  â”‚
          â”‚  â”‚      ## Acceptance Criteria
          â”‚  â”‚      <customfield_15890 â€” copied verbatim, omit section if empty>
          â”‚  â”‚
          â”‚  â”‚      ## Steps to Reproduce
          â”‚  â”‚      <customfield_10106 â€” copied verbatim, omit section if empty>
          â”‚  â”‚
          â”‚  â”‚      ## Design Description
          â”‚  â”‚      <customfield_15701 â€” copied verbatim, omit section if empty>
          â”‚  â”‚
          â”‚  â”‚    @jira create_issue
          â”‚  â”‚      summary:     "Porting to <branch> - <original summary>"
          â”‚  â”‚      issueType:   <same as original>
          â”‚  â”‚      project:     <same as original>
          â”‚  â”‚      priority:    <same as original>
          â”‚  â”‚      components:  <same as original>
          â”‚  â”‚      labels:      <same as original>
          â”‚  â”‚      description: <composed description above>
          â”‚  â”‚      + copy any other required fields that caused create to fail
          â”‚  â”‚        (e.g. customfield_11501, customfield_15716, customfield_15867)
          â”‚  â”‚
          â”‚  â”‚    @jira link_issues <new-ticket> "is cloned by" <original-ticket>
          â”‚  â”‚    â–¶ Use new ticket as porting ticket
          â”‚  â”‚
          â”‚  â””â”€ (b) PROVIDE â–¶ Wait â–¶ @jira get_issue â–¶ validate â–¶ use
          â”‚
          â””â”€ Not found â–¶ "Could not find JIRA ticket in PR. Please provide one."
                          â–¶ Wait â–¶ validate â–¶ continue
```

### Step 2: Create Branch

> **Progress:** Print before running: `â³ [Step 2/8] Detecting remote configuration...`

```powershell
git remote -v   # detect fork vs direct-clone
```

> After remotes are known, print: `âœ… [Step 2/8] Remotes detected â€” workflow: <fork|direct-clone>.`
>
> Then print: `â³ [Step 2/8] Fetching latest remote branch <target-branch> â€” this may take a few seconds...` before `git fetch`.
>
> After fetch: `âœ… [Step 2/8] Branch <target-branch> up to date.`
>
> Before `git checkout -b`: `â³ [Step 2/8] Creating branch <jira-ticket> from <target-branch>...`
>
> Before `git push`: `â³ [Step 2/8] Pushing branch <jira-ticket> to origin â€” please wait...`

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

If `git push` fails â€” **STOP and show this alert**:

```
âš ï¸  PUSH FAILED â€” Action Required
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Branch : <jira-ticket>
Remote : <upstream/origin>
Error  : <exact error message>

Common causes and fixes:

  [401/403 Authentication]
    â†’ Run:  gh auth login
    â†’ Then: git push upstream <jira-ticket>
    â†’ Say:  "push done, continue"

  [Branch protection / required review]
    â†’ The remote may block direct pushes to protected branches
    â†’ Verify target branch is not protected on your fork
    â†’ Say:  "push done, continue" after manual push succeeds

  [Network / timeout]
    â†’ Check your internet connection and VPN
    â†’ Retry: git push upstream <jira-ticket>
    â†’ Say:  "push done, continue"

  [Branch already exists on remote]
    â†’ If the branch is yours and clean:
         git push upstream <jira-ticket> --force-with-lease
    â†’ Say:  "push done, continue"
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
```

After user says **"push done, continue"** â€” proceed to Step 3.

### Step 3: Port Changes

#### 3.0 List and Confirm Files

> **Progress:** Print: `â³ [Step 3/8] Fetching list of files changed in PR #<N>...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json files --jq '.files[].path'
```

> After the list arrives, print it to the user and wait for confirmation before proceeding.

Show the file list to the user before proceeding. If any file is unexpected â€” stop and confirm.

#### 3.1 Cherry-Pick Commits

> **Progress:** Print: `â³ [Step 3/8] Fetching commit SHAs for PR #<N>...`

```bash
gh pr view <pr-number> --repo <org>/<repo> --json commits --jq '.commits[].oid'
```

> After SHAs are known, print: `âœ… [Step 3/8] Found <N> commit(s) to cherry-pick.`
>
> Before each cherry-pick, print: `â³ [Step 3/8] Cherry-picking commit <sha> (<current> of <total>)...`
>
> After each successful cherry-pick, print: `âœ… [Step 3/8] Commit <sha> applied cleanly.`

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

If conflicts detected â€” **STOP immediately** and show this alert:

```
âš ï¸  CHERRY-PICK CONFLICT â€” Action Required
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Commit : <sha>
Branch : <porting-branch>
Conflict in:
  - <file1>
  - <file2>

To resolve:
  1. Open the conflicting file(s) in Visual Studio or VS Code
  2. Look for conflict markers:
       <<<<<<< HEAD          â† keep what you want from this section
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

â›” Do NOT run git cherry-pick --continue yourself â€” Copilot will do it.
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

If files outside the original PR appear â€” STOP:

```
âš ï¸  SCOPE WARNING: Unexpected files modified: <list>
(a) Revert and continue  (b) Abort
```

#### 3.4 Package Version Conflict Detection

For each `.csproj` changed in the PR, after cherry-pick apply:

1. Diff to find modified `PackageReference` lines
2. For each changed package compare three values:
   - **PR version** (from original PR source branch)
   - **Target version** (current HEAD of target branch)
   - **Major version** of each (standard: `17.8.43` â†’ `17`; Conga year-based: `2025.10.0.6` â†’ `2025.10`)

3. Apply the following decision for each package:

```
For each changed PackageReference:
â”‚
â”œâ”€ Major versions DIFFER (PR major â‰  target major)
â”‚    â†’ STOP and prompt:
â”‚
â”‚       âš ï¸  Package version conflict in <file>:
â”‚         Package:        <name>
â”‚         PR version:     <source-version>  (major: <x>)
â”‚         Target version: <target-version>  (major: <y>)
â”‚         (a) Skip â€” keep target version
â”‚         (b) Provide correct version for target branch
â”‚         (c) Abort
â”‚
â”‚    After resolution:
â”‚    (a) â†’ keep target version; git add <file>; git commit --amend --no-edit
â”‚    (b) â†’ apply user-provided version; git add <file>; git commit --amend --no-edit
â”‚
â”œâ”€ Same major AND target version is HIGHER than PR version
â”‚    â†’ Automatically keep target branch version (do NOT downgrade)
â”‚    â†’ Apply no change to that package line (target version already in place)
â”‚    â†’ Log: "âš ï¸ <name>: kept target <target-version> (PR had <pr-version>, same major â€” target is higher)"
â”‚
â””â”€ Same major AND PR version is HIGHER than or EQUAL to target version
     â†’ Apply PR version (safe upgrade or no change)
     â†’ Log: "âœ… <name>: <target-version> â†’ <pr-version> (same major, applied)"
```

4. Collect all package log lines â€” include in Step 8 final report.

### Step 4: Build and Test

> **Progress:** Print before build: `â³ [Step 4/8] Building solution â€” this typically takes 1â€“3 minutes, please wait...`
>
> Print before tests: `â³ [Step 4/8] Running tests â€” this may take several minutes depending on test count, please wait...`

```bash
dotnet build --no-restore 2>&1
dotnet test --no-build --logger "trx;LogFileName=port-test-results.trx" --results-directory ./TestResults 2>&1
```

> After build: `âœ… [Step 4/8] Build succeeded.` or immediately show the BUILD FAILED alert.
>
> After tests: `âœ… [Step 4/8] Tests complete â€” <passed> passed, <failed> failed, <skipped> skipped.` or show TESTS FAILED alert.

### Step 5: Handle Failures

#### Build Failure

If `dotnet build` returns errors â€” **STOP and show this alert**:

```
âš ï¸  BUILD FAILED â€” Action Required
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Branch  : <porting-branch>
Errors  : <N>

<paste first 10 error lines here>

Options:
  (a) Let Copilot attempt to fix the build errors
  (b) Fix manually in IDE, then say: "build fixed, continue"
  (c) Abort the port
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
```

- **(a) Auto-fix** â†’ Copilot analyses errors, edits files, re-runs `dotnet build`
  - If build passes after fix â†’ proceed to tests
  - If build still fails after 2 attempts â†’ escalate to option (b)
- **(b) Manual fix** â†’ wait for user to say **"build fixed, continue"**
  - Re-run `dotnet build` to verify before proceeding
- **(c) Abort** â†’ `git cherry-pick --abort` (if in progress) then `git checkout <original-branch>`

#### Test Failure

If `dotnet test` reports failures â€” **STOP and show this alert**:

```
âš ï¸  TESTS FAILED â€” Action Required
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Branch   : <porting-branch>
Results  : <passed> passed, <failed> FAILED, <skipped> skipped

Failed tests:
  âœ— <TestClass.TestMethod1>
    Error: <first 120 chars of error message>
  âœ— <TestClass.TestMethod2>
    Error: <first 120 chars of error message>
  ... (run parse-trx for full details)

Options:
  (a) Let Copilot attempt to fix the failing tests
  (b) Fix manually in IDE, then say: "tests fixed, continue"
  (c) Create draft PR anyway (tests failing â€” reviewers will be notified)
  (d) Abort the port
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
```

To get full failure details:
```bash
cd "..\copilot-skills\conga-pr-porter"
python pr_porter.py parse-trx --file <repo-root>/TestResults/port-test-results.trx
```

- **(a) Auto-fix** â†’ Copilot analyses failures, edits source/test files, re-runs tests
- **(b) Manual fix** â†’ wait for user to say **"tests fixed, continue"**
  - Re-run `dotnet test` to verify before proceeding
- **(c) Continue with failures** â†’ proceed to Step 6; PR body will show failed count
- **(d) Abort** â†’ `git checkout <original-branch>`

After fix â†’ always re-run both build and tests before proceeding.

### Step 6: Create Draft PR

```powershell
# Step 6a: Generate PR body with formatted test results table
# pr_porter.py writes pr-body.md to the skill directory (next to the script)
# > Progress: print before running: â³ [Step 6/8] Generating PR body from test results...
cd "..\copilot-skills\conga-pr-porter"
python pr_porter.py generate-pr-body `
  --original-pr <number> `
  --original-repo <org>/<repo> `
  --target-branch <branch> `
  --jira-ticket <porting-ticket> `
  --test-results <repo-root>/TestResults/port-test-results.trx `
  --commits "<sha1>,<sha2>,<sha3>" `
  --jira-base-url https://conga.atlassian.net
# âœ… [Step 6/8] PR body written to pr-body.md.

# Step 6b: Create draft PR using the generated body
# > Progress: print before running: â³ [Step 6/8] Creating draft PR on GitHub...
# IMPORTANT: Never pass --body with @ mentions inline â€” PowerShell 5.1 treats @ as a
# splat operator and will fail. Always write the body to a file and use --body-file.
cd <repo-root>
gh pr create `
  --repo <org>/<repo> `
  --base <target-branch> `
  --head <fork>:<jira-ticket> `
  --title "<porting-ticket>: Porting to <target-branch> - <original-title>" `
  --body-file "..\copilot-skills\conga-pr-porter/pr-body.md" `
  --draft
# âœ… [Step 6/8] Draft PR created: <pr-url>
```

> **Note:** `pr-body.md` is written to the skill directory (`conga-pr-porter/`), not the repo root.
> Always use the full relative path when passing it to `gh pr create --body-file`.
> Use backtick (`` ` ``) for line continuation in PowerShell â€” **not** `\`.

### Step 7: Update JIRA

> **Progress:** Print: `â³ [Step 7/8] Adding PR link comment to JIRA ticket <porting-ticket>...`

```
@jira add_comment <porting-ticket> "Draft PR created: <pr-url>"
```

> After comment is posted: `âœ… [Step 7/8] JIRA ticket <porting-ticket> updated with PR link.`

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
  âœ… <package>: <pr-version> applied  (same major, PR version is higher)
  âš ï¸  <package>: kept <target-version>  â† target was higher than PR's <pr-version> (same major â€” no downgrade applied)
  âš ï¸  <package>: <resolved-version>  â† major version conflict resolved manually by user
  (omit this section entirely if the PR contained no .csproj changes)
```

> The âš ï¸ lines are informational â€” they tell reviewers exactly where the ported version
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
| PR not merged | "PR #N is not merged yet." | â€” |
| Cherry-pick conflict | âš ï¸ CHERRY-PICK CONFLICT alert with file list + IDE steps | `conflicts resolved, continue` |
| Push failure | âš ï¸ PUSH FAILED alert with cause + fix steps | `push done, continue` |
| Build failure | âš ï¸ BUILD FAILED alert with error lines + options (a/b/c) | `build fixed, continue` |
| Test failure | âš ï¸ TESTS FAILED alert with failed test list + options (a/b/c/d) | `tests fixed, continue` |
| `gh` not installed | "Install: `winget install GitHub.cli`" | â€” |
| JIRA MCP not configured | "Add JIRA MCP server to mcp.json." | â€” |

---

## Quick Reference

| Trigger | Command |
|---------|---------|
| Port with JIRA | `Port my PR #123 from master to release/2025.1 for REVREN-456` |
| Port without JIRA | `Port my PR #123 from master to release/2025.1` |
| Port with URL | `Port PR https://github.com/org/repo/pull/123 to release/2025.1` |
| Resume after conflict | `conflicts resolved, continue` |
| Skip tests | `Port PR #123 to release/2025.1, skip tests` |
