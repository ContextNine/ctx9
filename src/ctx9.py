#!/usr/bin/env python3
"""Install and verify independently released CTX9 components."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "0.3.14"
PRIVATE_CREDENTIAL_BINDING = "ctx9-gitlab-group-read"
PRIVATE_AUTH_GUARD = "CTX9_PRIVATE_AUTH_READY"


class LauncherError(RuntimeError):
    pass


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parent.parent / "components.json"


def default_private_helper_path() -> Path:
    override = os.environ.get("CTX9_PRIVATE_HELPER")
    return Path(override).expanduser() if override else Path.home() / ".local/libexec/ctx9/private-read.py"


def default_fleet_dependency_path() -> Path:
    override = os.environ.get("CTX9_FLEET_DEPENDENCIES")
    return Path(override).expanduser() if override else Path.home() / ".agents/package/_package/defaults/dependencies.json"


def validate_component(component: dict[str, Any], *, private: bool) -> None:
    component_id = component.get("id")
    release = component.get("release", {})
    if private:
        if not isinstance(release.get("source_commit"), str) or not is_hex(release["source_commit"], 40):
            raise LauncherError(f"{component_id}: private release requires an exact source commit")
        version_tuple(component.get("version", ""))
        minimum = release.get("minimum_launcher_version")
        if not isinstance(minimum, str) or version_tuple(VERSION) < version_tuple(minimum):
            raise LauncherError(f"{component_id}: launcher upgrade required")
        artifacts = release.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise LauncherError(f"{component_id}: private release artifacts are required")
        identities: set[tuple[str, str]] = set()
        for artifact in artifacts:
            digest = artifact.get("archive_sha256") if isinstance(artifact, dict) else None
            if not isinstance(digest, str) or not is_hex(digest, 64):
                raise LauncherError(f"{component_id}: invalid archive SHA-256")
            if not all(isinstance(artifact.get(key), str) and artifact[key] for key in ("platform", "architecture", "archive_url", "archive_root")):
                raise LauncherError(f"{component_id}: incomplete private artifact")
            safe_private_url(artifact["archive_url"])
            identity = artifact["platform"], artifact["architecture"]
            if identity in identities:
                raise LauncherError(f"{component_id}: duplicate private host artifact")
            identities.add(identity)
        return
    digest = release.get("archive_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise LauncherError(f"{component_id}: invalid archive SHA-256")


def version_tuple(value: str) -> tuple[int, int, int]:
    try:
        parts = value.removeprefix("v").split(".")
        if len(parts) != 3:
            raise ValueError
        numbers = tuple(int(part) for part in parts)
        return numbers[0], numbers[1], numbers[2]
    except ValueError as error:
        raise LauncherError(f"invalid semantic version: {value}") from error


def is_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def validate_manifest(data: Any, *, private: bool) -> dict[str, Any]:
    expected_kind = "private-overlay" if private else None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("components"), list):
        raise LauncherError("unsupported component manifest")
    if data.get("catalog_kind") != expected_kind:
        raise LauncherError("component manifest kind mismatch")
    if private and data.get("credential_binding") != PRIVATE_CREDENTIAL_BINDING:
        raise LauncherError("private catalog credential binding mismatch")
    ids: set[str] = set()
    for component in data["components"]:
        component_id = component.get("id") if isinstance(component, dict) else None
        if not isinstance(component_id, str) or not component_id or component_id in ids:
            raise LauncherError("component IDs must be unique non-empty strings")
        ids.add(component_id)
        validate_component(component, private=private)
        component["_private"] = private
    return data


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError(f"cannot read component manifest {path}: {error}") from error
    return validate_manifest(data, private=False)


def private_headers(binding: str) -> dict[str, str]:
    if binding != PRIVATE_CREDENTIAL_BINDING:
        raise LauncherError("unsupported private catalog credential binding")
    username = os.environ.get("CTX9_GITLAB_READ_USERNAME")
    token = os.environ.get("CTX9_GITLAB_READ_TOKEN")
    if not username or not token:
        raise LauncherError(
            "private catalog credential is unavailable; run ctx9 auth verify"
        )
    encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def safe_private_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise LauncherError("private catalog URL must be credential-free HTTPS")


def load_private_manifest(url: str, binding: str) -> dict[str, Any]:
    safe_private_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"ctx9/{VERSION}", **private_headers(binding)},
    )
    try:
        with urllib.request.urlopen(request) as response:
            data = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise LauncherError("private catalog retrieval failed") from error
    return validate_manifest(data, private=True)


def configured_private_catalogs(path: Path | None = None) -> list[tuple[str, str]]:
    registry = path or default_fleet_dependency_path()
    if not registry.is_file():
        return []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError(f"cannot read fleet component configuration: {error}") from error
    if not isinstance(data, dict):
        raise LauncherError("unsupported fleet component configuration")
    dependencies = data.get("dependencies")
    if data.get("schema_version") != 2 or not isinstance(dependencies, list):
        raise LauncherError("unsupported fleet component configuration")
    catalogs: list[tuple[str, str]] = []
    for dependency in dependencies:
        contract = dependency.get("contract") if isinstance(dependency, dict) else None
        recipes = contract.get("recipes") if isinstance(contract, dict) else None
        if not isinstance(recipes, dict):
            continue
        for recipe in recipes.values():
            if not isinstance(recipe, dict) or recipe.get("manager") != "ctx9-component":
                continue
            url = recipe.get("private_catalog_url")
            binding = recipe.get("credential_binding")
            if url is None and binding is None:
                continue
            if not isinstance(url, str) or binding != PRIVATE_CREDENTIAL_BINDING:
                raise LauncherError("fleet private component configuration is invalid")
            catalog = (url, binding)
            if catalog not in catalogs:
                catalogs.append(catalog)
    return catalogs


def run_private_helper(arguments: list[str], *, env: dict[str, str] | None = None) -> int:
    helper = default_private_helper_path()
    if not helper.is_file():
        raise LauncherError(
            "private component access is not enrolled; run the fleet onboarding workflow"
        )
    return subprocess.run(
        [sys.executable, str(helper), *arguments],
        check=False,
        env=env,
    ).returncode


def reexec_with_private_auth(argv: list[str]) -> int:
    if os.environ.get(PRIVATE_AUTH_GUARD) == "1":
        raise LauncherError("private component access did not provide credentials")
    environment = dict(os.environ)
    environment[PRIVATE_AUTH_GUARD] = "1"
    return run_private_helper(
        [
            "exec",
            "--",
            sys.executable,
            str(Path(__file__).resolve()),
            *argv,
        ],
        env=environment,
    )


def merge_manifests(public: dict[str, Any], private: dict[str, Any] | None) -> dict[str, Any]:
    if private is None:
        return public
    components = [*public["components"], *private["components"]]
    ids = [component["id"] for component in components]
    if len(ids) != len(set(ids)):
        raise LauncherError("private catalog cannot replace a public component")
    return {"schema_version": 1, "components": components}


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


def download(url: str, destination: Path, *, private: bool = False) -> None:
    if private:
        safe_private_url(url)
    headers = {"User-Agent": f"ctx9/{VERSION}"}
    if private:
        headers.update(private_headers(PRIVATE_CREDENTIAL_BINDING))
    request = urllib.request.Request(url, headers=headers)
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
    args_key = {
        "doctor": "doctor_args",
        "rollback": "rollback_args",
        "uninstall": "uninstall_args",
    }.get(mode, "install_args")
    if args_key not in installer:
        raise LauncherError(f"{component['id']}: {mode} is not supported")
    private = component.get("_private") is True
    if private:
        operating_system, architecture = host_identity()
        matches = [
            artifact
            for artifact in release["artifacts"]
            if artifact["platform"] == operating_system and artifact["architecture"] == architecture
        ]
        if len(matches) != 1:
            raise LauncherError(f"{component['id']}: exact host artifact is unavailable")
        artifact = matches[0]
    else:
        artifact = release
    with tempfile.TemporaryDirectory(prefix="ctx9-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "component.tar.gz"
        download(artifact["archive_url"], archive_path, private=private)
        actual_digest = sha256(archive_path)
        if actual_digest != artifact["archive_sha256"]:
            raise LauncherError(
                f"{component['id']}: checksum mismatch; expected "
                f"{artifact['archive_sha256']}, got {actual_digest}"
            )
        extract_archive(archive_path, temporary_path)
        root = temporary_path / artifact["archive_root"]
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
    command_parser.add_argument("--private-catalog-url", help=argparse.SUPPRESS)
    command_parser.add_argument("--credential-binding", help=argparse.SUPPRESS)
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    auth_parser = subcommands.add_parser("auth", help="inspect or use private component access")
    auth_parser.add_argument("action", choices=("status", "verify"))
    auth_parser.add_argument("--json", action="store_true")
    list_parser = subcommands.add_parser("list", help="list available components")
    list_parser.add_argument("--json", action="store_true")
    for name in ("install", "update", "doctor", "rollback", "uninstall"):
        operation_parser = subcommands.add_parser(name)
        operation_parser.add_argument("component", nargs="?" if name != "install" else None)
        operation_parser.add_argument("--json", action="store_true")
    return command_parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(raw)
    try:
        if args.command == "auth":
            return run_private_helper([args.action, *(["--json"] if args.json else [])])
        public_manifest = load_manifest(args.manifest)
        if bool(args.private_catalog_url) != bool(args.credential_binding):
            raise LauncherError("private catalog URL and credential binding must be provided together")
        public_ids = {component["id"] for component in public_manifest["components"]}
        needs_private_catalog = (
            bool(args.private_catalog_url)
            or args.command == "list"
            or not getattr(args, "component", None)
            or args.component not in public_ids
        )
        catalogs = []
        if needs_private_catalog:
            catalogs = (
                [(args.private_catalog_url, args.credential_binding)]
                if args.private_catalog_url
                else configured_private_catalogs()
            )
        if catalogs and not (
            os.environ.get("CTX9_GITLAB_READ_USERNAME")
            and os.environ.get("CTX9_GITLAB_READ_TOKEN")
        ):
            return reexec_with_private_auth(raw)
        manifest = public_manifest
        for url, binding in catalogs:
            manifest = merge_manifests(manifest, load_private_manifest(url, binding))
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
        mode = args.command if args.command in {"doctor", "rollback", "uninstall"} else "install"
        results = [run_component(component, mode) for component in selected]
        emit(results, args.json)
        return 0
    except LauncherError as error:
        print(f"ctx9: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
