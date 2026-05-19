# Conga Package Upgrader - mechanical operations only.
# NuGet version discovery is Copilot's job via the NuGet-MCP fetch tool.
# This script handles: .csproj scanning, patching, TRX parsing, PR body generation.
#
# Subcommands:
#   scan                  Print JSON: current sprint + all matching package locations
#   find-target-version   Resolve highest minor in a target sprint via Artifactory OData (Platform)
#   find-revenue-version  Resolve latest Revenue package versions; OData fallback for legacy versions
#   patch                 Update PackageReference versions in .csproj files (NuGet MCP fallback)
#   generate-pr-body      Build a draft PR body from plan.json + optional .trx file
#   parse-trx             Print a human-readable summary of a .trx test-results file
#
# Requires: Python 3.10+

from __future__ import annotations
import argparse, base64, json, os, re, sys, tempfile, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conga_common import parse_trx, write_markdown, validate_package_version, validate_sprint_version  # noqa: E402

_RUN_TS         = datetime.now().strftime("%Y%m%d-%H%M%S")
TEMP_PLAN_JSON  = Path(tempfile.gettempdir()) / f"conga-upgrade-plan-{_RUN_TS}.json"
TEMP_PR_BODY_MD = Path(tempfile.gettempdir()) / f"conga-pr-body-{_RUN_TS}.md"
DEFAULT_PREFIX  = "Conga.Platform."
DEFAULT_SOURCE  = "https://art01.apttuscloud.io/artifactory/api/nuget/conga-platform-nuget"
PKGREF_RE       = re.compile(r'(<PackageReference\s+Include="(?P<pkg>[^"]+)"\s+Version=")(?P<ver>[^"]+)(")')
_SPRINT_RE      = re.compile(r"^(\d{6})\.(\d+)\.\d+$")


# -- helpers -------------------------------------------------------------------

def _csproj_files(root: Path) -> list[Path]:
    """Find all .csproj files, excluding bin/obj directories."""
    return [p for p in root.rglob("*.csproj")
            if not any(x in p.parts for x in ("bin", "obj"))]

def _platform_pkgs(csproj: Path, prefix: str = DEFAULT_PREFIX) -> dict[str, str]:
    """Extract package references whose name starts with *prefix* from a .csproj file."""
    pkgs = {}
    for m in PKGREF_RE.finditer(csproj.read_text(encoding="utf-8")):
        if m.group("pkg").startswith(prefix):
            pkgs[m.group("pkg")] = m.group("ver")
    return pkgs

def _current_sprint(all_pkgs: dict[str, str]) -> tuple[int, int] | None:
    """Return (yyyymm, sprint) of the highest sprint found across all package versions."""
    best: tuple[int, int] | None = None
    for v in all_pkgs.values():
        if m := _SPRINT_RE.match(v.strip()):
            p = (int(m.group(1)), int(m.group(2)))
            if best is None or p > best:
                best = p
    return best

# -- scan ----------------------------------------------------------------------

def _scan_prefix(root: Path, prefix: str) -> tuple[dict, dict]:
    """Return (csproj_map, all_pkgs) for a single prefix."""
    csproj_map: dict[str, dict] = {}
    all_pkgs:   dict[str, str]  = {}
    for f in _csproj_files(root):
        pkgs = _platform_pkgs(f, prefix)
        if pkgs:
            csproj_map[str(f.relative_to(root))] = pkgs
            all_pkgs.update(pkgs)
    return csproj_map, all_pkgs


