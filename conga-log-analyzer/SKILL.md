---
name: conga-log-analyzer
description: |
  Download Grafana Loki logs by TraceId, analyze errors and exceptions, and
  identify root cause. Runs a local Python script (stdlib only, zero dependencies)
  to fetch and pre-process logs, then reads exactly three LLM-safe summary files
  to synthesize root cause, evidence, performance hotspots, and a recommendation.
  Also supports analysis of multiple manually downloaded raw-logs.json files placed
  in a named folder under the downloads directory — no Grafana connection required.
---

# Conga Log Analyzer Skill

## The Core Idea

Standard log analysis requires manually navigating Grafana, downloading raw JSON, and reading thousands of lines. This skill is different:

1. **Download layer** — A single Python script fetches logs from Grafana Loki by TraceId or custom query and writes structured analysis files locally. Raw data never enters the LLM context.
2. **Manual layer** — Multiple `raw-logs.json` files downloaded from Grafana can be placed in a named folder under `downloads\` and analyzed together without any Grafana connection.
3. **Summary layer** — The script pre-processes logs into three LLM-safe files: a service overview, a stack-trace analysis with GitHub links, and a performance summary. Total context: ~4,450 tokens.
4. **Synthesis layer** — The LLM reads only the three summary files and returns root cause, evidence, performance correlation, and a recommendation in one response.

> Python handles all log fetching and pre-processing; the LLM reads only the distilled summaries.

---

## Analysis Files

| File | Size | Read? | Contents |
|------|------|-------|----------|
| `summary.md` | ~3 KB | ✅ **YES** | Overview: services, error root cause, perf hotspots |
| `error-analysis.md` | ~9 KB | ✅ **YES** | Stack traces, GitHub links, exception types |
| `perf-summary.md` | ~2 KB | ✅ **YES** | Service time, slow segments, method durations (LLM-safe) |
| `performance.md` | ~178 KB | ❌ NO | Full waterfall — too large, use `perf-summary.md` instead |
| `timeline.md` | ~193 KB | ❌ NO | Every log entry — too large, use `summary.md` |
| `raw-logs.json` | ~1.4 MB | ❌ NO | Raw Grafana data — never load into LLM context |
| `summary.json` | ~700 KB | ❌ NO | Structured analysis data — for tooling only |

Total LLM context from the three YES files: **~4,450 tokens** — fits comfortably in any model.

---

## ⚡ Quick Start

```bash
# By TraceId (dev/qa default to deployment_environment=rls04)
python log_downloader.py --trace-id "abc123" --environment dev

# With explicit deployment filter
python log_downloader.py --trace-id "abc123" --environment dev --deployment-env rls04

# Custom Loki query with service filter
python log_downloader.py --environment dev --loki-query '{deployment_environment="rls04", service_name="platform-objectdb-api"} |= "abc123"'

# Extended time range (15 days = 21600 min)
python log_downloader.py --trace-id "abc123" --environment dev --time-range 21600

# Analyze a single previously downloaded raw-logs.json (no Grafana needed)
python log_downloader.py --analyze-local "downloads/abc123_20260305/raw-logs.json"

# Analyze multiple manually downloaded files merged from a folder (*.json and *.log supported)
python log_downloader.py --analyze-folder "downloads/my-incident-folder"
```

---

## Operations

### Option A — Download and Analyze via Grafana (automated)

#### Step 1 — Run the Python Script Locally

Locate the script relative to the workspace root:
```powershell
$skillDir = "$((Get-Item (git rev-parse --show-toplevel)).Parent.FullName)\copilot-skills\conga-log-analyzer"
cd $skillDir
```

Then run the appropriate command from the Quick Start above.

After the script completes, the output folder is printed as:
```
Files saved to: downloads/<traceId>_<timestamp>/
```

---

### Option B — Analyze Multiple Manually Downloaded Files (no Grafana needed)

Use this option when you have already downloaded one or more `raw-logs.json` **or plain `.log`** files and want to analyze them together without a Grafana connection.

Supported file types in the folder:
- `*.json` — Grafana Loki raw-logs export (standard download)
- `*.log` — Lightsaber / Akka plain-text log files (e.g. Kubernetes pod logs)

All matching files in the folder are automatically merged before analysis.

#### ⚠️ Copilot Behavioral Instruction — MUST follow ALL steps below before running any script

When a user asks to analyze manually downloaded log files, Copilot MUST execute these steps in order:

**Step 1 — Create the incident sub-folder**

Ask the user for a descriptive folder name for their incident, then create the sub-folder immediately:

```powershell
$skillDir = "$((Get-Item (git rev-parse --show-toplevel)).Parent.FullName)\copilot-skills\conga-log-analyzer"
$folder = "my-incident-20260610"   # replace with the name the user provides
New-Item -ItemType Directory -Force -Path "$skillDir\downloads\$folder"
```

> Do NOT assume a folder name. Always ask the user: *"What would you like to name the folder for this incident? (e.g. `my-incident-20260610`)"*

**Step 2 — Prompt the user to place their files**

After creating the folder, tell the user:

> "The folder has been created at:
> ```
> $skillDir\downloads\<your-folder-name>\
> ```
> Please place all your downloaded log files there now.
> - You may have multiple files — rename them to avoid conflicts (e.g. `asset-api-raw-logs.json`, `renewal-api-raw-logs.json`, `cart-0.log`).
> - All `*.json` **and** `*.log` files in the folder will be automatically merged and analyzed together.
>
> Let me know when the files are in place and I will start the analysis."

**Step 3 — Wait for user confirmation**

Do NOT proceed to run `--analyze-folder` until the user explicitly confirms the files are in place.

Example folder layout after the user places their files:
```
downloads\
  my-incident-20260610\
    asset-api-raw-logs.json
    renewal-api-raw-logs.json
    objectdb-raw-logs.json
    cart-0.log
    cart-web-2.log
