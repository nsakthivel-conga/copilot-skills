"""Conga Log Analyzer - downloads Grafana Loki logs and produces structured analysis.

Output: summary.md, error-analysis.md, performance.md, timeline.md, raw-logs.json

Usage:
    python log_downloader.py --trace-id "abc123" --environment dev
    python log_downloader.py --trace-id "abc123" --environment dev --time-range 21600
    python log_downloader.py --analyze-local "downloads/abc123_20260305/raw-logs.json"

Setup: set Grafana API keys in config.json.
Requires Python 3.10+ (stdlib only).
"""

import argparse
import json
import re
import ssl
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ============================================================================
# Paths - all relative to this script's directory
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
CONFIG_TEMPLATE = SCRIPT_DIR / "config.template.json"
DOWNLOADS_DIR = SCRIPT_DIR / "downloads"


# ============================================================================
# Regex patterns used across the script
# ============================================================================

# Matches: "at Namespace.Class.Method(...) in /path/File.cs:line 123"
RE_STACK_FRAME = re.compile(
    r'at\s+([\w.<>\[\],`]+(?:\(.*?\))?)\s+in\s+(.+?):line\s+(\d+)'
)

# Matches Jenkins CI workspace prefix to strip from file paths
# Example: /home/jenkins/agent/workspace/ga.Revenue.Renewal.Worker_master/
RE_JENKINS_PREFIX = re.compile(r'.*/workspace/[^/]+/')

# Matches: "after 33.2861ms" in HTTP log messages
RE_HTTP_DURATION = re.compile(r'after\s+([\d.]+)ms')

# Matches: "33.2861ms - 201" to extract duration and HTTP status code
RE_HTTP_STATUS = re.compile(r'([\d.]+)ms\s*-\s*(\d+)')

# Matches exception type names like "PlatformException" or "System.NullReferenceException"
RE_EXCEPTION_TYPE = re.compile(r'(\w+(?:\.\w+)*(?:Exception|Error))')

# Matches the method name in "method start" log messages
# Example: "[AS]:GetAssetLineItems method start" → "GetAssetLineItems"
RE_METHOD_NAME = re.compile(r'(\w+)\s+method\s+start', re.IGNORECASE)


# ============================================================================
# Section 1: Configuration & Environment
# ============================================================================

def load_config():
    """Load config.json. Creates from template if missing."""
    if not CONFIG_FILE.exists():
        if CONFIG_TEMPLATE.exists():
            import shutil
            shutil.copy(CONFIG_TEMPLATE, CONFIG_FILE)
            print("Created config.json from template. Set your API keys and re-run.")
            sys.exit(0)
        print(f"ERROR: config.json not found at {CONFIG_FILE}")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))




# ============================================================================
# Section 2: Grafana / Loki Download
# ============================================================================

# Default deployment environment for dev/qa (most common setup)
DEFAULT_DEPLOYMENT_ENV = "rls04"


def build_loki_query(trace_id, deployment_env, custom_query, environment="dev"):
    """Build a Loki query. Defaults deployment_env to rls04 for dev/qa."""
    if custom_query:
        return custom_query
    if not trace_id:
        print("ERROR: Provide --trace-id or --loki-query")
        sys.exit(1)
    # Default to rls04 for dev/qa environments
    if not deployment_env and environment in ("dev", "qa"):
        deployment_env = DEFAULT_DEPLOYMENT_ENV
    if deployment_env:
        return f'{{deployment_environment="{deployment_env}"}} |= "{trace_id}"'
    return f'{{}} |= "{trace_id}"'


# Loki returns max ~1000 entries per request; we paginate to get more
LOKI_PAGE_SIZE = 5000


def download_logs(grafana_url, api_key, loki_query, time_range_min, max_entries):
    """Download logs from Grafana Loki with pagination (Loki caps ~1000/request)."""
    now = datetime.now(timezone.utc)
    start_ns = int((now - timedelta(minutes=time_range_min)).timestamp() * 1_000_000_000)
    end_ns = int(now.timestamp() * 1_000_000_000)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "CongaLogAnalyzer/1.0",
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    all_results = []  # Accumulate stream results across pages
    cursor_ns = start_ns
    page = 0

    print("Querying Grafana Loki...")
    while True:
        page += 1
        url = (
            f"{grafana_url}/api/datasources/proxy/6/loki/api/v1/query_range"
            f"?query={quote(loki_query)}&start={cursor_ns}&end={end_ns}"
            f"&limit={LOKI_PAGE_SIZE}&direction=forward"
        )
        try:
            with urlopen(Request(url, headers=headers), timeout=180, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            print(f"ERROR: HTTP {e.code} - {e.read().decode('utf-8', errors='replace')[:300]}")
            return None if not all_results else {"data": {"result": all_results}}
        except (URLError, TimeoutError) as e:
            print(f"ERROR: {e}")
            return None if not all_results else {"data": {"result": all_results}}

        streams = data.get("data", {}).get("result", [])
        if not streams:
            break

        # Count entries in this page and find the latest timestamp
        page_count = 0
        max_ts = cursor_ns
        for stream in streams:
            vals = stream.get("values", [])
            page_count += len(vals)
            for ts_str, _ in vals:
                max_ts = max(max_ts, int(ts_str))

        all_results.extend(streams)
        total = sum(len(s.get("values", [])) for s in all_results)
        print(f"  Page {page}: +{page_count} entries (total: {total})")

        # Stop if we got fewer than page size (no more data) or hit max
        if page_count < LOKI_PAGE_SIZE or total >= max_entries:
            break

        # Advance cursor past the latest timestamp to avoid duplicates
        cursor_ns = max_ts + 1

    if not all_results:
        return None
    return {"data": {"result": all_results}}


# ============================================================================
# Section 3: Log Parsing
# ============================================================================

def parse_loki_response(response):
    """Flatten Loki stream response into a sorted list of {TimestampNs, Timestamp, Message}."""
    entries = []
    for stream in response.get("data", {}).get("result", []):
        for ts_ns_str, message in stream.get("values", []):
            ts_ns = int(ts_ns_str)
            dt = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc)
            entries.append({
                "TimestampNs": ts_ns,
                "Timestamp": dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "Message": message,
            })

    entries.sort(key=lambda e: e["TimestampNs"])
    return entries