def cmd_scan(args):
    """Scan solution for packages matching --prefix (or both namespaces with --all-prefixes).

    --all-prefixes  scan both Conga.Platform.* and Conga.Revenue.* in one pass.
                    Output JSON has a top-level key per prefix instead of a single 'packages' map.
    """
    root = Path(args.solution_path).resolve()

    if getattr(args, "all_prefixes", False):
        prefixes = [DEFAULT_PREFIX, "Conga.Revenue."]
        result: dict = {"solution_path": str(root), "namespaces": {}}
        for prefix in prefixes:
            csproj_map, all_pkgs = _scan_prefix(root, prefix)
            if not all_pkgs:
                result["namespaces"][prefix] = {"error": f"No {prefix} packages found."}
                continue
            invalid = {p: v for p, v in all_pkgs.items() if not validate_package_version(v)}
            if invalid:
                print(f"WARNING: Invalid versions for {prefix}: {invalid}", file=sys.stderr)
            cur = _current_sprint(all_pkgs)
            pkg_index: dict = {}
            for proj, pkgs in csproj_map.items():
                for pkg, ver in pkgs.items():
                    if pkg not in pkg_index:
                        pkg_index[pkg] = {"current_version": ver, "projects": []}
                    pkg_index[pkg]["projects"].append(proj)
            result["namespaces"][prefix] = {
                "current_sprint": f"{cur[0]}.{cur[1]}" if cur else None,
                "packages": pkg_index,
            }
        print(json.dumps(result, indent=2))
        return 0

    # Single prefix (original behaviour)
    prefix = args.prefix
    csproj_map, all_pkgs = _scan_prefix(root, prefix)

    if not all_pkgs:
        print(json.dumps({"error": f"No {prefix} packages found."}))
        return 1

    invalid = {pkg: ver for pkg, ver in all_pkgs.items()
               if not validate_package_version(ver)}
    if invalid:
        print("WARNING: Invalid version format detected:", file=sys.stderr)
        for pkg, ver in invalid.items():
            print(f"  {pkg}: {ver}", file=sys.stderr)

    cur = _current_sprint(all_pkgs)

    pkg_index = {}
    for proj, pkgs in csproj_map.items():
        for pkg, ver in pkgs.items():
            if pkg not in pkg_index:
                pkg_index[pkg] = {"current_version": ver, "projects": []}
            pkg_index[pkg]["projects"].append(proj)

    print(json.dumps({
        "solution_path":  str(root),
        "prefix":         prefix,
        "current_sprint": f"{cur[0]}.{cur[1]}" if cur else None,
        "packages":       pkg_index,
    }, indent=2))
    return 0


# -- OData / credentials -----------------------------------------------------

def _read_nuget_creds(source_url: str, solution_path: Path | None = None) -> tuple[str, str] | None:
    """Read username + ClearTextPassword for *source_url* from NuGet.Config.

    Search order: %APPDATA%/NuGet/NuGet.Config → <solution_path>/NuGet.Config → cwd/NuGet.Config.
    Returns (username, password) or None if not found.
    """
    candidates = [Path(os.environ.get("APPDATA", "")) / "NuGet" / "NuGet.Config"]
    if solution_path:
        candidates.append(Path(solution_path).resolve() / "NuGet.Config")
    candidates.append(Path.cwd() / "NuGet.Config")
    for cfg in candidates:
        if not cfg.exists():
            continue
        try:
            text     = cfg.read_text(encoding="utf-8")
            src_host = source_url.split("/")[2]
            if src_host not in text:
                continue
            for ps in ET.fromstring(text).iter("packageSourceCredentials"):
                for child in ps:
                    username = pw = None
                    for add in child:
                        k, v = add.attrib.get("key", ""), add.attrib.get("value", "")
                        if k in ("Username", "username"):
                            username = v
                        elif k in ("ClearTextPassword", "clearTextPassword"):
                            pw = v
                    if username and pw:
                        return username, pw
        except Exception:
            continue
    return None


def _odata_query(pkg: str, source: str, creds: tuple[str, str] | None, *, sprint: str | None = None) -> str | None:
    """Query Artifactory NuGet v2 OData for a package version.

    sprint=<str>  → filter startswith(Version, sprint) + order by Version desc  (Platform: highest minor in sprint)
    sprint=None   → order by Published desc                                       (Revenue: latest by publish date)
    Uses ``Version`` field — ``NormalizedVersion`` is NuGet Gallery-only and returns 400 on Artifactory.
    """
    if sprint:
        url = (f"{source}/FindPackagesById()?id='{pkg}'"
               f"&$filter=startswith(Version,'{sprint}.')&$orderby=Version+desc&$top=1")
    else:
        url = f"{source}/FindPackagesById()?id='{pkg}'&$orderby=Published+desc&$top=1"
    req = urllib.request.Request(url)
    if creds:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ns = {"d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
                  "atom": "http://www.w3.org/2005/Atom"}
            entry = ET.fromstring(resp.read()).find("atom:entry", ns)
            if entry is None:
                return None
            ver_el = entry.find(".//d:Version", ns)
            return ver_el.text.strip() if ver_el is not None else None
    except Exception:
        return None


def _is_conflicting_version(ver: str) -> bool:
    """Return True when *ver* is NOT a valid 6-digit-prefix sprint version (e.g. legacy ``2024011.2.2``)."""
    return not validate_sprint_version(ver.strip())




# -- patch --------------------------------------------------------------------

