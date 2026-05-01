"""Shared utilities for Conga Copilot skills.

Common functionality for PR Porter, Package Upgrader, and future skills.
Requires: Python 3.10+ (stdlib only, zero dependencies)
"""

from __future__ import annotations
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime


# ============================================================================
# TRX Test Results Parser
# ============================================================================

def parse_trx(trx_path: str | Path) -> dict | None:
    """Parse Visual Studio .trx test results file.
    
    Args:
        trx_path: Path to .trx file
    
    Returns:
        dict with keys: total, passed, failed, skipped, failed_tests
        None if file not found
    """
    path = Path(trx_path)
    if not path.exists():
        return None
    
    root = ET.parse(path).getroot()
    ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
    
    counters = root.find(".//t:ResultSummary/t:Counters", ns)
    if counters is None:
        counters = root.find(".//ResultSummary/Counters")
    
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "failed_tests": []
    }
    
    if counters is not None:
        summary.update(
            total=int(counters.get("total", 0)),
            passed=int(counters.get("passed", 0)),
            failed=int(counters.get("failed", 0)),
            skipped=int(counters.get("notExecuted", 0))
        )
    
    for result in root.findall(".//t:UnitTestResult[@outcome='Failed']", ns):
        test_name = result.get("testName", "?")
        error_msg = ""
        error_el = result.find(".//t:ErrorInfo/t:Message", ns)
        if error_el is not None and error_el.text:
            error_msg = error_el.text[:200]
        summary["failed_tests"].append({
            "name": test_name,
            "error": error_msg
        })
    
    return summary


# ============================================================================
# File Writing Utilities
# ============================================================================

def write_json(data: dict, path: str | Path) -> Path:
    """Write JSON with standard formatting."""
    path = Path(path)
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_markdown(content: str, path: str | Path) -> Path:
    """Write markdown file."""
    path = Path(path)
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(content, encoding="utf-8")
    return path


# ============================================================================
# PR Body Utilities
# ============================================================================

def format_test_results_table(test_summary: dict) -> str:
    """Format test results as markdown table.
    
    Args:
        test_summary: Output from parse_trx()
    
    Returns:
        Markdown table string with pass/fail counts and failed test details
    """
    status = "✅ All passing" if test_summary['failed'] == 0 else f"❌ {test_summary['failed']} failed"
    
    lines = [
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total | {test_summary['total']} |",
        f"| Passed | {test_summary['passed']} |",
        f"| Failed | {test_summary['failed']} |",
        f"| Skipped | {test_summary['skipped']} |",
        "",
        f"**Status:** {status}"
    ]
    
    if test_summary["failed_tests"]:
        lines.append("\n**Failed Tests:**")
        for ft in test_summary["failed_tests"][:10]:
            lines.append(f"- `{ft['name']}`: {ft['error'][:100]}")
        if len(test_summary["failed_tests"]) > 10:
            lines.append(f"- _...and {len(test_summary['failed_tests']) - 10} more_")
    
    return "\n".join(lines)


def timestamp() -> str:
    """Standard timestamp format for PR bodies."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ============================================================================
# Package Version Validation
# ============================================================================

def validate_sprint_version(version: str) -> bool:
    """Validate Conga.Platform sprint-based version format YYYYMM.sprint.minor
    
    Args:
        version: Version string (e.g., "202603.1.7")
    
    Returns:
        True if valid sprint format, False otherwise
    
    Examples:
        >>> validate_sprint_version("202603.1.7")
        True
        >>> validate_sprint_version("1.2.3")
        False
    """
    return bool(re.match(r'^\d{6}\.\d+\.\d+$', version))


def validate_semantic_version(version: str) -> bool:
    """Validate semantic version format major.minor.patch (for Conga.Revenue.*)
    
    Args:
        version: Version string (e.g., "2.4.1", "10.0.0")
    
    Returns:
        True if valid semantic version, False otherwise
    
    Examples:
        >>> validate_semantic_version("2.4.1")
        True
        >>> validate_semantic_version("202603.1.7")
        False
    """
    return bool(re.match(r'^\d+\.\d+\.\d+$', version))


def validate_package_version(version: str) -> bool:
    """Validate any Conga package version (sprint-based OR semantic).
    
    Accepts both formats:
    - Sprint: YYYYMM.sprint.minor (e.g., "202603.1.7")
    - Semantic: major.minor.patch (e.g., "2.4.1")
    
    Args:
        version: Version string
    
    Returns:
        True if valid format (either type), False otherwise
    """
    return validate_sprint_version(version) or validate_semantic_version(version)