def parse_structured_entry(entry):
    """Parse a log entry's JSON body/attributes/resources into a flat dict."""
    try:
        parsed = json.loads(entry["Message"])
    except (json.JSONDecodeError, TypeError):
        return None

    body = parsed.get("body", {})
    attrs = parsed.get("attributes", {})
    resources = parsed.get("resources", {})

    # Body can be a dict with "message" key, or a plain string
    message = body.get("message", body) if isinstance(body, dict) else str(body)

    class_name = attrs.get("ClassName", "")
    return {
        "timestamp": entry["Timestamp"],
        "timestamp_ns": entry["TimestampNs"],
        "service": resources.get("service.name", "unknown"),
        "severity": attrs.get("SeverityText", "unknown"),
        "class_full": class_name,
        "class_short": class_name.rsplit(".", 1)[-1] if class_name else "",
        "method": attrs.get("MethodName", ""),
        "message": str(message),
        "span_id": parsed.get("spanid", ""),
        "trace_id": parsed.get("traceid", ""),
        "exception_type": attrs.get("exception_type", ""),
        "exception_stacktrace": attrs.get("exception_stacktrace", ""),
    }


# ============================================================================
# Section 4: Analysis - Statistics
# ============================================================================

def build_analysis(entries):
    """Parse raw entries into timeline and compute service/error/severity stats."""
    # Parse each raw entry into a structured dict
    timeline = []
    for entry in entries:
        parsed = parse_structured_entry(entry)
        if parsed:
            timeline.append(parsed)

    if not timeline:
        return None

    # Count entries per service, class, and severity
    services = {}
    classes = {}
    severity_counts = {}
    errors = []

    for row in timeline:
        services[row["service"]] = services.get(row["service"], 0) + 1

        if row["class_full"]:
            classes[row["class_full"]] = classes.get(row["class_full"], 0) + 1

        severity_counts[row["severity"]] = severity_counts.get(row["severity"], 0) + 1

        if row["severity"] in ("Error", "Fatal", "Critical"):
            errors.append(row)

    # Calculate first/last timestamp and accumulated active duration per service.
    # A service may be active in multiple segments (e.g. 0-10s and 50-60s in a 60s trace),
    # so we sum only the gaps between consecutive entries of the same service rather than
    # using the raw first-to-last span, which would include idle time between segments.
    service_timing = {}
    for row in timeline:
        svc = row["service"]
        if svc not in service_timing:
            service_timing[svc] = {
                "first": row["timestamp"], "first_ns": row["timestamp_ns"],
                "last": row["timestamp"], "last_ns": row["timestamp_ns"],
                "_active_ns": 0,
                "_prev_ns": row["timestamp_ns"],
            }
        else:
            gap_ns = row["timestamp_ns"] - service_timing[svc]["_prev_ns"]
            service_timing[svc]["_active_ns"] += gap_ns
            service_timing[svc]["last"] = row["timestamp"]
            service_timing[svc]["last_ns"] = row["timestamp_ns"]
            service_timing[svc]["_prev_ns"] = row["timestamp_ns"]

    for timing in service_timing.values():
        timing["duration_sec"] = round(timing["_active_ns"] / 1_000_000_000, 3)
        del timing["_active_ns"], timing["_prev_ns"]

    # Overall trace duration
    duration_sec = round(
        (timeline[-1]["timestamp_ns"] - timeline[0]["timestamp_ns"]) / 1_000_000_000, 3
    )

    return {
        "total": len(timeline),
        "first": timeline[0]["timestamp"],
        "last": timeline[-1]["timestamp"],
        "duration_sec": duration_sec,
        "services": services,
        "service_timing": service_timing,
        "severity_counts": severity_counts,
        "classes": classes,
        "error_count": len(errors),
        "errors": errors,
        "timeline": timeline,
    }


# ============================================================================
# Section 5: Analysis - Error Details
# ============================================================================

def extract_error_details(timeline, repo_url):
    """Two-pass error enrichment: extract stack traces, exception types, GitHub links.

    Pass 1: Scan all entries for embedded ErrorDetails/StackTrace (often at Info level).
    Pass 2: Build enriched errors from Error-severity entries, attaching Pass 1 traces.
    """
    # --- Pass 1: Collect stack traces from job status responses ---
    # Job status messages (Info severity) often contain the actual ErrorDetails
    # with StackTrace, while the Error entries just say "Message processing failed"
    job_error_details = {}
    for row in timeline:
        msg = row["message"]
        has_attr_trace = bool(row.get("exception_stacktrace"))
        if not has_attr_trace and "ErrorDetails" not in msg and "StackTrace" not in msg and "Exception" not in msg and "Error while" not in msg:
            continue

        temp = _new_error_fields()

        # Use attribute-level stack trace when present
        if has_attr_trace:
            if row.get("exception_type"):
                temp["exception_type"] = row["exception_type"]
            _parse_stack_trace(row["exception_stacktrace"], temp, repo_url)
            temp["error_stage"] = row["class_short"] or row["method"] or "unknown"
            temp["nested_message"] = row["exception_stacktrace"].splitlines()[0][:300]
        else:
            _extract_nested_error(msg, temp, repo_url)

        if temp["stack_frames"] or temp["error_stage"]:
            stage = temp["error_stage"] or "unknown"
            job_error_details[stage] = temp

    # --- Pass 2: Build enriched errors from Error-severity entries ---
    enriched_errors = []
    used_stages = set()  # Track which job error details have been assigned

    for row in timeline:
        if row["severity"] not in ("Error", "Fatal", "Critical"):
            continue

        error_info = {**row, **_new_error_fields()}

        # Priority 1: use exception_type / exception_stacktrace attributes directly
        if row.get("exception_type"):
            error_info["exception_type"] = row["exception_type"]
        if row.get("exception_stacktrace"):
            _parse_stack_trace(row["exception_stacktrace"], error_info, repo_url)
            error_info["nested_message"] = row["exception_stacktrace"].splitlines()[0][:300]

        # Priority 2: try extracting error details from the error message itself
        if not error_info["stack_frames"]:
            _extract_nested_error(row["message"], error_info, repo_url)

        # If this error has no stack trace, try to attach one from Pass 1
        if not error_info["stack_frames"] and job_error_details:
            for stage, details in job_error_details.items():
                if stage not in used_stages:
                    error_info.update({
                        "error_stage": details["error_stage"],
                        "error_type": details["error_type"],
                        "stack_frames": details["stack_frames"],
                        "nested_message": details["nested_message"],
                    })
                    if details["exception_type"]:
                        error_info["exception_type"] = details["exception_type"]
                    used_stages.add(stage)
                    break

        # Last resort: extract exception type from the raw message text
        if not error_info["exception_type"]:
            match = RE_EXCEPTION_TYPE.search(row["message"])
            if match:
                error_info["exception_type"] = match.group(1)

        enriched_errors.append(error_info)

    # Pass 3: Surface any Information-level exceptions that were never attached
    # to an Error-severity entry (i.e., the only evidence of the failure is an Info log)
    for stage, details in job_error_details.items():
        if stage not in used_stages:
            error_info = {
                "severity": "Information",
                "service": "",
                "class_full": "",
                "class_short": "",
                "method": "",
                "message": details.get("nested_message", ""),
                "timestamp": "",
                "timestamp_ns": 0,
                **details,
            }
            enriched_errors.append(error_info)

    return enriched_errors


