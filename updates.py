"""Update check: is there a newer Halo Battery release on GitHub?

Once a day the app asks GitHub for the latest release (the public REST API, no token,
one small request). When it is newer than the running version, the tray shows a
notification once for that version and the menu gets a "Download vX.Y.Z..." item that
installs the release after the user clicks it in a packaged Windows build.
Source runs open the release page instead. Checks never install without a click.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote
from typing import Optional, Tuple

REPO = "Ash91323/HaloBattery"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY = 24 * 3600          # seconds between checks
TIMEOUT = 10


def migrate_source(cfg: dict) -> bool:
    """Forget cached upstream releases when moving to this fork's feed."""
    if cfg.get("update_repo") == REPO:
        return False
    for key in ("update_latest", "update_url", "update_notified", "update_last"):
        cfg.pop(key, None)
    cfg["update_repo"] = REPO
    return True


def parse_version(text: str) -> Optional[Tuple[int, ...]]:
    """'v1.11.0' / '1.11.0' -> (1, 11, 0); anything else -> None."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)\s*$", text or "")
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def fetch_latest(current: str) -> Tuple[str, str]:
    """-> (version without the 'v', release page URL). Raises on network or API errors."""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"HaloBattery/{current}",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # A personal fork may not have published its first release yet.
            return current, RELEASES_URL
        raise
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        raise ValueError(f"unexpected tag name {tag!r}")
    return tag.lstrip("vV").strip(), f"https://github.com/{REPO}/releases/tag/{quote(tag, safe='')}"
