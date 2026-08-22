#!/usr/bin/env python3
"""Install and verify independently released CTX9 components."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "0.1.0"


class LauncherError(RuntimeError):
    pass


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parent.parent / "components.json"


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError(f"cannot read component manifest {path}: {error}") from error
    if data.get("schema_version") != 1 or not isinstance(data.get("components"), list):
        raise LauncherError("unsupported component manifest")
    ids: set[str] = set()
    for component in data["components"]:
        component_id = component.get("id")
        if not isinstance(component_id, str) or not component_id or component_id in ids:
            raise LauncherError("component IDs must be unique non-empty strings")
        ids.add(component_id)
        release = component.get("release", {})
        digest = release.get("archive_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise LauncherError(f"{component_id}: invalid archive SHA-256")
    return data


def host_identity() -> tuple[str, str]:
    if sys.platform == "darwin":
        operating_system = "macos"
    elif sys.platform.startswith("linux"):
        operating_system = "linux"
    else:
        raise LauncherError(f"unsupported platform: {sys.platform}")
    architecture = platform.machine().lower()
    architecture = {"arm64": "aarch64", "amd64": "x86_64"}.get(
        architecture, architecture
    )
    return operating_system, architecture


def component_by_id(manifest: dict[str, Any], component_id: str) -> dict[str, Any]:
    for component in manifest["components"]:
        if component["id"] == component_id:
            return component
    raise LauncherError(f"unknown component: {component_id}")


def ensure_supported(component: dict[str, Any]) -> None:
    operating_system, architecture = host_identity()
    if operating_system not in component["platforms"]:
        raise LauncherError(f"{component['id']} does not support {operating_system}")
    if architecture not in component["architectures"]:
        raise LauncherError(f"{component['id']} does not support {architecture}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"ctx9/{VERSION}"})
    try:
        with urllib.request.urlopen(request) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except (OSError, urllib.error.URLError) as error:
        raise LauncherError(f"download failed for {url}: {error}") from error


def extract_archive(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise LauncherError(f"unsafe archive path: {member.name}")
            if member.issym() or member.islnk():
                raise LauncherError(f"archive links are not allowed: {member.name}")
        archive.extractall(destination, members=members)


def run_component(component: dict[str, Any], mode: str) -> dict[str, Any]:
    ensure_supported(component)
    release = component["release"]
    installer = component["installer"]
    args_key = "doctor_args" if mode == "doctor" else "install_args"
    with tempfile.TemporaryDirectory(prefix="ctx9-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "component.tar.gz"
        download(release["archive_url"], archive_path)
        actual_digest = sha256(archive_path)
        if actual_digest != release["archive_sha256"]:
            raise LauncherError(
                f"{component['id']}: checksum mismatch; expected "
                f"{release['archive_sha256']}, got {actual_digest}"
            )
        extract_archive(archive_path, temporary_path)
        root = temporary_path / release["archive_root"]
        installer_path = root / installer["path"]
        if not installer_path.is_file():
            raise LauncherError(f"{component['id']}: installer is missing from release")
        completed = subprocess.run(
            [sys.executable, str(installer_path), *installer[args_key], "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise LauncherError(f"{component['id']}: {mode} failed: {detail}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise LauncherError(
                f"{component['id']}: installer returned invalid JSON"
            ) from error
        if not result.get("ready"):
            raise LauncherError(f"{component['id']}: installer did not report ready")
        return {
            "component": component["id"],
            "operation": mode,
            "version": component["version"],
            "ready": True,
            "result": result,
        }


def emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    if isinstance(value, list):
        for item in value:
            if "operation" in item:
                print(f"{item['component']} {item['version']}: {item['operation']} ready")
            else:
                provides = ", ".join(item["provides"])
                print(f"{item['id']} {item['version']} [{provides}]")
        return
    print(value)


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="ctx9")
    command_parser.add_argument("--version", action="version", version=f"ctx9 {VERSION}")
    command_parser.add_argument(
        "--manifest", type=Path, default=default_manifest_path(), help=argparse.SUPPRESS
    )
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    list_parser = subcommands.add_parser("list", help="list available components")
    list_parser.add_argument("--json", action="store_true")
    for name in ("install", "update", "doctor"):
        operation_parser = subcommands.add_parser(name)
        operation_parser.add_argument("component", nargs="?" if name != "install" else None)
        operation_parser.add_argument("--json", action="store_true")
    return command_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "list":
            result = [
                {
                    "id": component["id"],
                    "name": component["name"],
                    "version": component["version"],
                    "provides": component["provides"],
                    "documentation": component["documentation"],
                }
                for component in manifest["components"]
            ]
            emit(result, args.json)
            return 0
        selected = (
            [component_by_id(manifest, args.component)]
            if args.component
            else manifest["components"]
        )
        mode = "doctor" if args.command == "doctor" else "install"
        results = [run_component(component, mode) for component in selected]
        emit(results, args.json)
        return 0
    except LauncherError as error:
        print(f"ctx9: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
