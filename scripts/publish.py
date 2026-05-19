#!/usr/bin/env python3
"""Pre-deploy checks and PyPI publish script."""

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import tomllib
from packaging.version import parse as parse_version

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
PYPI_URL = "https://pypi.org/pypi/obsidian-ai-miniserver/json"


def project_python() -> str:
    """Prefer project .venv so checks see installed deps (obs_ai_ms, uvicorn, etc.)."""
    for name in ("python", "python3"):
        candidate = ROOT / ".venv" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def read_version() -> str:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["version"]


def published_version() -> str | None:
    """Fetch current version from PyPI, or None if not published."""
    try:
        with urlopen(PYPI_URL, timeout=10) as resp:
            import json
            return json.loads(resp.read())["info"]["version"]
    except (HTTPError, URLError):
        return None


def check_version(version: str) -> bool:
    remote = published_version()
    if remote is None:
        print(f"  ✓ Version {version} (not yet on PyPI)")
        return True
    if parse_version(version) > parse_version(remote):
        print(f"  ✓ Version {version} > published {remote}")
        return True
    print(f"  ✗ Version {version} <= published {remote}")
    return False


def changelog_sections(text: str) -> set[str]:
    """Parse `##` section titles (Keep a Changelog style)."""
    sections: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("##") or stripped.startswith("###"):
            continue
        header = stripped[2:].strip().lstrip("v")
        if header.startswith("["):
            header = header[1:].split("]")[0]
        elif " - " in header:
            header = header.split(" - ", 1)[0].strip()
        sections.add(header)
    return sections


def check_changelog(version: str, *, deploy: bool) -> bool:
    if not CHANGELOG.exists():
        print(f"  ✗ {CHANGELOG.name} not found")
        return False
    text = CHANGELOG.read_text()
    sections = changelog_sections(text)
    if deploy:
        if version in sections:
            print(f"  ✓ Changelog has release section for {version}")
            return True
        print(
            f"  ✗ Changelog missing release section for {version} "
            "(rename ## Unreleased to match pyproject before deploy)"
        )
        return False
    if version in sections:
        print(f"  ✓ Changelog has entry for {version}")
        return True
    if "Unreleased" in sections:
        print("  ✓ Changelog has ## Unreleased (fold into release version before deploy)")
        return True
    print(f"  ✗ Changelog missing ## Unreleased or entry for {version}")
    return False


def check_tests() -> bool:
    result = subprocess.run(
        [project_python(), "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  ✓ Tests pass")
        return True
    print("  ✗ Tests failed")
    if result.stdout:
        for line in result.stdout.splitlines()[-5:]:
            print(f"    {line}")
    return False


def check_screenshots() -> bool:
    result = subprocess.run(
        [project_python(), str(ROOT / "scripts" / "update_screenshots.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  ✓ Screenshots up to date")
        return True
    print("  ✗ Screenshots update failed")
    if result.stderr:
        for line in result.stderr.splitlines()[-5:]:
            print(f"    {line}")
    return False


def check_git_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        print("  ✓ Git clean")
        return True
    print("  ✗ Uncommitted changes:")
    for line in result.stdout.strip().splitlines():
        print(f"    {line}")
    return False


def check_token(token: str | None) -> str | None:
    tok = token or os.environ.get("TWINE_TOKEN") or os.environ.get("TWINE_PASSWORD")
    if tok:
        print("  ✓ PyPI token present")
        return tok
    print("  ✗ No PyPI token (set TWINE_TOKEN or TWINE_PASSWORD or pass --token)")
    return None


def run_checks(
    token: str | None,
    *,
    skip_git_clean: bool = False,
    skip_pypi_token: bool = False,
    deploy: bool = False,
) -> tuple[bool, str | None]:
    """Run all pre-deploy checks. Returns (all_passed, resolved_token)."""
    version = read_version()
    print(f"Pre-deploy checks for obsidian-ai-miniserver v{version}:\n")

    results = []
    results.append(check_version(version))
    results.append(check_changelog(version, deploy=deploy))
    results.append(check_tests())
    results.append(check_screenshots())
    if skip_git_clean:
        print("  (skipped git clean — working tree may have uncommitted changes)")
    else:
        results.append(check_git_clean())
    if skip_pypi_token:
        print("  (skipped PyPI token check)")
        tok = token or os.environ.get("TWINE_TOKEN") or os.environ.get("TWINE_PASSWORD")
    else:
        tok = check_token(token)
        results.append(tok is not None)

    print()
    all_passed = all(results)
    if all_passed:
        print("All checks passed.")
    else:
        print("Some checks failed.")
    return all_passed, tok


def deploy(version: str, token: str) -> None:
    print(f"\nDeploying v{version}...\n")

    # Clean old dist files
    for f in glob.glob(str(ROOT / "dist" / "*")):
        os.remove(f)

    # Build distributables
    print("  Building distributables...")
    subprocess.run([project_python(), "-m", "build"], cwd=ROOT, check=True)

    # Git tag (skip if already exists from a partial deploy)
    tag = f"v{version}"
    existing = subprocess.run(
        ["git", "tag", "-l", tag], cwd=ROOT, capture_output=True, text=True
    )
    if existing.stdout.strip():
        print(f"  Tag {tag} already exists, skipping")
    else:
        print(f"  Tagging {tag}...")
        subprocess.run(["git", "tag", tag], cwd=ROOT, check=True)

    # Upload to PyPI
    print("  Uploading to PyPI...")
    dist_files = sorted(glob.glob(str(ROOT / "dist" / "*")))
    if not dist_files:
        print("  ✗ No files found in dist/")
        sys.exit(1)
    subprocess.run(
        ["twine", "upload", *dist_files],
        env={**os.environ, "TWINE_PASSWORD": token, "TWINE_USERNAME": "__token__"},
        check=True,
    )
    print(f"\nPublished v{version} to PyPI.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-deploy checks and publish")
    parser.add_argument("--check", action="store_true", help="Run checks only (default)")
    parser.add_argument("--deploy", action="store_true", help="Run checks then deploy")
    parser.add_argument("--token", help="PyPI API token (or set TWINE_TOKEN)")
    parser.add_argument(
        "--skip-git-clean",
        action="store_true",
        help="Do not require a clean git working tree (for local release prep)",
    )
    parser.add_argument(
        "--skip-pypi-token",
        action="store_true",
        help="Do not require TWINE_TOKEN (cannot use with --deploy)",
    )
    args = parser.parse_args()

    # Default to --check if nothing specified
    if not args.deploy:
        args.check = True

    if args.deploy and args.skip_pypi_token:
        print("Cannot --deploy with --skip-pypi-token.", file=sys.stderr)
        sys.exit(1)

    passed, token = run_checks(
        args.token,
        skip_git_clean=args.skip_git_clean,
        skip_pypi_token=args.skip_pypi_token,
        deploy=args.deploy,
    )

    if not passed:
        sys.exit(1)

    if args.deploy:
        if not token:
            print("Deploy requires a PyPI token.", file=sys.stderr)
            sys.exit(1)
        deploy(read_version(), token)
    elif not args.check:
        # Neither flag set — just ran checks
        pass


if __name__ == "__main__":
    main()
