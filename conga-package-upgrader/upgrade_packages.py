# Conga Package Upgrader - mechanical operations only.
# NuGet version discovery is Copilot's job via the NuGet-MCP fetch tool.
# This script handles: .csproj scanning, patching, TRX parsing, PR body generation.
#
# Subcommands:
#   scan                  Print JSON: current sprint + all matching package locations
#   patch                 Apply {pkg: version} JSON to every matching .csproj (fallback only)
#   find-target-version   Resolve highest minor in a target sprint via Artifactory OData (Platform)
#   find-revenue-version  Resolve latest Revenue package versions; falls back to OData only when
#                         NuGet MCP returns a conflicting (legacy) version string
#   generate-pr-body      Build a draft PR body from plan.json + optional .trx file
#   parse-trx             Print a human-readable summary of a .trx test-results file
#
# Preferred workflow (no PowerShell JSON quoting issues):
#   Steps 1-3  -> scan + NuGet MCP + OData to build upgrade plan
#   Step 4     -> Copilot writes upgrades/plan.json from confirmed plan (bypasses shell quoting)
#   Step 5     -> NuGet_MCP_update_package_version applies versions directly to .csproj files
#   Step 9     -> generate-pr-body reads plan.json + .trx -> writes pr-body.md
#
# Requires: Python 3.10+

from __future__ import annotations
import argparse, json, re, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # copilot-skills/ root contains conga_common.py
from conga_common import parse_trx, format_test_results_table, write_json, write_markdown, validate_package_version  # noqa: E402

SCRIPT_DIR        = Path(__file__).resolve().parent
UPGRADES_DIR      = SCRIPT_DIR / "upgrades"
DEFAULT_PREFIX    = "Conga.Platform."
PKGREF_RE         = re.compile(r'(<PackageReference\s+Include="(?P<pkg>[^"]+)"\s+Version=")(?P<ver>[^"]+)(")')
_SPRINT_RE        = re.compile(r"^(\d{6})\.(\d+)\.\d+$")   # used only by _current_sprint


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

def cmd_scan(args):
    """Scan solution for packages matching --prefix and print JSON summary."""
    root   = Path(args.solution_path).resolve()
    prefix = args.prefix
    csproj_map, all_pkgs = {}, {}

    for f in _csproj_files(root):
        pkgs = _platform_pkgs(f, prefix)
        if pkgs:
            csproj_map[str(f.relative_to(root))] = pkgs
            all_pkgs.update(pkgs)

    if not all_pkgs:
        print(json.dumps({"error": f"No {prefix} packages found."}))
        return 1

    # Validate all package versions
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


# -- patch ---------------------------------------------------------------------

def cmd_patch(args):
    """Apply version updates to all matching .csproj files."""
    root        = Path(args.solution_path).resolve()
    prefix      = args.prefix
    version_map = json.loads(args.versions)

    # Validate all target versions before patching
    invalid = {pkg: ver for pkg, ver in version_map.items() 
               if not validate_package_version(ver)}
    if invalid:
        print("ERROR: Invalid version format in target versions:", file=sys.stderr)
        for pkg, ver in invalid.items():
            print(f"  {pkg}: {ver}", file=sys.stderr)
        return 1

    changes_by_proj = {}

    for csproj in _csproj_files(root):
        content     = csproj.read_text(encoding="utf-8")
        new_content = content
        proj_changes = []

        for pkg, new_ver in version_map.items():
            def _replace(m, _p=pkg, _v=new_ver):
                if m.group("pkg") == _p and m.group("ver") != _v:
                    proj_changes.append([_p, m.group("ver"), _v])
                    return m.group(1) + _v + m.group(4)
                return m.group(0)
            new_content = PKGREF_RE.sub(_replace, new_content)

        if new_content != content:
            csproj.write_text(new_content, encoding="utf-8")
            rel = str(csproj.relative_to(root))
            changes_by_proj[rel] = proj_changes
            for p, old, new in proj_changes:
                print(f"  {csproj.name}  {p.removeprefix(prefix)}: {old} -> {new}")

    total = sum(len(v) for v in changes_by_proj.values())
    print(f"\n{total} reference(s) updated across {len(changes_by_proj)} project(s).")

    if changes_by_proj:
        UPGRADES_DIR.mkdir(exist_ok=True)
        meta = {
            "target_sprint": args.target_sprint,
            "prefix": prefix,
            "solution_path": str(root),
            "changes_by_project": changes_by_proj,
            "timestamp": datetime.now().isoformat()
        }
        out = write_json(meta, UPGRADES_DIR / "changes.json")
        print(f"Saved -> {out}")
    return 0