def _new_error_fields():
    """Return a dict with default values for error enrichment fields."""
    return {
        "exception_type": "",
        "error_stage": "",
        "error_type": "",
        "stack_frames": [],
        "nested_message": "",
    }


def _extract_nested_error(msg, error_info, repo_url):
    """Peel nested JSON layers: message → JobResponse → ErrorDetails → StackTrace."""
    search_texts = [msg]

    # Pattern 1: JobResponse is a JSON string containing ErrorDetails
    # Pattern 2: ErrorDetails is directly in the message
    patterns = [
        r'"JobResponse"\s*:\s*"(.+?)"(?=\s*[,}])',
        r'"ErrorDetails"\s*:\s*(\{.+?\})',
    ]

    for pattern in patterns:
        for text in list(search_texts):
            for match in re.findall(pattern, text):
                try:
                    # Unescape the nested JSON string
                    unescaped = (match
                                 .replace('\\\\n', '\n')
                                 .replace('\\"', '"')
                                 .replace('\\n', '\n'))
                    if not unescaped.startswith('{'):
                        continue

                    parsed = json.loads(unescaped)
                    search_texts.append(json.dumps(parsed))

                    # Extract ErrorDetails if present
                    if "ErrorDetails" in parsed:
                        _fill_from_error_details(parsed["ErrorDetails"], error_info, repo_url)
                    elif "Stage" in parsed and "StackTrace" in parsed:
                        _fill_from_error_details(parsed, error_info, repo_url)
                except (json.JSONDecodeError, TypeError):
                    pass

    # Fallback: search the raw message for stack trace frames directly
    if not error_info["stack_frames"]:
        _parse_stack_trace(msg, error_info, repo_url)


def _fill_from_error_details(error_details, error_info, repo_url):
    """Populate error_info from an ErrorDetails dict (Stage, Message, StackTrace)."""
    error_info["error_stage"] = error_details.get("Stage", "")
    error_info["error_type"] = error_details.get("ErrorType", "")
    error_info["nested_message"] = error_details.get("Message", "")

    stack_trace = error_details.get("StackTrace", "")
    if stack_trace:
        _parse_stack_trace(stack_trace, error_info, repo_url)


def _parse_stack_trace(text, error_info, repo_url):
    """Extract .NET stack frames, strip Jenkins prefix, generate GitHub URLs."""
    for match in RE_STACK_FRAME.finditer(text):
        method = match.group(1)
        file_path = match.group(2)
        line_num = int(match.group(3))

        # Strip Jenkins CI path prefix to get repo-relative path
        # e.g. /home/jenkins/agent/workspace/ga.Revenue.Renewal.Worker_master/
        #      becomes Conga.Revenue.Renewal.Worker/Processors/File.cs
        rel_path = RE_JENKINS_PREFIX.sub('', file_path)

        # Generate GitHub URL if we successfully stripped the prefix
        github_url = ""
        if repo_url and rel_path != file_path:
            github_url = f"{repo_url.rstrip('/')}/blob/master/{rel_path}#L{line_num}"

        error_info["stack_frames"].append({
            "method": method,
            "file": rel_path,
            "line": line_num,
            "github_url": github_url,
        })


# ============================================================================
# Section 6: Analysis - Performance
# ============================================================================

