"""Verified personal-release downloads and a detached, rollback-capable installer.

The helper runs from a copy of the CURRENT app, so no loaded DLL belongs to the
installation being replaced. Only HaloBattery.exe and _internal are replaced;
portable settings/history and normal AppData settings remain untouched.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import quote, urlparse
import zipfile

import updates

MAX_DOWNLOAD = 200 * 1024 * 1024
MAX_UNPACKED = 600 * 1024 * 1024
APP_FILES = ("HaloBattery.exe", "_internal")


def read_release(version):
    if updates.parse_version(version) is None:
        raise ValueError("Invalid release version")
    url = f"https://api.github.com/repos/{updates.REPO}/releases/tags/v{quote(version, safe='')}"
    req = urllib.request.Request(url, headers={"User-Agent": "HaloBattery", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read(1024 * 1024))
    if data.get("tag_name") != f"v{version}" or data.get("draft") or data.get("prerelease"):
        raise ValueError("Release is not a published stable version")
    name = f"HaloBattery-{version}.zip"
    asset = next((a for a in data.get("assets", []) if a.get("name") == name), None)
    if not asset or asset.get("state") != "uploaded":
        raise ValueError("Release does not contain a ready Windows update ZIP")
    expected_url = f"https://github.com/{updates.REPO}/releases/download/v{version}/{name}"
    if asset.get("browser_download_url") != expected_url:
        raise ValueError("Update asset is not from the configured repository")
    digest = asset.get("digest", "") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("GitHub did not provide a SHA-256 digest for this asset")
    if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= MAX_DOWNLOAD:
        raise ValueError("Invalid update download size")
    return expected_url, digest[7:].lower(), asset["size"]


def download(url, digest, size, destination):
    req = urllib.request.Request(url, headers={"User-Agent": "HaloBattery"})
    sha, count = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=60) as response, open(destination, "wb") as output:
        final = urlparse(response.geturl())
        if final.scheme != "https" or not (final.hostname == "github.com" or
                (final.hostname or "").endswith(".githubusercontent.com")):
            raise ValueError("Unexpected update download host")
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            count += len(block)
            if count > size or count > MAX_DOWNLOAD:
                raise ValueError("Update exceeds expected download size")
            output.write(block)
            sha.update(block)
    if count != size or sha.hexdigest() != digest:
        raise ValueError("Update SHA-256 or size does not match GitHub")


def extract_package(archive, destination):
    """Validate the entire ZIP before extracting any files (including Windows ADS)."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as package:
        entries, seen, total = [], set(), 0
        for info in package.infolist():
            raw = info.orig_filename  # ZipInfo normalizes backslashes on Windows
            parts = PurePosixPath(raw).parts
            if ("\\" in raw or not parts or parts[0] != "HaloBattery" or
                    any(p in (".", "..") or ":" in p or p.rstrip(" .") != p for p in raw.rstrip('/').split('/'))):
                raise ValueError("Unsafe update archive path")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("Update archive contains a symbolic link")
            if len(parts) == 1 and info.is_dir():
                continue
            relative = parts[1:]
            for part in relative:
                if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
                    raise ValueError("Reserved Windows filename in update archive")
            if not relative or (relative[0] != "_internal" and relative != ("HaloBattery.exe",)):
                raise ValueError("Unexpected file in update archive")
            key = '/'.join(relative).casefold()
            if key in seen:
                raise ValueError("Duplicate update archive path")
            seen.add(key)
            total += info.file_size
            if total > MAX_UNPACKED or len(seen) > 10000:
                raise ValueError("Update archive is too large")
            entries.append((info, destination.joinpath(*relative)))
        if "halobattery.exe" not in seen or not any(p.startswith("_internal/") for p in seen):
            raise ValueError("Incomplete Windows application bundle")
        destination.mkdir(parents=True, exist_ok=False)
        for info, path in entries:
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
    with (destination / "HaloBattery.exe").open("rb") as executable:
        magic = executable.read(2)
    if magic != b"MZ" or not (destination / "_internal").is_dir():
        raise ValueError("Update does not contain a Windows executable")