# -- find-target-version ------------------------------------------------------
# Approach: Artifactory NuGet v2 OData
#   FindPackagesById()?$filter=startswith(Version,'<sprint>.')&$orderby=Version+desc&$top=1
#   One HTTP call per package. Credentials auto-read from NuGet.Config.
#
# Why other approaches were rejected:
#   NuGet v3 flat container index.json -> 405 (disabled on this Artifactory instance)
#   Artifactory AQL                    -> empty (NuGet pkgs not stored as Maven artifacts)
#   dotnet package search              -> stale search index, wrong versions
#   NuGet MCP get_latest_package_version -> absolute latest only, no sprint-prefix filter
#   Temp .csproj + dotnet restore      -> works but ~15 s + temp files; removed as fallback
#                                         was no longer needed once OData filter used
#                                         'Version' (not 'NormalizedVersion' which is
#                                         NuGet.org Gallery-only -> 400 Bad Request)

def _read_nuget_creds(source_url: str, solution_path: Path | None = None) -> tuple[str, str] | None:
    """Read username + ClearTextPassword for *source_url* from NuGet.Config.

    Search order:
    1. %APPDATA%/NuGet/NuGet.Config          - user-wide (always checked)
    2. <solution_path>/NuGet.Config          - solution-local (when --solution-path supplied)
    3. <cwd>/NuGet.Config                    - current working directory fallback

    The old SCRIPT_DIR.parent.parent candidate pointed at SourceCode/ which is not
    the solution root. Passing --solution-path is the correct way to find it.
    Returns (username, password) or None if not found.
    """
    import xml.etree.ElementTree as ET, os
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "NuGet" / "NuGet.Config",
    ]
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
                        if k in ("Username", "username"):                    username = v
                        elif k in ("ClearTextPassword", "clearTextPassword"): pw = v
                    if username and pw:
                        return username, pw
        except Exception:
            continue
    return None


def _find_via_odata(pkg: str, sprint: str, source: str, creds: tuple[str, str] | None) -> str | None:
    """Return the highest ``Version`` starting with ``sprint.`` from the Artifactory NuGet v2 feed.

    Uses ``$filter=startswith(Version,'<sprint>.')&$orderby=Version+desc&$top=1``.
    Field must be ``Version`` not ``NormalizedVersion`` (Artifactory v2 does not expose the latter).
    Returns the version string, or None if no match or any HTTP/parse error.
    """
    import urllib.request, base64
    url = (
        f"{source}/FindPackagesById()"
        f"?id='{pkg}'"
        f"&$filter=startswith(Version,'{sprint}.')"
        f"&$orderby=Version+desc&$top=1"
    )
    req = urllib.request.Request(url)
    if creds:
        token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            import xml.etree.ElementTree as ET
            ns = {
                "d":    "http://schemas.microsoft.com/ado/2007/08/dataservices",
                "atom": "http://www.w3.org/2005/Atom",
            }
            root  = ET.fromstring(resp.read())
            entry = root.find("atom:entry", ns)
            if entry is None:
                return None
            ver_el = entry.find(".//d:Version", ns)
            return ver_el.text.strip() if ver_el is not None else None
    except Exception:
        return None


def _is_conflicting_version(ver: str) -> bool:
    """Return True when *ver* is NOT a valid sprint-format version string.

    Valid sprint format: ``YYYYMM.sprint.minor`` where YYYYMM is exactly 6 digits.
    e.g. ``202412.2.3``, ``202501.1.5``, ``202604.2.11`` are all valid.

    Conflicting (legacy) versions like ``2024011.2.2`` have a 7-digit date prefix
    and sort lexicographically above valid sprint versions, causing NuGet MCP to
    return stale builds. This check is year-agnostic: it works correctly across
    year boundaries (e.g. Jan 2025 packages may still be ``202412.*``).
    """
    return _SPRINT_RE.match(ver.strip()) is None


def _find_latest_revenue_via_odata(pkg: str, source: str, creds: tuple[str, str] | None) -> str | None:
    """Return the most recently *published* valid sprint-format version for *pkg*.

    Used as a fallback for ``Conga.Revenue.*`` packages when NuGet MCP returns a
    conflicting (legacy) version string (e.g. ``2024011.2.2``).

    Query: ``$orderby=Published+desc&$top=1``

    No year filter is applied - ordering by ``Published`` date is sufficient and
    year-agnostic. This handles year-boundary cases correctly: e.g. in January 2025
    the latest packages may still be ``202412.*`` (prior year), which a year-prefix
    filter of ``2025`` would incorrectly exclude.

    Ordering by ``Published`` (not ``Version``) avoids the lexicographic trap where
    legacy ``2024011.*`` versions sort above valid sprint versions as strings.
    """
    import urllib.request, base64
    url = (
        f"{source}/FindPackagesById()"
        f"?id='{pkg}'"
        f"&$orderby=Published+desc&$top=1"
    )
    req = urllib.request.Request(url)
    if creds:
        token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            import xml.etree.ElementTree as ET
            ns = {
                "d":    "http://schemas.microsoft.com/ado/2007/08/dataservices",
                "atom": "http://www.w3.org/2005/Atom",
            }
            root  = ET.fromstring(resp.read())
            entry = root.find("atom:entry", ns)
            if entry is None:
                return None
            ver_el = entry.find(".//d:Version", ns)
            return ver_el.text.strip() if ver_el is not None else None
    except Exception:
        return None