def extract_performance_data(timeline):
    """Compute timing deltas, extract HTTP durations, find slow segments."""
    segments = []
    http_calls = []

    for i, row in enumerate(timeline):
        # Time since previous log entry (0 for the first entry)
        delta_ms = 0
        if i > 0:
            delta_ms = round(
                (row["timestamp_ns"] - timeline[i - 1]["timestamp_ns"]) / 1_000_000, 1
            )

        segments.append({
            "index": i,
            "timestamp": row["timestamp"],
            "service": row["service"],
            "class_short": row["class_short"],
            "method": row["method"],
            "message_preview": row["message"][:100],
            "delta_ms": delta_ms,
        })

        # Check if this message contains an HTTP call duration
        msg = row["message"]
        dur_match = RE_HTTP_DURATION.search(msg)
        if dur_match and ("End processing" in msg or "Received HTTP" in msg):
            duration_ms = float(dur_match.group(1))

            # Try to extract the target URL from the message
            url_part = ""
            url_match = re.search(r'(http\S+)', msg)
            if url_match:
                url_part = url_match.group(1)[:80]

            # Try to extract the HTTP status code
            status = ""
            status_match = RE_HTTP_STATUS.search(msg)
            if status_match:
                status = status_match.group(2)

            http_calls.append({
                "timestamp": row["timestamp"],
                "service": row["service"],
                "class_short": row["class_short"],
                "duration_ms": duration_ms,
                "url": url_part,
                "status": status,
                "type": "response" if "Received" in msg else "complete",
            })

    # Top 10 slowest gaps between consecutive entries
    slow_segments = sorted(
        [s for s in segments if s["delta_ms"] > 0],
        key=lambda x: -x["delta_ms"],
    )[:10]

    # Total time attributed to each service.
    # Only accumulate delta_ms when the previous entry belongs to the same service,
    # so inter-service wait time is not incorrectly credited to the next service that logs.
    service_time = {}
    for i, s in enumerate(segments):
        svc = s["service"]
        delta = s["delta_ms"] if i > 0 and segments[i - 1]["service"] == svc else 0
        service_time[svc] = service_time.get(svc, 0) + delta

    # --- Span-based method call correlation ---
    # Match "method start" → "method end" pairs using spanid as the correlation key.
    # Each unique spanid represents one invocation, so 10 calls to GetAssetLineItems
    # produce 10 independent start/end pairs with separate spanids.
    span_starts = {}   # span_id → start row
    method_calls = []  # completed matched pairs

    for row in timeline:
        span = row.get("span_id", "")
        if not span:
            continue
        msg_lower = row["message"].lower()
        if "method start" in msg_lower:
            span_starts[span] = row
        elif "method end" in msg_lower and span in span_starts:
            start_row = span_starts.pop(span)
            duration_ms = round(
                (row["timestamp_ns"] - start_row["timestamp_ns"]) / 1_000_000, 3
            )
            name_match = RE_METHOD_NAME.search(start_row["message"])
            method_name = name_match.group(1) if name_match else start_row["message"][:50]
            method_calls.append({
                "span_id":     span,
                "method_name": method_name,
                "service":     row["service"],
                "start":       start_row["timestamp"],
                "end":         row["timestamp"],
                "duration_ms": duration_ms,
            })

    # Aggregate per method name: call count, total/avg/min/max duration
    method_stats = {}
    for call in method_calls:
        name = call["method_name"]
        if name not in method_stats:
            method_stats[name] = {
                "method_name": name,
                "service":     call["service"],
                "call_count":  0,
                "total_ms":    0.0,
                "min_ms":      float("inf"),
                "max_ms":      0.0,
            }
        s = method_stats[name]
        s["call_count"] += 1
        s["total_ms"]   += call["duration_ms"]
        s["min_ms"]      = min(s["min_ms"], call["duration_ms"])
        s["max_ms"]      = max(s["max_ms"], call["duration_ms"])

    for s in method_stats.values():
        s["avg_ms"]   = round(s["total_ms"] / s["call_count"], 3)
        s["total_ms"] = round(s["total_ms"], 3)
        s["min_ms"]   = round(s["min_ms"], 3)

    return {
        "segments": segments,
        "http_calls": http_calls,
        "slow_segments": slow_segments,
        "service_time_ms": {
            k: round(v, 1)
            for k, v in sorted(service_time.items(), key=lambda x: -x[1])
        },
        "method_calls": method_calls,
        "method_stats": method_stats,
    }


# ============================================================================
# Section 7: Output Writers
# ============================================================================

def write_summary_md(analysis, perf_data, error_details, out_dir):
    """Write summary.md — ~3KB overview: services, errors, hotspots, HTTP calls."""
    lines = ["# Log Analysis Summary\n"]

    # --- Overview stats ---
    lines.append(f"- **Total entries:** {analysis['total']}")
    lines.append(f"- **Time range:** {analysis['first']} to {analysis['last']} ({analysis['duration_sec']}s)")
    lines.append(f"- **Services:** {len(analysis['services'])}")
    lines.append(f"- **Errors:** {analysis['error_count']}")
    lines.append(f"- **Severity:** {', '.join(f'{k}: {v}' for k, v in analysis['severity_counts'].items())}\n")

    # --- Service breakdown ---
    lines.append("## Services\n")
    lines.append("| Service | Entries | Duration | Time Spent |")
    lines.append("|---------|---------|----------|------------|")
    for svc, count in sorted(analysis["services"].items(), key=lambda x: -x[1]):
        t = analysis["service_timing"][svc]
        time_ms = perf_data["service_time_ms"].get(svc, 0)
        lines.append(f"| {svc} | {count} | {t['duration_sec']}s | {time_ms}ms |")

    # --- Error root cause (top 3 unique stages) ---
    if error_details:
        lines.append("\n## Error Root Cause\n")
        seen = set()
        for e in error_details[:3]:
            stage = e["error_stage"] or e["class_short"]
            if stage in seen:
                continue
            seen.add(stage)
            lines.append(f"**{e['exception_type'] or 'Error'} at {stage}**")
            if e["stack_frames"]:
                top = e["stack_frames"][-1]
                lines.append(f"- Source: `{top['file']}:{top['line']}`")
                if top["github_url"]:
                    lines.append(f"- GitHub: {top['github_url']}")
            if e["nested_message"]:
                lines.append(f"- Message: {e['nested_message'][:200]}")
            lines.append("")

    # --- Performance hotspots (top 5 slowest gaps) ---
    if perf_data["slow_segments"]:
        lines.append("## Performance Hotspots\n")
        lines.append("| Gap | Service | Class | Action |")
        lines.append("|-----|---------|-------|--------|")
        for s in perf_data["slow_segments"][:5]:
            gap = f"{s['delta_ms']}ms" if s["delta_ms"] < 1000 else f"{round(s['delta_ms'] / 1000, 1)}s"
            lines.append(f"| **{gap}** | {s['service']} | {s['class_short']} | {s['message_preview'][:60]} |")

    # --- HTTP calls (top 5 slowest) ---
    if perf_data["http_calls"]:
        lines.append("\n## HTTP Calls\n")
        lines.append("| Duration | Service | Status | URL |")
        lines.append("|----------|---------|--------|-----|")
        for h in sorted(perf_data["http_calls"], key=lambda x: -x["duration_ms"])[:5]:
            lines.append(f"| {h['duration_ms']}ms | {h['service']} | {h['status']} | {h['url'][:60]} |")

    # --- Method call summary (top 5 by total time) ---
    if perf_data["method_stats"]:
        lines.append("\n## Method Calls\n")
        lines.append("| Method | Calls | Total | Avg | Max |")
        lines.append("|--------|-------|-------|-----|-----|")
        for s in sorted(perf_data["method_stats"].values(), key=lambda x: -x["total_ms"])[:5]:
            lines.append(
                f"| {s['method_name']} | {s['call_count']} |"
                f" {s['total_ms']}ms | {s['avg_ms']}ms | {s['max_ms']}ms |"
            )

    # --- Pointers to detail files ---
    lines.append("\n## Detail Files\n")
    if error_details:
        lines.append(f"- **error-analysis.md** - {len(error_details)} errors with stack traces and GitHub links")
    lines.append(f"- **performance.md** - {len(perf_data['http_calls'])} HTTP calls, slow segments, waterfall")
    lines.append(f"- **timeline.md** - All {analysis['total']} entries chronologically")
    lines.append("- **raw-logs.json** - Complete raw data")

    md = "\n".join(lines)
    (out_dir / "summary.md").write_text(md, encoding="utf-8")
    return md


