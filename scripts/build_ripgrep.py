#!/usr/bin/env python3
"""Fetch and verify the Windows ripgrep binary used by the packaged backend."""

from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "15.2.0"
ARCHIVE_NAME = f"ripgrep-{VERSION}-x86_64-pc-windows-msvc.zip"
ARCHIVE_URL = (
    f"https://github.com/BurntSushi/ripgrep/releases/download/"
    f"{VERSION}/{ARCHIVE_NAME}"
)
ARCHIVE_SHA256 = "71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5"

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "ripgrep"
ARCHIVE = CACHE / ARCHIVE_NAME
RESOURCE_ROOT = ROOT / "gui" / "src-tauri" / "resources" / "python"
DESTINATION = RESOURCE_ROOT / "bin" / "rg.exe"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download() -> None:
    if ARCHIVE.is_file() and _sha256(ARCHIVE) == ARCHIVE_SHA256:
        return

    CACHE.mkdir(parents=True, exist_ok=True)
    partial = ARCHIVE.with_suffix(ARCHIVE.suffix + ".download")
    request = urllib.request.Request(
        ARCHIVE_URL,
        headers={"User-Agent": "xeyo-build-ripgrep"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            with partial.open("wb") as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
        actual = _sha256(partial)
        if actual != ARCHIVE_SHA256:
            raise SystemExit(
                f"ripgrep checksum mismatch: expected {ARCHIVE_SHA256}, got {actual}"
            )
        partial.replace(ARCHIVE)
    finally:
        if partial.exists():
            partial.unlink()


def _install() -> None:
    with zipfile.ZipFile(ARCHIVE) as bundle:
        members = bundle.infolist()
        binary = [
            item
            for item in members
            if PurePosixPath(item.filename.replace("\\", "/")).name.lower()
            == "rg.exe"
        ]
        if len(binary) != 1:
            raise SystemExit(f"expected one rg.exe in {ARCHIVE_NAME}, found {len(binary)}")

        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        temporary = DESTINATION.with_name("rg.exe.download")
        temporary.write_bytes(bundle.read(binary[0]))
        temporary.replace(DESTINATION)

        license_dir = DESTINATION.parent / "licenses"
        for item in members:
            name = PurePosixPath(item.filename.replace("\\", "/")).name
            if name.upper() not in {"LICENSE-MIT", "UNLICENSE"}:
                continue
            license_dir.mkdir(parents=True, exist_ok=True)
            (license_dir / name).write_bytes(bundle.read(item))

    result = subprocess.run(
        [str(DESTINATION), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or f"ripgrep {VERSION}" not in result.stdout:
        raise SystemExit(
            f"ripgrep verification failed: {result.stdout.strip()} {result.stderr.strip()}"
        )


def main() -> None:
    if os.name != "nt":
        raise SystemExit("build_ripgrep.py creates the Windows x64 app resource")
    _download()
    _install()
    print(f"Bundled {DESTINATION.relative_to(ROOT)} ({VERSION})")


if __name__ == "__main__":
    main()