def cmd_find_revenue_version(args):
    """Resolve latest versions for ``Conga.Revenue.*`` packages.

    Workflow:
    1. Accept ``--nuget-versions`` JSON map (versions already fetched by NuGet MCP).
    2. For each package, check if the NuGet MCP version is a **conflicting** (legacy)
       version string via ``_is_conflicting_version`` (format-based: valid sprint versions
       match ``YYYYMM.sprint.minor`` with a 6-digit date prefix).
    3. If conflicting: fall back to OData ``$orderby=Published+desc&$top=1`` to get the
       true latest by publish date - no year filter, works across year boundaries.
    4. If not conflicting (valid sprint format e.g. ``202412.2.3``): use the NuGet MCP
       value as-is (no OData call needed).

    Outputs JSON: {"PackageName": "resolved_version", ...}
    Packages resolved via OData fallback are flagged in stderr with ``[odata-fallback]``.
    """
    source       = args.source
    sol_path     = Path(args.solution_path).resolve() if args.solution_path else None
    creds        = (args.username, args.password) if args.username else _read_nuget_creds(source, sol_path)
    nuget_map: dict[str, str] = json.loads(args.nuget_versions) if args.nuget_versions else {}

    # Auto-discover packages from solution if no explicit nuget-versions provided
    if not nuget_map and args.solution_path:
        prefix = args.prefix
        root   = Path(args.solution_path).resolve()
        all_pkgs: dict[str, str] = {}
        for f in _csproj_files(root):
            all_pkgs.update(_platform_pkgs(f, prefix))
        if not all_pkgs:
            print(json.dumps({"error": f"No {prefix} packages found in {root}"}), file=sys.stdout)
            return 1
        # Without NuGet MCP versions, every package needs OData resolution
        nuget_map = {pkg: "" for pkg in all_pkgs}
        print(f"  [scan] discovered {len(nuget_map)} package(s) with prefix '{prefix}'", file=sys.stderr)

    if not nuget_map:
        print("ERROR: provide --nuget-versions JSON or --solution-path", file=sys.stderr)
        return 1

    resolved: dict[str, str] = {}
    failed:   list[str]      = []

    for pkg, nuget_ver in nuget_map.items():
        if nuget_ver and not _is_conflicting_version(nuget_ver):
            # NuGet MCP version is valid - no OData call needed
            resolved[pkg] = nuget_ver
            print(f"  [nuget-mcp] {pkg} -> {nuget_ver}", file=sys.stderr)
        else:
            reason = f"legacy version '{nuget_ver}'" if nuget_ver else "no version supplied"
            print(f"  [odata-fallback] {pkg} <- conflicting {reason}, querying OData...", file=sys.stderr)
            ver = _find_latest_revenue_via_odata(pkg, source, creds)
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
    """Resolve the highest minor in *sprint* for each Conga.Platform.* package.

    Packages are auto-discovered from ``--solution-path`` (preferred) or supplied
    explicitly via ``--packages``.
    Each package requires one OData HTTP call (~0.3 s).
    Outputs JSON: {"PackageName": "resolved_version", ...}
    """
    sprint = args.sprint
    source = args.source
    sol_path = Path(args.solution_path).resolve() if args.solution_path else None
    creds  = (args.username, args.password) if args.username else _read_nuget_creds(source, sol_path)

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

    for pkg in packages:
        ver = _find_via_odata(pkg, sprint, source, creds)
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


# -- generate-pr-body ----------------------------------------------------------
# Reads upgrades/plan.json written by Copilot at Step 4 (after user confirms).
# plan.json shape:
#   {
#     "title":   "Upgrade Conga packages: Platform 202604.1 + Revenue latest",
#     "sprint":  "202604.1",
#     "changes": [{"project": "Asset.API", "namespace": "Platform",
#                  "package": "Authorization.Middleware",
#                  "from": "202602.1.8", "to": "202604.1.8"}, ...],
#     "skipped": ["Conga.Revenue.Callbacks - reason"]
#   }