def write_error_analysis_md(error_details, out_dir, repo_url, compact=False):
    """Write error-analysis.md — stack traces, GitHub links, exception details.

    compact=True: limits stack frames to top 3 and skips raw message body,
    keeping the file small (~400 tokens) for LLM consumption.
    compact=False (default): full output for human browsing.
    """
    if not error_details:
        return

    lines = [f"# Error Analysis ({len(error_details)} errors)\n"]
    if repo_url:
        lines.append(f"Repository: {repo_url}\n")
    if compact:
        lines.append("_Compact mode: top 3 stack frames only. Re-run without --compact for full output._\n")

    for i, e in enumerate(error_details, 1):
        lines.append(f"## Error {i} - [{e['timestamp']}]\n")
        lines.append(f"- **Service:** {e['service']}")
        lines.append(f"- **Class:** {e['class_full']}")
        lines.append(f"- **Method:** {e['method']}")
        if e["exception_type"]:
            lines.append(f"- **Exception:** {e['exception_type']}")
        if e["error_stage"]:
            lines.append(f"- **Stage:** {e['error_stage']}")
        if e["error_type"]:
            lines.append(f"- **Error Type:** {e['error_type']}")

        # Nested error message (from ErrorDetails)
        if e["nested_message"]:
            lines.append("\n### Error Message\n")
            msg_limit = 200 if compact else 1000
            lines.append(f"```\n{e['nested_message'][:msg_limit]}\n```")

        # Stack trace with GitHub links (">>>" marks the top frame)
        if e["stack_frames"]:
            lines.append("\n### Stack Trace\n")
            frames = e["stack_frames"][-3:] if compact else e["stack_frames"]
            for j, frame in enumerate(frames):
                prefix = ">>>" if j == len(frames) - 1 else "   "
                lines.append(f"{prefix} `{frame['file']}:{frame['line']}` - {frame['method']}")
                if frame["github_url"]:
                    lines.append(f"    {frame['github_url']}")
            if compact and len(e["stack_frames"]) > 3:
                lines.append(f"   _...{len(e['stack_frames']) - 3} more frames omitted (compact mode)_")

        # Full raw message — skipped in compact mode
        if not compact:
            lines.append("\n### Full Message\n")
            lines.append(f"```\n{e['message'][:2000]}\n```\n")

        lines.append("")

    (out_dir / "error-analysis.md").write_text("\n".join(lines), encoding="utf-8")