def launch(executable, *args):
    return subprocess.Popen([str(executable), *args], cwd=str(Path(executable).parent),
                            creationflags=0x08000000 if sys.platform == "win32" else 0)


def prepare(version, current, executable, language):
    if not updates.is_newer(version, current):
        raise ValueError("Update must be newer than the running version")
    executable = Path(executable).resolve()
    target = executable.parent
    if executable.name != "HaloBattery.exe" or not (target / "_internal").is_dir():
        raise ValueError("One-click updates require the packaged Windows application")
    # Fail while the current app is still running if its folder is not writable.
    with tempfile.TemporaryFile(dir=target):
        pass
    url, digest, size = read_release(version)
    work = Path(tempfile.mkdtemp(prefix="HaloBattery-update-"))
    try:
        archive = work / "release.zip"
        download(url, digest, size, archive)
        extract_package(archive, work / "package")
        archive.unlink()
        runner = work / "runner"
        runner.mkdir()
        shutil.copy2(executable, runner / executable.name)
        shutil.copytree(target / "_internal", runner / "_internal")
        plan = dict(target=str(target), parent_pid=os.getpid(), language=language,
                    version=version)
        (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        return work
    except Exception:
        shutil.rmtree(work)
        raise


def start_helper(work):
    work = Path(work)
    process = launch(work / "runner/HaloBattery.exe", "--install-update", str(work / "plan.json"))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (work / "ready.txt").exists():
            return process
        if process.poll() is not None:
            break
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError("The update helper could not start; the running app was kept")


def wait_for_parent(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # process has already exited
            return
        raise OSError("Cannot wait for the running application")
    try:
        if kernel.WaitForSingleObject(handle, 60000) != 0:
            raise TimeoutError("The running application did not exit")
    finally:
        kernel.CloseHandle(handle)


def install_files(package, target, launch_app=launch):
    """Replace only app-owned paths, rolling back any partial replacement."""
    package, target = Path(package).resolve(), Path(target).resolve()
    if not all((package / name).exists() and (target / name).exists() for name in APP_FILES):
        raise ValueError("Missing application files")
    incoming = Path(tempfile.mkdtemp(prefix=".halo-incoming-", dir=target))
    backup = Path(tempfile.mkdtemp(prefix=".halo-backup-", dir=target))
    moved, installed = [], []
    try:
        shutil.copy2(package / APP_FILES[0], incoming / APP_FILES[0])
        shutil.copytree(package / APP_FILES[1], incoming / APP_FILES[1])
        for name in APP_FILES:
            os.replace(target / name, backup / name)
            moved.append(name)
            os.replace(incoming / name, target / name)
            installed.append(name)
        process = launch_app(target / "HaloBattery.exe")
        time.sleep(5)
        if process.poll() is not None:
            raise RuntimeError("The updated application exited during startup")
    except Exception:
        for name in reversed(installed):
            path = target / name
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        for name in moved:
            os.replace(backup / name, target / name)
        launch_app(target / "HaloBattery.exe")
        raise
    finally:
        shutil.rmtree(incoming)
    # Retain the last application files for manual recovery; no user data moved.
    return backup


def helper_main(plan_path):
    import i18n
    plan_path = Path(plan_path).resolve()
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        i18n.set_language(plan.get("language", "en"))
        (plan_path.parent / "ready.txt").write_text("ready", encoding="utf-8")
        wait_for_parent(int(plan["parent_pid"]))
        backup = install_files(plan_path.parent / "package", plan["target"])
        (plan_path.parent / "result.txt").write_text(f"Installed {plan['version']}\nBackup: {backup}", encoding="utf-8")
        return 0
    except Exception as error:
        (plan_path.parent / "result.txt").write_text(str(error), encoding="utf-8")
        ctypes.windll.user32.MessageBoxW(None, i18n.tr("Installation failed. The previous version was kept or restored.\n{error}", error=str(error)),
                                         i18n.tr("Update failed"), 0x10)
        return 1