def cmd_patch(args):
    """Patch PackageReference versions in .csproj files from a JSON versions map.

    Reads ``--versions-file`` (JSON: {"PackageName": "version", ...}) and updates
    only the ``Version`` attribute of matching ``<PackageReference>`` entries.

    This is equivalent to upgrading packages manually via the Visual Studio NuGet
    Package Manager UI: only the explicitly listed package versions are changed;
    transitive dependencies are never added or modified.

    Outputs a summary of every file touched and each version change applied.
    """
    root     = Path(args.solution_path).resolve()
    versions: dict[str, str] = json.loads(Path(args.versions_file).read_text(encoding="utf-8-sig"))

    if not versions:
        print(json.dumps({"error": "versions-file is empty"}), file=sys.stderr)
        return 1

    changed_files: dict[str, list[str]] = {}  # file -> list of "pkg: old -> new"

    for csproj in _csproj_files(root):
        original = csproj.read_text(encoding="utf-8")
        updated  = original

        for pkg, target_ver in versions.items():
            def _replacer(m: re.Match, _pkg: str = pkg, _ver: str = target_ver) -> str:
                if m.group("pkg") != _pkg:
                    return m.group(0)
                old_ver = m.group("ver")
                if old_ver == _ver:
                    return m.group(0)
                changed_files.setdefault(str(csproj.relative_to(root)), []).append(
                    f"  {_pkg}: {old_ver} -> {_ver}"
                )
                return m.group(1) + _ver + m.group(4)

            updated = PKGREF_RE.sub(_replacer, updated)

        if updated != original:
            csproj.write_text(updated, encoding="utf-8")

    if changed_files:
        for f, changes in changed_files.items():
            print(f"[patch] {f}", file=sys.stderr)
            for c in changes:
                print(c, file=sys.stderr)
        print(json.dumps({"patched_files": list(changed_files.keys()), "status": "ok"}))
    else:
        print(json.dumps({"patched_files": [], "status": "no changes — all packages already at target versions"}))
    return 0


def cmd_find_revenue_version(args):
    """Resolve latest versions for Conga.Revenue.* packages.

    NuGet MCP versions are used as-is when they match sprint format (YYYYMM.sprint.minor).
    Legacy versions (e.g. 2024011.2.2 with 7-digit prefix) fall back to OData Published+desc.
    """
    source       = args.source
    sol_path     = Path(args.solution_path).resolve() if args.solution_path else None
    creds        = (args.username, args.password) if args.username else _read_nuget_creds(source, sol_path)

    nuget_map: dict[str, str] = {}
    if args.nuget_versions_file:
        nuget_map = json.loads(Path(args.nuget_versions_file).read_text(encoding="utf-8-sig"))
    elif args.nuget_versions:
        nuget_map = json.loads(args.nuget_versions)

    if not nuget_map and args.solution_path:
        prefix = args.prefix
        root   = Path(args.solution_path).resolve()
        all_pkgs: dict[str, str] = {}
        for f in _csproj_files(root):
            all_pkgs.update(_platform_pkgs(f, prefix))
        if not all_pkgs:
            print(json.dumps({"error": f"No {prefix} packages found in {root}"}), file=sys.stdout)
            return 1
        nuget_map = {pkg: "" for pkg in all_pkgs}
        print(f"  [scan] discovered {len(nuget_map)} package(s) with prefix '{prefix}'", file=sys.stderr)

    if not nuget_map:
        print("ERROR: provide --nuget-versions JSON or --solution-path", file=sys.stderr)
        return 1

    resolved: dict[str, str] = {}
    failed:   list[str]      = []

    for pkg, nuget_ver in nuget_map.items():
        if nuget_ver and not _is_conflicting_version(nuget_ver):
            resolved[pkg] = nuget_ver
            print(f"  [nuget-mcp] {pkg} -> {nuget_ver}", file=sys.stderr)
        else:
            reason = f"legacy version '{nuget_ver}'" if nuget_ver else "no version supplied"
            print(f"  [odata-fallback] {pkg} <- conflicting {reason}, querying OData...", file=sys.stderr)
            ver = _odata_query(pkg, source, creds)
            if ver:
                resolved[pkg] = ver
                print(f"  [odata-fallback] {pkg} -> {ver}", file=sys.stderr)
            else:
                failed.append(pkg)
                print(f"  [odata-fallback] {pkg} -> NOT FOUND", file=sys.stderr)

    if failed:
        print(f"WARNING: could not resolve latest version for: {', '.join(failed)}", file=sys.stderr)

    print(json.dumps(resolved, indent=2))
    return 0 if not failed else 1


