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


def check_changelog(version: str) -> bool:
    if not CHANGELOG.exists():
        print(f"  ✗ {CHANGELOG.name} not found")
        return False
    text = CHANGELOG.read_text()
    # Match version headers like "## 0.1.0", "## v0.1.0", "## [0.1.0] - date"
    for line in text.splitlines():
        header = line.strip().lstrip("#").strip().lstrip("v")
        if header.startswith("["):
            header = header[1:].split("]")[0]
        if header == version:
            print(f"  ✓ Changelog has entry for {version}")
            return True
    print(f"  ✗ Changelog missing entry for {version}")
    return False


def check_tests() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
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
        [sys.executable, str(ROOT / "scripts" / "update_screenshots.py")],
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


def run_checks(token: str | None) -> tuple[bool, str | None]:
    """Run all pre-deploy checks. Returns (all_passed, resolved_token)."""
    version = read_version()
    print(f"Pre-deploy checks for obsidian-ai-miniserver v{version}:\n")

    results = []
    results.append(check_version(version))
    results.append(check_changelog(version))
    results.append(check_tests())
    results.append(check_screenshots())
    results.append(check_git_clean())
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
    subprocess.run([sys.executable, "-m", "build"], cwd=ROOT, check=True)

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
    args = parser.parse_args()

    # Default to --check if nothing specified
    if not args.deploy:
        args.check = True

    passed, token = run_checks(args.token)

    if not passed:
        sys.exit(1)

    if args.deploy:
        deploy(read_version(), token)
    elif not args.check:
        # Neither flag set — just ran checks
        pass


if __name__ == "__main__":
    main()