def write_perf_summary_md(perf_data, analysis, out_dir):
    """Write perf-summary.md — compact ~1.5KB performance distillation for LLM consumption.

    Deliberately excludes the full waterfall (178KB) and per-call detail.
    Contains only: service time, top 5 slow segments, top 5 method calls, HTTP calls.
    Target: ~1,500 tokens — safe to include alongside summary.md + error-analysis.md.
    """
    lines = [
        "# Performance Summary (LLM-optimised)\n",
        f"Trace duration: **{analysis['duration_sec']}s** | Entries: {analysis['total']}\n",
    ]

    # --- Service time breakdown ---
    lines.append("## Time by Service\n")
    lines.append("| Service | Time Spent | % of Total |")
    lines.append("|---------|-----------|------------|")
    total_ms = sum(perf_data["service_time_ms"].values()) or 1
    for svc, ms in perf_data["service_time_ms"].items():
        pct = round(ms / total_ms * 100, 1)
        display = f"{ms}ms" if ms < 1000 else f"{round(ms / 1000, 1)}s"
        lines.append(f"| {svc} | {display} | {pct}% |")

    # --- Top 5 slow segments (the biggest time gaps — where work actually happened) ---
    if perf_data["slow_segments"]:
        lines.append("\n## Slow Segments (top 5 gaps between log entries)\n")
        lines.append("> A large gap = the service was doing silent work (DB call, HTTP, CPU)\n")
        lines.append("| Gap | Service | Class | What logged after the gap |")
        lines.append("|-----|---------|-------|--------------------------|")
        for s in perf_data["slow_segments"][:5]:
            gap = f"{s['delta_ms']}ms" if s["delta_ms"] < 1000 else f"{round(s['delta_ms'] / 1000, 1)}s"
            lines.append(
                f"| **{gap}** | {s['service']} | {s['class_short']} "
                f"| {s['message_preview'][:80]} |"
            )

    # --- Method call summary (span-correlated start/end pairs) ---
    if perf_data["method_stats"]:
        lines.append(f"\n## Method Durations ({len(perf_data['method_calls'])} matched calls)\n")
        lines.append("| Method | Service | Calls | Total | Avg | Max |")
        lines.append("|--------|---------|-------|-------|-----|-----|")
        for s in sorted(perf_data["method_stats"].values(), key=lambda x: -x["total_ms"])[:5]:
            lines.append(
                f"| {s['method_name']} | {s['service']} | {s['call_count']} |"
                f" {s['total_ms']}ms | {s['avg_ms']}ms | {s['max_ms']}ms |"
            )

    # --- HTTP calls (if any) ---
    if perf_data["http_calls"]:
        lines.append(f"\n## HTTP Calls ({len(perf_data['http_calls'])} total)\n")
        lines.append("| Duration | Service | Status | URL |")
        lines.append("|----------|---------|--------|-----|")
        for h in sorted(perf_data["http_calls"], key=lambda x: -x["duration_ms"])[:5]:
            lines.append(
                f"| {h['duration_ms']}ms | {h['service']} | {h['status']} | {h['url'][:70]} |"
            )
    else:
        lines.append("\n_No HTTP calls detected in this trace._\n")

    lines.append(
        "\n> Full waterfall with all entries: see `performance.md` (not for LLM — 178KB)"
    )

    (out_dir / "perf-summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_performance_md(perf_data, analysis, out_dir):
    """Write performance.md — time by service, HTTP calls, slow segments, waterfall."""
    lines = [
        "# Performance Analysis\n",
        f"Total duration: {analysis['duration_sec']}s | Entries: {analysis['total']}\n",
    ]

    # --- Time by service ---
    lines.append("## Time by Service\n")
    lines.append("| Service | Time Spent | % of Total |")
    lines.append("|---------|-----------|------------|")
    total_ms = sum(perf_data["service_time_ms"].values()) or 1
    for svc, ms in perf_data["service_time_ms"].items():
        pct = round(ms / total_ms * 100, 1)
        display = f"{ms}ms" if ms < 1000 else f"{round(ms / 1000, 1)}s"
        lines.append(f"| {svc} | {display} | {pct}% |")

    # --- HTTP calls sorted by duration ---
    if perf_data["http_calls"]:
        lines.append(f"\n## HTTP Calls ({len(perf_data['http_calls'])} total)\n")
        lines.append("| Timestamp | Duration | Service | Status | URL |")
        lines.append("|-----------|----------|---------|--------|-----|")
        for h in sorted(perf_data["http_calls"], key=lambda x: -x["duration_ms"]):
            lines.append(f"| {h['timestamp']} | {h['duration_ms']}ms | {h['service']} | {h['status']} | {h['url'][:70]} |")

    # --- Slow segments (largest time gaps between consecutive entries) ---
    if perf_data["slow_segments"]:
        lines.append(f"\n## Slow Segments (top {len(perf_data['slow_segments'])} gaps)\n")
        lines.append("| Gap | Timestamp | Service | Class | What Happened |")
        lines.append("|-----|-----------|---------|-------|---------------|")
        for s in perf_data["slow_segments"]:
            gap = f"{s['delta_ms']}ms" if s["delta_ms"] < 1000 else f"{round(s['delta_ms'] / 1000, 1)}s"
            lines.append(f"| **{gap}** | {s['timestamp']} | {s['service']} | {s['class_short']} | {s['message_preview'][:70]} |")

    # --- Method call analysis (spanid-correlated start/end pairs) ---
    if perf_data["method_stats"]:
        lines.append(f"\n## Method Call Analysis ({len(perf_data['method_calls'])} matched calls)\n")
        lines.append("| Method | Service | Calls | Total | Avg | Min | Max |")
        lines.append("|--------|---------|-------|-------|-----|-----|-----|")
        for s in sorted(perf_data["method_stats"].values(), key=lambda x: -x["total_ms"]):
            lines.append(
                f"| {s['method_name']} | {s['service']} | {s['call_count']} |"
                f" {s['total_ms']}ms | {s['avg_ms']}ms | {s['min_ms']}ms | {s['max_ms']}ms |"
            )

        # Per-call detail for each method
        lines.append(f"\n### Per-Call Detail\n")
        for call in sorted(perf_data["method_calls"], key=lambda x: -x["duration_ms"]):
            lines.append(
                f"- **{call['method_name']}** | span `{call['span_id']}` | "
                f"{call['start']} → {call['end']} | **{call['duration_ms']}ms**"
            )

    # --- Full waterfall (every entry with delta from previous) ---
    lines.append(f"\n## Waterfall ({analysis['total']} entries)\n")
    lines.append("```")
    lines.append(f"{'Delta':<10} {'Timestamp':<24} {'Service':<28} {'Class':<30} Message")
    lines.append("-" * 150)
    for s in perf_data["segments"]:
        delta_str = f"+{s['delta_ms']}ms" if s["delta_ms"] > 0 else ""
        lines.append(
            f"{delta_str:<10} {s['timestamp']:<24} {s['service']:<28} "
            f"{s['class_short']:<30} {s['message_preview'][:60]}"
        )
    lines.append("```")

    (out_dir / "performance.md").write_text("\n".join(lines), encoding="utf-8")


def write_timeline_md(analysis, out_dir):
    """Write timeline.md — full chronological log."""
    lines = [f"# Timeline ({analysis['total']} entries)\n", "```"]
    lines.append(f"{'Timestamp':<24} {'Service':<28} {'Sev':<12} {'Class':<40} Message")
    lines.append("-" * 150)
    for e in analysis["timeline"]:
        lines.append(
            f"{e['timestamp']:<24} {e['service']:<28} {e['severity']:<12} "
            f"{e['class_short']:<40} {e['message'][:80]}"
        )
    lines.append("```")

    (out_dir / "timeline.md").write_text("\n".join(lines), encoding="utf-8")


# ============================================================================
# Section 8: Orchestration
# ============================================================================

def analyze_local(raw_logs_path):
    """Load a local raw-logs.json for analysis (no Grafana needed)."""
    raw_path = Path(raw_logs_path)
    if not raw_path.exists():
        print(f"ERROR: File not found: {raw_path}")
        sys.exit(1)

    out_dir = raw_path.parent
    print(f"Analyzing local file: {raw_path}")

    entries = json.loads(raw_path.read_text(encoding="utf-8"))
    print(f"Found {len(entries)} log entries")

    if not entries:
        print("No entries in file.")
        sys.exit(0)

    return entries, out_dir


# ============================================================================
# Section 9: Plain .log file parser (Lightsaber / Akka format)
# ============================================================================

# Matches: [INFO][05/08/2026 20:22:17.549Z][Thread 0047][actor-path] message
RE_PLAIN_LOG = re.compile(
    r'^\[(?P<level>\w+)\]\[(?P<ts>\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+Z)\]'
    r'\[Thread\s+(?P<thread>\w+)\]\[(?P<actor>[^\]]*)\]\s*(?P<msg>.*)',
    re.DOTALL,
)

# Exception/stack-frame continuation lines (no leading bracket)
RE_STACK_CONTINUATION = re.compile(r'^\s+(at\s+\S+|Cause:|System\.|Apttus\.|Conga\.)')

_LEVEL_MAP = {
    "INFO":    "Information",
    "DEBUG":   "Debug",
    "WARN":    "Warning",
    "WARNING": "Warning",
    "ERROR":   "Error",
    "FATAL":   "Fatal",
}


def parse_plain_log_entries(file_path: Path) -> list[dict]:
    """Parse a Lightsaber/Akka plain-text .log file into the same entry schema
    used by parse_loki_response() so it can flow through the existing pipeline.

    Entry format:
        [LEVEL][MM/DD/YYYY HH:MM:SS.mmmZ][Thread NNNN][actor-path] message
        (continuation lines with stack frames or 'Cause:' are appended to the message)

    Returns a list of dicts with keys: TimestampNs, Timestamp, Message (JSON).
    The Message is a synthetic JSON body that parse_structured_entry() can decode.
    """
    entries = []
    text = file_path.read_text(encoding="utf-8", errors="replace")

    # Split into logical log records: each record starts with a '[LEVEL][' header.
    # Continuation lines (stack frames, Cause:) are folded into the previous record.
    records: list[tuple[str, str, str, str, list[str]]] = []  # (level, ts, thread, actor, lines)
    for raw_line in text.splitlines():
        m = RE_PLAIN_LOG.match(raw_line)
        if m:
            records.append((
                m.group("level"),
                m.group("ts"),
                m.group("thread"),
                m.group("actor"),
                [m.group("msg")],
            ))
        elif records and RE_STACK_CONTINUATION.match(raw_line):
            records[-1][4].append(raw_line.rstrip())

    # Derive service name from the file stem: "cart-0_cart (4)" → "cart-0"
    # and "cart-web-2_cart-web (1)" → "cart-web-2"
    stem = file_path.stem  # e.g. "cart-0_cart (4)"
    service_name = stem.split("_")[0] if "_" in stem else stem

    for level, ts_str, thread, actor, msg_lines in records:
        # Parse timestamp → nanoseconds (used for sorting)
        try:
            dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        ts_ns = int(dt.timestamp() * 1_000_000_000)
        ts_fmt = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        full_msg = "\n".join(msg_lines).strip()

        # Detect exception stack in continuation lines
        exception_type = ""
        exception_stacktrace = ""
        stack_lines = [l for l in msg_lines[1:] if l.strip()]
        if stack_lines:
            exception_stacktrace = "\n".join(stack_lines)
            # Try to extract exception type from "Cause: Some.Exception: ..."
            cause_match = re.search(r'Cause:\s*([\w.]+(?:Exception|Error))', exception_stacktrace)
            if cause_match:
                exception_type = cause_match.group(1)
            else:
                exc_match = RE_EXCEPTION_TYPE.search(exception_stacktrace)
                if exc_match:
                    exception_type = exc_match.group(1)

        # Derive a short class name from the actor path
        # e.g. "akka.tcp://lightsaber@.../CartActor/4/..." → "CartActor"
        class_name = ""
        actor_parts = actor.split("/")
        for part in reversed(actor_parts):
            if part and not part.isdigit() and part not in ("user", "system", "sharding"):
                class_name = part.split("@")[0] if "@" in part else part
                break

        # Build a synthetic JSON body that parse_structured_entry() can read
        body = {
            "body": {"message": full_msg},
            "attributes": {
                "SeverityText": _LEVEL_MAP.get(level.upper(), level),
                "ClassName": class_name,
                "MethodName": "",
                "exception_type": exception_type,
                "exception_stacktrace": exception_stacktrace,
            },
            "resources": {
                "service.name": service_name,
            },
            "spanid": "",
            "traceid": "",
        }

        entries.append({
            "TimestampNs": ts_ns,
            "Timestamp": ts_fmt,
            "Message": json.dumps(body, ensure_ascii=False),
        })

    return entries


# ============================================================================
# Section 10: Folder-based multi-file analysis (*.json + *.log)
# ============================================================================

def analyze_folder(folder_path: str) -> tuple[list[dict], Path]:
    """Merge all *.json and *.log files in a folder into one entry list.

    *.json files are assumed to be Grafana raw-logs.json format.
    *.log files are parsed with parse_plain_log_entries().
    Entries from all files are merged and sorted by timestamp before analysis.
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        print(f"ERROR: Folder not found: {folder}")
        sys.exit(1)

    json_files = sorted(folder.glob("*.json"))
    log_files  = sorted(folder.glob("*.log"))

    if not json_files and not log_files:
        print(f"ERROR: No *.json or *.log files found in {folder}")
        sys.exit(1)

    all_entries: list[dict] = []

    for jf in json_files:
        print(f"  [json] Loading {jf.name} ...")
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            # Grafana raw-logs.json is a list of {TimestampNs, Timestamp, Message}
            if isinstance(data, list):
                all_entries.extend(data)
            # Loki raw API response ({"data": {"result": [...]}})
            elif isinstance(data, dict) and "data" in data:
                all_entries.extend(parse_loki_response(data))
            else:
                print(f"    WARNING: Unrecognised JSON structure in {jf.name} — skipping")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"    WARNING: Could not read {jf.name}: {exc}")

    for lf in log_files:
        print(f"  [log]  Parsing {lf.name} ...")
        try:
            parsed = parse_plain_log_entries(lf)
            print(f"         -> {len(parsed)} entries")
            all_entries.extend(parsed)
        except OSError as exc:
            print(f"    WARNING: Could not read {lf.name}: {exc}")

    if not all_entries:
        print("ERROR: No log entries found in any file.")
        sys.exit(1)

    # Sort merged entries by timestamp (nanoseconds) for a coherent timeline
    all_entries.sort(key=lambda e: e["TimestampNs"])

    print(f"\nMerged {len(all_entries)} entries from "
          f"{len(json_files)} JSON + {len(log_files)} .log files")

    return all_entries, folder


def run_analysis(entries, out_dir, repo_url="", compact=False):
    """Full pipeline: parse → errors → perf → write all output files."""
    if compact:
        print("[compact mode] error-analysis.md capped to 3 frames — ~400 tokens for LLM use")
    analysis = build_analysis(entries)
    if not analysis:
        print("Could not parse any structured log entries.")
        sys.exit(0)

    # Extract enriched error and performance data
    error_details = extract_error_details(analysis["timeline"], repo_url)
    perf_data = extract_performance_data(analysis["timeline"])

    # Write raw analysis JSON for programmatic access
    (out_dir / "summary.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Write tiered output files
    summary_md = write_summary_md(analysis, perf_data, error_details, out_dir)
    print(f"\n{summary_md}")

    write_error_analysis_md(error_details, out_dir, repo_url, compact=compact)
    write_perf_summary_md(perf_data, analysis, out_dir)
    write_performance_md(perf_data, analysis, out_dir)
    write_timeline_md(analysis, out_dir)

    # Print file listing with sizes
    print(f"\nFiles saved to: {out_dir}")
    for f in sorted(out_dir.iterdir()):
        size_kb = round(f.stat().st_size / 1024, 1)
        print(f"  {f.name:<24} {size_kb:>8} KB")

    # Explicit LLM read instructions — Copilot reads terminal output and must follow these
    print(f"\n{'-' * 60}")
    print("COPILOT: Read ONLY these three files for analysis:")
    print(f"  {out_dir / 'summary.md'}          (~700 tokens)")
    print(f"  {out_dir / 'error-analysis.md'}   (~2,250 tokens)")
    print(f"  {out_dir / 'perf-summary.md'}      (~1,500 tokens)")
    print("DO NOT read: raw-logs.json, summary.json, timeline.md, performance.md")
    print(f"{'-' * 60}")


# ============================================================================
# Section 9: CLI Entry Point
# ============================================================================

def main():
    """CLI entry point: download from Grafana or analyze a local file."""
    parser = argparse.ArgumentParser(
        description="Download Grafana Loki logs and produce structured analysis"
    )
    parser.add_argument("--trace-id", help="OpenTelemetry TraceId to search for")
    parser.add_argument("--environment", choices=["dev", "staging", "production"], default="dev",
                        help="Target environment (default: dev)")
    parser.add_argument("--deployment-env", help="Deployment filter, e.g. rls04")
    parser.add_argument("--loki-query", help="Custom Loki query (overrides --trace-id)")
    parser.add_argument("--time-range", type=int, default=0,
                        help="Minutes of history to search (default: from config.json)")
    parser.add_argument("--analyze-local", metavar="PATH",
                        help="Skip download. Analyze a local raw-logs.json file")
    parser.add_argument("--analyze-folder", metavar="PATH",
                        help="Merge and analyze all *.json and *.log files in a folder")
    parser.add_argument("--repo-url", default="https://github.com/congaengr/Conga.Revenue.Renewal",
                        help="GitHub repo URL for source code links")
    parser.add_argument("--compact", action="store_true",
                        help="Compact error-analysis.md (top 3 frames only, ~400 tokens) for LLM consumption")
    args = parser.parse_args()

    # --- Mode 1: Analyze local file ---
    if args.analyze_local:
        entries, out_dir = analyze_local(args.analyze_local)
        run_analysis(entries, out_dir, args.repo_url, compact=args.compact)
        return

    # --- Mode 2: Analyze a folder (*.json + *.log merged) ---
    if args.analyze_folder:
        entries, out_dir = analyze_folder(args.analyze_folder)
        run_analysis(entries, out_dir, args.repo_url, compact=args.compact)
        return

    # --- Mode 3: Download from Grafana ---
    config = load_config()

    time_range = args.time_range if args.time_range > 0 else config.get("defaultTimeRangeMinutes", 60)

    # Resolve Grafana URL for the target environment
    env_cfg = config.get("grafana", {}).get(args.environment)
    if not env_cfg:
        print(f"ERROR: Environment '{args.environment}' not in config.json")
        sys.exit(1)

    grafana_url = env_cfg["url"].rstrip("/")

    # Resolve API key from config.json
    api_key = env_cfg.get("apiKey", "")
    if not api_key:
        print(f"ERROR: No apiKey for '{args.environment}' in config.json")
        sys.exit(1)

    loki_query = build_loki_query(args.trace_id, args.deployment_env, args.loki_query, args.environment)

    # Create output folder: downloads/<traceId>_<timestamp>/
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = args.trace_id or "custom"
    out_dir = DOWNLOADS_DIR / f"{tag}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nQuery:       {loki_query}")
    print(f"Time Range:  {time_range} min")
    print(f"Output:      {out_dir}\n")

    # Download logs (returns None on failure instead of exiting)
    resp = download_logs(
        grafana_url, api_key, loki_query, time_range,
        config.get("maxLogEntries", 5000),
    )

    # If download failed, guide the user to place logs manually
    if resp is None:
        print(f"\n{'=' * 60}")
        print("DOWNLOAD FAILED - Manual log placement required")
        print(f"{'=' * 60}")
        print(f"\nCould not download logs from Grafana (timeout or error).")
        print(f"\nTo continue, manually download the logs and place them here:")
        print(f"  {out_dir / 'raw-logs.json'}")
        print(f"\nThen run:")
        print(f'  python log_downloader.py --analyze-local "{out_dir / "raw-logs.json"}"')
        sys.exit(1)

    entries = parse_loki_response(resp)
    print(f"Found {len(entries)} log entries")

    if not entries:
        print("No logs found. Try increasing --time-range.")
        sys.exit(0)

    # Save raw data for re-analysis later
    (out_dir / "raw-logs.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    run_analysis(entries, out_dir, args.repo_url, compact=args.compact)


if __name__ == "__main__":
    main()
