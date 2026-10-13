"""Check release prerequisites, build the HACS archive and extract release notes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = Path("custom_components/sabatark")


def check_release(tag: str, root: Path = ROOT) -> str:
    """Check that the tag matches the manifest and its library pin exists on PyPI."""
    manifest = json.loads((root / INTEGRATION / "manifest.json").read_text())
    version = manifest["version"]
    if not tag.startswith("v") or tag[1:] != version:
        raise ValueError(f"Tag {tag!r} must be v{version} to match manifest.json.")
    pins = [
        requirement
        for requirement in manifest["requirements"]
        if re.fullmatch(r"sabatark==[0-9][A-Za-z0-9.!+_-]*", requirement)
    ]
    if len(pins) != 1:
        raise ValueError("manifest.json must contain one exact sabatark==X requirement.")
    library_version = pins[0].split("==", 1)[1]
    url = f"https://pypi.org/pypi/sabatark/{library_version}/json"
    message = (
        f"Cannot confirm sabatark=={library_version} on PyPI. "
        "Release python-sabatark first and wait for that version to be available on PyPI."
    )
    try:
        with urlopen(url, timeout=20) as response:
            if response.status != 200:
                raise ValueError(message)
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(message) from error
    return version


def build_archive(output: Path, root: Path = ROOT) -> None:
    """Build and verify an archive containing the integration contents at its root."""
    source = root / INTEGRATION
    manifest = source / "manifest.json"
    json.loads(manifest.read_text())
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("The release archive must be outside the integration directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.relative_to(source).parts
                and path.suffix not in {".pyc", ".pyo"}
                and path.name != ".DS_Store"
            ):
                archive.write(path, path.relative_to(source).as_posix())
    with ZipFile(output) as archive:
        names = archive.namelist()
        if (
            "manifest.json" not in names
            or any(name.startswith("custom_components/") for name in names)
            or any("__pycache__" in Path(name).parts for name in names)
            or archive.read("manifest.json") != manifest.read_bytes()
            or archive.testzip() is not None
        ):
            raise ValueError("Release archive failed root-layout or integrity validation.")


def release_notes(version: str, root: Path = ROOT) -> str:
    """Extract this version's section from CHANGELOG.md."""
    changelog = (root / "CHANGELOG.md").read_text()
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, changelog, flags=re.MULTILINE | re.DOTALL)
    if match is None or not match[1].strip():
        raise ValueError(f"CHANGELOG.md has no release notes for {version}.")
    return match[1].strip() + "\n"


def main() -> None:
    """Run the requested release operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("--tag", required=True)
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    notes = commands.add_parser("notes")
    notes.add_argument("--version", required=True)
    notes.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check":
            print(f"version={check_release(args.tag)}")
        elif args.command == "build":
            build_archive(args.output)
        else:
            content = release_notes(args.version)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(status=1, message=f"Release failed: {error}\n")


if __name__ == "__main__":
    main()
