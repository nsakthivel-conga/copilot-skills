# Conga Log Analyzer Skill

## Purpose
Download Grafana Loki logs by TraceId, analyze errors/exceptions, and identify root cause.
Uses Python (stdlib only, zero dependencies).

## Usage

```bash
cd "..\copilot-skills\conga-log-analyzer"

# By TraceId (dev/qa default to deployment_environment=rls04)
python log_downloader.py --trace-id "abc123" --environment dev

# With explicit deployment filter
python log_downloader.py --trace-id "abc123" --environment dev --deployment-env rls04

# Custom Loki query with service filter
python log_downloader.py --environment dev --loki-query '{deployment_environment="rls04", service_name="platform-objectdb-api"} |= "abc123"'

# Extended time range (15 days = 21600 min)
python log_downloader.py --trace-id "abc123" --environment dev --time-range 21600

# Analyze previously downloaded logs (no Grafana needed)
python log_downloader.py --analyze-local "downloads/abc123_20260305/raw-logs.json"
```

## Parameters
| Parameter | Required | Description |
|-----------|----------|-------------|
| --trace-id | Yes* | OpenTelemetry trace ID |
| --environment | No | dev (default), staging, production. dev/qa auto-defaults to rls04 |
| --deployment-env | No | Override deployment filter (e.g. rls04, rls07) |
| --loki-query | Yes* | Custom Loki query (overrides --trace-id) |
| --time-range | No | Minutes of history. Default: 60 |
| --analyze-local | No | Path to raw-logs.json for offline re-analysis |
| --repo-url | No | GitHub repo URL for source links (default: congaengr/Conga.Revenue.Renewal) |

*Provide either --trace-id or --loki-query

## Output Files
| File | Contents |
|------|----------|
| summary.md | ~3KB overview: services, error root cause, perf hotspots, HTTP calls |
| error-analysis.md | Stack traces with GitHub source links, exception types |
| performance.md | Waterfall timing, HTTP call durations, slow segments |
| timeline.md | Every log entry in chronological order |
| raw-logs.json | Complete raw data from Grafana |

## Setup
1. Copy `config.template.json` to `config.json`
2. Set your Grafana API keys in `config.json` (one `apiKey` per environment)
3. Python 3.10+ required (no pip packages needed)
