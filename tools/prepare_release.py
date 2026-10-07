"""Select the release version in CI without creating bot commits.

main push/manual run: increment the highest source/tag version's patch component.
Explicit tag: require it to match the checked-in VERSION.
Manual runs on other branches build artifacts without publishing.
"""
from pathlib import Path
import os
import re
import subprocess

try:
    from .release_notes import section
except ImportError:
    from release_notes import section

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r'^VERSION = "(\d+\.\d+\.\d+)"', re.M)


def next_version(base, tags):
    versions = [tuple(map(int, base.split('.')))]
    for tag in tags:
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\.\d+)?", tag)
        if match:
            versions.append(tuple(map(int, match.groups())))
    major, minor, patch = max(versions)
    patch += 1
    if patch > 65535:
        minor, patch = minor + 1, 0
    if minor > 65535:
        major, minor = major + 1, 0
    if major > 65535:
        raise ValueError("Version exceeds Windows version resource limits")
    return f"{major}.{minor}.{patch}"


def prepare(root, ref_type, ref_name, tags, sha):
    root = Path(root)
    source_path = root / "halo_battery.pyw"
    source = source_path.read_text(encoding="utf-8")
    match = VERSION_RE.search(source)
    if not match:
        raise ValueError("Expected a three-component VERSION in halo_battery.pyw")
    base = match.group(1)
    publish = ref_type == "tag" or ref_name == "main"
    if ref_type == "tag":
        if ref_name != f"v{base}":
            raise ValueError(f"Tag {ref_name} does not match VERSION {base}")
        version = base
        notes = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    elif ref_name == "main":
        version = next_version(base, tags)
        source_path.write_text(VERSION_RE.sub(f'VERSION = "{version}"', source, count=1), encoding="utf-8")
        try:
            notes = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), "Unreleased")
        except LookupError:
            notes = "Personal build from main.\n"
    else:
        version, notes = base, "Preview build; no release published.\n"
    notes = f"Built from commit `{sha}`.\n\n" + notes
    (root / "release_notes.md").write_text(notes, encoding="utf-8")
    return dict(version=version, tag=f"v{version}", publish=str(publish).lower())


def main():
    tags = subprocess.check_output(["git", "tag", "--list"], cwd=ROOT, text=True).splitlines()
    result = prepare(ROOT, os.environ.get("GITHUB_REF_TYPE", "branch"),
                     os.environ.get("GITHUB_REF_NAME", ""), tags,
                     os.environ.get("GITHUB_SHA", "local"))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            for key, value in result.items():
                stream.write(f"{key}={value}\n")
    print(result)


if __name__ == "__main__":
    main()