def cmd_find_target_version(args):
    """Resolve the highest minor in *sprint* for each Conga.Platform.* package via OData (parallel)."""
    sprint   = args.sprint
    source   = args.source
    sol_path = Path(args.solution_path).resolve() if args.solution_path else None
    creds    = (args.username, args.password) if args.username else _read_nuget_creds(source, sol_path)

    if args.solution_path:
        prefix   = args.prefix
        root     = Path(args.solution_path).resolve()
        all_pkgs: dict[str, str] = {}
        for f in _csproj_files(root):
            all_pkgs.update(_platform_pkgs(f, prefix))
        if not all_pkgs:
            print(json.dumps({"error": f"No {prefix} packages found in {root}"}))
            return 1
        packages = list(all_pkgs.keys())
        print(f"  [scan] discovered {len(packages)} package(s) with prefix '{prefix}'", file=sys.stderr)
    elif args.packages:
        packages = [p.strip() for p in args.packages.split(",") if p.strip()]
    else:
        print("ERROR: provide --solution-path or --packages", file=sys.stderr)
        return 1

    resolved: dict[str, str] = {}
    failed:   list[str]      = []

    def _fetch(pkg: str) -> tuple[str, str | None]:
        return pkg, _odata_query(pkg, source, creds, sprint=sprint)

    with ThreadPoolExecutor(max_workers=min(len(packages), 8)) as pool:
        futures = {pool.submit(_fetch, pkg): pkg for pkg in packages}
        for future in as_completed(futures):
            pkg, ver = future.result()
            if ver:
                resolved[pkg] = ver
                print(f"  [odata] {pkg} -> {ver}", file=sys.stderr)
            else:
                failed.append(pkg)
                print(f"  [odata] {pkg} -> NOT FOUND for sprint {sprint}", file=sys.stderr)

    if failed:
        print(f"WARNING: no {sprint}.* version found for: {', '.join(failed)}", file=sys.stderr)

    print(json.dumps(resolved, indent=2))
    return 0 if not failed else 1


# -- generate-pr-body ---------------------------------------------------------
# plan.json Shape A (preferred): flat "changes" array with project/namespace/package/from/to.
# plan.json Shape B (fallback):  "namespaces" object — auto-converted by _changes_from_namespaces.

_NS_LABEL: dict[str, str] = {"Conga.Platform.": "Platform", "Conga.Revenue.": "Revenue"}


def _changes_from_namespaces(plan: dict) -> list[dict]:
    """Convert Shape B namespaces plan to flat Shape A changes list (omits already-at-target packages)."""
    changes: list[dict] = []
    project = Path(plan.get("solution_path", "")).name or "Unknown"
    for ns_key, ns_data in plan.get("namespaces", {}).items():
        ns_label = _NS_LABEL.get(ns_key, ns_key.rstrip("."))
        for pkg_name, pkg_data in ns_data.get("packages", {}).items():
            from_ver, to_ver = pkg_data.get("from", ""), pkg_data.get("to", "")
            if from_ver != to_ver:
                changes.append({"project": project, "namespace": ns_label,
                                 "package": pkg_name, "from": from_ver, "to": to_ver})
    return changes


_BODY = (
    "## {title}\n\n"
    "**{changes_summary}**\n\n"
    "**Tests:** {test_summary}\n\n"
    "*Generated by `conga-package-upgrader` skill.*\n"
)


def cmd_generate_pr_body(args):
    """Generate a concise PR body (2-line summary) from plan.json + optional TRX."""
    plan  = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    title = plan.get("title", "Upgrade Conga Packages")

    raw_changes = plan.get("changes") or _changes_from_namespaces(plan)

    platform_pkgs = [c for c in raw_changes if c.get("namespace") == "Platform"]
    revenue_pkgs  = [c for c in raw_changes if c.get("namespace") == "Revenue"]

    parts = []
    if platform_pkgs:
        sprints = sorted({c["to"].rsplit(".", 1)[0] for c in platform_pkgs})
        parts.append(f"{len(platform_pkgs)} Platform package(s) → {', '.join(sprints)}")
    if revenue_pkgs:
        sprints = sorted({c["to"].rsplit(".", 1)[0] for c in revenue_pkgs})
        parts.append(f"{len(revenue_pkgs)} Revenue package(s) → {', '.join(sprints)}")
    changes_summary = "; ".join(parts) if parts else "No packages changed"

    trx_s = parse_trx(args.trx_path) if args.trx_path else None
    if trx_s:
        test_summary = (
            f"✅ {trx_s['passed']} passed, {trx_s['failed']} failed, "
            f"{trx_s.get('skipped', 0)} skipped (total {trx_s['total']})"
        )
    else:
        test_summary = "verify manually"

    body = _BODY.format(
        title           = title,
        changes_summary = changes_summary,
        test_summary    = test_summary,
    )

    out_path = Path(args.output) if args.output else TEMP_PR_BODY_MD
    out = write_markdown(body, out_path)
    print(f"PR body -> {out}")
    return 0


