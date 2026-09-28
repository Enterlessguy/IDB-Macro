"""Checking GitHub Releases for a newer version, and fetching it safely."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO = "Enterlessguy/IDB-Macro"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
ASSET_NAME = "IDB-Macro-windows-x64.zip"
# Downloads are only accepted from GitHub itself and its release CDN.
ALLOWED_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
MAX_API_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
TIMEOUT_S = 15


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    version: str
    name: str
    notes: str
    page_url: str
    asset_url: str = ""
    asset_size: int = 0
    sha256: str = ""
    sha256_url: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        raise UpdateError(f"not a version: {text!r}")
    return tuple(int(p) for p in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _check_url(url: str) -> None:
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"refusing to download from {parts.hostname or url}")


def _open(url: str):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "IDB-Macro-updater",  # noqa: S310 - checked above
                                               "Accept": "application/vnd.github+json"})
    resp = urllib.request.urlopen(req, timeout=TIMEOUT_S)  # noqa: S310 - https + host allowlist above
    _check_url(resp.geturl())  # redirects must stay on GitHub too
    return resp


def _read_capped(resp, cap: int) -> bytes:
    data = resp.read(cap + 1)
    if len(data) > cap:
        raise UpdateError("the response was unexpectedly large")
    return data


def parse_release(doc: dict) -> Release:
    if not isinstance(doc, dict) or not isinstance(doc.get("tag_name"), str):
        raise UpdateError("GitHub returned an unexpected answer")
    parse_version(doc["tag_name"])
    rel = Release(version=doc["tag_name"].lstrip("v"), name=str(doc.get("name") or doc["tag_name"])[:200],
                  notes=str(doc.get("body") or "")[:20_000], page_url=str(doc.get("html_url") or RELEASES_PAGE))
    for asset in doc.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") == ASSET_NAME:
            rel.asset_url = str(asset.get("browser_download_url", ""))
            rel.asset_size = int(asset.get("size") or 0)
            digest = str(asset.get("digest") or "")
            if digest.startswith("sha256:"):
                rel.sha256 = digest.split(":", 1)[1].lower()
        elif asset.get("name") == ASSET_NAME + ".sha256":
            rel.sha256_url = str(asset.get("browser_download_url", ""))
    return rel


def fetch_latest() -> Release:
    try:
        with _open(API_LATEST) as resp:
            doc = json.loads(_read_capped(resp, MAX_API_BYTES))
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from None
    return parse_release(doc)


def expected_digest(rel: Release) -> str:
    if rel.sha256:
        return rel.sha256
    if rel.sha256_url:
        with _open(rel.sha256_url) as resp:
            text = _read_capped(resp, 4096).decode("ascii", "replace")
        match = re.search(r"\b[0-9a-fA-F]{64}\b", text)
        if match:
            return match.group(0).lower()
    raise UpdateError("the release has no checksum, so it can't be verified")


def download(rel: Release, dest: Path, progress=lambda done, total: None) -> Path:
    """Download the release zip to ``dest`` and verify its SHA-256. Returns the file path."""
    if not rel.asset_url:
        raise UpdateError("this release has no Windows download")
    want = expected_digest(rel)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / ASSET_NAME
    digest = hashlib.sha256()
    done = 0
    try:
        with _open(rel.asset_url) as resp, path.open("wb") as fh:
            while chunk := resp.read(256 * 1024):
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("the download is unexpectedly large")
                digest.update(chunk)
                fh.write(chunk)
                progress(done, rel.asset_size)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"download failed: {exc}") from None
    if digest.hexdigest() != want:
        path.unlink(missing_ok=True)
        raise UpdateError("the download doesn't match the release checksum; it was deleted")
    return path


def safe_extract(zip_path: Path, target: Path) -> Path:
    """Extract, refusing any entry that would land outside ``target``. Returns the app folder."""
    target = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            out = (target / info.filename).resolve()
            if out != target and target not in out.parents:
                raise UpdateError(f"unsafe path in update: {info.filename}")
        zf.extractall(target)
    exe = next(target.rglob("IDB-Macro.exe"), None)
    if exe is None:
        raise UpdateError("the update doesn't contain IDB-Macro.exe")
    return exe.parent