_BODY = (
    "## {title}\n\n"
    "**Date:** {date}\n\n"
    "---\n### Packages Updated\n\n"
    "| Project | Namespace | Package | From | To |\n"
    "|---------|-----------|---------|------|----|\n"
    "{rows}\n\n"
    "{skipped_block}"
    "---\n### Build & Test\n\n"
    "{test_block}\n\n"
    "---\n### Checklist\n"
    "- [x] `dotnet build` passed\n"
    "- [{tick}] All unit tests passing\n"
    "- [x] Only `Conga.*` versions modified\n"
    "- [x] Draft PR - ready for review\n\n"
    "*Generated by `conga-package-upgrader` skill.*\n"
)

def cmd_generate_pr_body(args):
    """Generate PR body from plan.json (written by Copilot at Step 4) + optional TRX."""
    plan  = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    title = plan.get("title", "Upgrade Conga Packages")

    rows = [
        f"| `{c['project']}` | {c['namespace']} | `{c['package']}` | `{c['from']}` | `{c['to']}` |"
        for c in plan.get("changes", [])
    ]

    skipped = plan.get("skipped", [])
    skipped_block = (
        "---\n### Skipped\n\n"
        + "\n".join(f"- {s}" for s in skipped)
        + "\n\n"
    ) if skipped else ""

    trx_s = parse_trx(args.trx_path) if args.trx_path else None
    if trx_s:
        tick       = "x" if trx_s["failed"] == 0 else " "
        test_block = format_test_results_table(trx_s)
    else:
        tick, test_block = "x", "_No TRX file - verify tests manually._"

    body = _BODY.format(
        title         = title,
        date          = datetime.now().strftime("%Y-%m-%d %H:%M"),
        rows          = "\n".join(rows),
        skipped_block = skipped_block,
        test_block    = test_block,
        tick          = tick,
    )

    out = write_markdown(body, UPGRADES_DIR / "pr-body.md")
    print(f"PR body -> {out}")
    return 0


# -- command configuration (declarative) --------------------------------------

_SHARED_SOLUTION_ARGS = [
    ("--solution-path", {"default": "."}),
    ("--prefix", {"default": DEFAULT_PREFIX, "help": "Package name prefix (default: Conga.Platform.)"}),
]

_COMMANDS = [
    ("scan", cmd_scan, _SHARED_SOLUTION_ARGS),

    ("patch", cmd_patch, _SHARED_SOLUTION_ARGS + [
        ("--versions", {"required": True, "help": 'JSON map {"Package":"version",...}'}),
        ("--target-sprint", {"default": "unknown"}),
    ]),

    ("find-target-version", cmd_find_target_version, [
        ("--solution-path", {"default": None, "help": "Solution root; auto-discovers all packages with --prefix (preferred)"}),
        ("--prefix", {"default": DEFAULT_PREFIX, "help": "Package prefix used with --solution-path (default: Conga.Platform.)"}),
        ("--packages", {"default": None, "help": "Comma-separated package IDs (alternative to --solution-path)"}),
        ("--sprint", {"required": True, "help": "Target sprint prefix, e.g. 202604.1"}),
        ("--source", {"default": "https://art01.apttuscloud.io/artifactory/api/nuget/conga-platform-nuget", "help": "NuGet v2 feed URL"}),
        ("--username", {"default": None, "help": "Feed username (optional; uses NuGet.Config if omitted)"}),
        ("--password", {"default": None, "help": "Feed password / API key"}),
    ]),

    # Revenue packages: NuGet MCP version used as-is unless it fails the sprint-format
    # check (YYYYMM.sprint.minor, 6-digit date prefix). Conflicting legacy versions
    # (e.g. 2024011.* with 7-digit prefix) trigger OData $orderby=Published+desc fallback
    # to get the true latest by publish date - no year filter, works across year boundaries.
    ("find-revenue-version", cmd_find_revenue_version, [
        ("--nuget-versions", {"default": None, "help": 'JSON map {"Package":"nuget-mcp-version",...} from NuGet MCP; conflicting versions trigger OData fallback'}),
        ("--solution-path", {"default": None, "help": "Solution root; auto-discovers Conga.Revenue.* packages when --nuget-versions is omitted"}),
        ("--prefix", {"default": "Conga.Revenue.", "help": "Package prefix for solution scan (default: Conga.Revenue.)"}),
        ("--source", {"default": "https://art01.apttuscloud.io/artifactory/api/nuget/conga-platform-nuget", "help": "NuGet v2 feed URL"}),
        ("--username", {"default": None, "help": "Feed username (optional; uses NuGet.Config if omitted)"}),
        ("--password", {"default": None, "help": "Feed password / API key"}),
    ]),

    ("parse-trx", None, [
        ("--trx-path", {"required": True}),
    ]),

    ("generate-pr-body", cmd_generate_pr_body, [
        ("--plan", {"default": str(UPGRADES_DIR / "plan.json"), "help": "Path to plan.json written by Copilot at Step 4"}),
        ("--trx-path", {"default": None}),
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