# -- command configuration (declarative) --------------------------------------

_COMMANDS = [
    ("scan", cmd_scan, [
        ("--solution-path",  {"default": "."}),
        ("--prefix",         {"default": DEFAULT_PREFIX, "help": "Package name prefix (default: Conga.Platform.)"}),
        ("--all-prefixes",   {"action": "store_true", "default": False,
                              "help": "Scan both Conga.Platform.* and Conga.Revenue.* in one pass"}),
    ]),

    ("find-target-version", cmd_find_target_version, [
        ("--solution-path", {"default": None, "help": "Solution root; auto-discovers all packages with --prefix (preferred)"}),
        ("--prefix",        {"default": DEFAULT_PREFIX, "help": "Package prefix used with --solution-path (default: Conga.Platform.)"}),
        ("--packages",      {"default": None, "help": "Comma-separated package IDs (alternative to --solution-path)"}),
        ("--sprint",        {"required": True, "help": "Target sprint prefix, e.g. 202604.1"}),
        ("--source",        {"default": DEFAULT_SOURCE, "help": "NuGet v2 feed URL"}),
        ("--username",      {"default": None, "help": "Feed username (optional; uses NuGet.Config if omitted)"}),
        ("--password",      {"default": None, "help": "Feed password / API key"}),
    ]),

    ("find-revenue-version", cmd_find_revenue_version, [
        ("--nuget-versions",      {"default": None, "help": 'Inline JSON map {"Pkg":"ver",...} — prefer --nuget-versions-file in PowerShell'}),
        ("--nuget-versions-file", {"default": None, "help": "Path to JSON file {\"Pkg\":\"ver\",...} — write via Copilot create_file (timestamped name)"}),
        ("--solution-path",       {"default": None, "help": "Solution root; auto-discovers Conga.Revenue.* when no --nuget-versions* supplied"}),
        ("--prefix",              {"default": "Conga.Revenue.", "help": "Package prefix for solution scan (default: Conga.Revenue.)"}),
        ("--source",              {"default": DEFAULT_SOURCE, "help": "NuGet v2 feed URL"}),
        ("--username",            {"default": None, "help": "Feed username (optional; uses NuGet.Config if omitted)"}),
        ("--password",            {"default": None, "help": "Feed password / API key"}),
    ]),

    ("patch", cmd_patch, [
        ("--solution-path", {"default": ".", "help": "Solution root to scan for .csproj files"}),
        ("--versions-file", {"required": True, "help": 'Path to JSON file {"PackageName": "version", ...}'}),
    ]),

    ("parse-trx", None, [
        ("--trx-path", {"required": True}),
    ]),

    ("generate-pr-body", cmd_generate_pr_body, [
        ("--plan",     {"default": str(TEMP_PLAN_JSON),  "help": f"Path to plan.json (default: {TEMP_PLAN_JSON})"}),
        ("--trx-path", {"default": None}),
        ("--output",   {"default": None, "help": f"Output path for pr-body.md (default: {TEMP_PR_BODY_MD}). "
                                                  "Defaults to system temp — no .gitignore changes needed in any project."}),
    ]),
]


# -- entry point ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Conga Package Upgrader (Platform + Revenue)")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # Build all subcommands from declarative config
    for cmd_name, handler, arguments in _COMMANDS:
        subparser = subparsers.add_parser(cmd_name)
        for arg_name, arg_kwargs in arguments:
            subparser.add_argument(arg_name, **arg_kwargs)

    args = parser.parse_args()

    # Special handling for parse-trx (no handler in config)
    if args.cmd == "parse-trx":
        trx_result = parse_trx(args.trx_path)
        print(json.dumps(trx_result, indent=2) if trx_result else "{}")
        sys.exit(0 if trx_result else 1)

    # Find and execute the handler
    handler = next((h for name, h, _ in _COMMANDS if name == args.cmd and h), None)
    if handler:
        sys.exit(handler(args))
    else:
        print(f"ERROR: No handler for command '{args.cmd}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