```

> ✅ Only after the user confirms the files are ready should Copilot proceed to Step 2 below.

#### Step 2 — Run the Script with `--analyze-folder`

```powershell
$skillDir = "$((Get-Item (git rev-parse --show-toplevel)).Parent.FullName)\copilot-skills\conga-log-analyzer"
cd $skillDir
python log_downloader.py --analyze-folder "downloads/my-incident-20260610"
```

The script will:
1. Discover all `*.json` files in the specified folder.
2. Merge their log entries into a single unified dataset.
3. Run the full analysis pipeline (errors, stack traces, performance) across all services.
4. Write the three summary files into the same folder.

After the script completes, the output is written to the same folder:
```
downloads/<your-folder-name>/summary.md
downloads/<your-folder-name>/error-analysis.md
downloads/<your-folder-name>/perf-summary.md
```

---

### Step 2 (Option A) / Step 3 (Option B) — Read Exactly These Three Files

```
downloads/<folder>/summary.md          → read this (~700 tokens)    - overview, errors, hotspots
downloads/<folder>/error-analysis.md   → read this (~2,250 tokens)  - stack traces, GitHub links
downloads/<folder>/perf-summary.md     → read this (~1,500 tokens)  - timing, slow segments, methods
```

Do NOT read any other file in the output folder — the remaining files are too large and contain no additional insight beyond what the three summaries already capture.

---

### Step 3 (both options) — Synthesize and Respond

After reading all three files, provide:

1. **Root Cause** — what failed, which service, which class/method (`error-analysis.md`)
2. **Evidence** — stack frame file + line number, GitHub link if present (`error-analysis.md`)
3. **Performance** — which service took longest, which gap was largest, any method > 500ms (`perf-summary.md`)
4. **Correlation** — connect perf hotspots to errors (e.g. "the 1.1s gap before ObjectDB failure...")
5. **Recommendation** — what to investigate or fix

---

## Constraints

- ✅ Read `summary.md`, `error-analysis.md`, and `perf-summary.md` — all three, every time
- ✅ Provide either `--trace-id`, `--loki-query`, `--analyze-local`, or `--analyze-folder` — at least one is required
- ✅ **When the user asks to analyze manually downloaded files** — Copilot MUST: (1) ask for a folder name, (2) create the sub-folder under `downloads\`, (3) prompt the user to place files there, (4) wait for confirmation before running any script
- ✅ **Never assume a folder name** — always ask the user for an incident-descriptive name before creating the folder or running `--analyze-folder`
- ✅ **Always create the sub-folder first** using `New-Item` before asking the user to place files — the folder must exist before the user can copy files into it
- ✅ When using `--analyze-folder`, all `*.json` and `*.log` files in the folder are merged before analysis
- ❌ **NEVER** proceed with `--analyze-folder` without first creating the folder, prompting the user, and receiving explicit confirmation that files are in place
- ❌ **NEVER** read `raw-logs.json` (~1.4 MB, ~350,000 tokens) — never load into LLM context
- ❌ **NEVER** read `summary.json` (~700 KB, ~179,000 tokens) — for tooling only
- ❌ **NEVER** read `timeline.md` (~193 KB, ~48,000 tokens) — use `summary.md` instead
- ❌ **NEVER** read `performance.md` (~178 KB, ~44,500 tokens) — use `perf-summary.md` instead

---

## Parameters Reference

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--trace-id` | Yes* | OpenTelemetry trace ID |
| `--environment` | No | `dev` (default), `staging`, `production`. dev/qa auto-defaults to `rls04` |
| `--deployment-env` | No | Override deployment filter (e.g. `rls04`, `rls07`) |
| `--loki-query` | Yes* | Custom Loki query (overrides `--trace-id`) |
| `--time-range` | No | Minutes of history. Default: 60 |
| `--analyze-local` | No | Path to a single `raw-logs.json` for offline re-analysis |
| `--analyze-folder` | No | Path to a folder containing `*.json` and/or `*.log` files to merge and analyze |
| `--repo-url` | No | GitHub repo URL for source links (default: `congaengr/Conga.Revenue.Renewal`) |
| `--compact` | No | Limit stack frames to top 3 (~400 tokens total) for CI pipelines |

*Provide one of: `--trace-id`, `--loki-query`, `--analyze-local`, or `--analyze-folder`

---

## Setup

1. Copy `config.template.json` to `config.json`
2. Set your Grafana API keys in `config.json` (one `apiKey` per environment)
3. Python 3.10+ required (no pip packages needed)

---

## Design Philosophy

> "Fetch once, summarize locally, read only the distilled output. Raw logs never enter the model."

| Decision | Reason |
|----------|--------|
| **Three fixed summary files** | Caps LLM context at ~4,450 tokens regardless of log volume — a 1.4 MB raw log file would consume ~350,000 tokens and still give worse signal |
| **Python stdlib only** | Zero `pip install` friction — the script runs in any Python 3.10+ environment without setup |
| **`perf-summary.md` instead of `performance.md`** | Full waterfall is ~178 KB; the summary distills the same hotspots into ~2 KB — same insight, 99% fewer tokens |
| **`--analyze-local` flag** | Enables re-analysis of a single previously downloaded `raw-logs.json` without a Grafana connection — useful for offline investigation or re-running with different parameters |
| **`--analyze-folder` flag** | Merges all `*.json` and `*.log` files from a single folder into one unified dataset before analysis — enables cross-service incident analysis from both Grafana exports and raw Kubernetes/pod `.log` files without Grafana access |
| **GitHub links in `error-analysis.md`** | Ties stack frames directly to source lines — removes the manual step of searching the repo for the failing class/method |
