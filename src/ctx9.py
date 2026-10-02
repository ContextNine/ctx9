#!/usr/bin/env python3
"""Install and verify independently released CTX9 components."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "0.3.24"
PRIVATE_CREDENTIAL_BINDING = "ctx9-gitlab-group-read"
PRIVATE_AUTH_GUARD = "CTX9_PRIVATE_AUTH_READY"
PREFLIGHT_STATES = {
    "ready", "credential-missing", "credential-locked", "credential-unavailable",
    "credential-expired", "credential-rejected", "access-denied", "release-unavailable",
    "rate-limited", "transport-unavailable", "invalid-release", "platform-incompatible",
    "launcher-upgrade-required", "trust-policy-missing", "verifier-unavailable", "trust-rejected", "release-changed",
}


class PreflightError(RuntimeError):
    def __init__(self, state: str):
        super().__init__(state)
        self.state = state


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
        if not isinstance(component_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", component_id):
            raise LauncherError("invalid private component ID")
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
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise LauncherError("private catalog URL must be credential-free HTTPS")
    if parsed.netloc != "gitlab.com" or not re.fullmatch(r"/api/v4/projects/[0-9]+/packages/generic/[a-z0-9-]+/[0-9]+\.[0-9]+\.[0-9]+/[A-Za-z0-9_.-]+", parsed.path):
        raise LauncherError("private reads require an exact GitLab package URL")


class NoPrivateRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise PreflightError("access-denied")


def private_read(url: str, binding: str, *, limit: int = 4 * 1024 * 1024) -> bytes:
    """Read bounded metadata without forwarding authentication across redirects."""
    safe_private_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": f"ctx9/{VERSION}", **private_headers(binding)})
    try:
        with urllib.request.build_opener(NoPrivateRedirect()).open(request, timeout=20) as response:
            deadline = time.monotonic() + 35
            chunks = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise PreflightError("transport-unavailable")
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise PreflightError("invalid-release")
            data = b"".join(chunks)
    except urllib.error.HTTPError as error:
        state = {401: "credential-rejected", 403: "access-denied", 404: "release-unavailable", 429: "rate-limited"}.get(error.code, "transport-unavailable")
        raise PreflightError(state) from None
    except (OSError, urllib.error.URLError, ValueError):
        raise PreflightError("transport-unavailable") from None
    if len(data) > limit:
        raise PreflightError("invalid-release")
    return data


def load_private_manifest(url: str, binding: str) -> dict[str, Any]:
    try:
        data = json.loads(private_read(url, binding))
    except (UnicodeError, json.JSONDecodeError):
        raise PreflightError("invalid-release") from None
    return validate_manifest(data, private=True)


def private_release_policy(url: str, project: str | None, version: str | None) -> str:
    """Trust comes from the caller's enrolled configuration, never catalog claims."""
    if not project or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+", project) or any(part in {".", ".."} for part in project.split("/")) or not version or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise PreflightError("trust-policy-missing")
    if not re.fullmatch(r"https://gitlab\.com/api/v4/projects/[0-9]+/packages/generic/[a-z0-9-]+/" + re.escape(version) + r"/components\.json", url):
        raise PreflightError("invalid-release")
    return f"https://gitlab.com/{project}//.gitlab-ci.yml@refs/tags/v{version}"


def verify_private_release(component: dict[str, Any], manifest: dict[str, Any], url: str, identity: str, version: str) -> dict[str, Any]:
    """Verify signed catalog/host digests before downloading executable code."""
    if component.get("version") != version:
        raise PreflightError("invalid-release")
    ensure_supported(component)
    operating_system, architecture = host_identity()
    artifacts = component["release"]["artifacts"]
    matches = [item for item in artifacts if (item["platform"], item["architecture"]) == (operating_system, architecture)]
    if len(matches) != 1:
        raise PreflightError("platform-incompatible")
    base = url.removesuffix("components.json")
    prefix = f"{component['id']}-{version}.release"
    if component["release"].get("provenance_url") != f"{base}{prefix}.sigstore.json":
        raise PreflightError("invalid-release")
    for artifact in artifacts:
        if not artifact["archive_url"].startswith(base) or "/" in artifact["archive_url"][len(base):] or not artifact["archive_url"][len(base):]:
            raise PreflightError("invalid-release")
        root = PurePosixPath(artifact["archive_root"])
        if len(root.parts) != 1 or root.is_absolute() or root.name in {".", ".."}:
            raise PreflightError("invalid-release")
    installer = component.get("installer")
    if not isinstance(installer, dict) or not isinstance(installer.get("path"), str):
        raise PreflightError("invalid-release")
    path = PurePosixPath(installer["path"])
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PreflightError("invalid-release")
    verifier = shutil.which("cosign")
    if verifier is None:
        raise PreflightError("verifier-unavailable")
    blob = private_read(f"{base}{prefix}.json", PRIVATE_CREDENTIAL_BINDING)
    bundle = private_read(f"{base}{prefix}.sigstore.json", PRIVATE_CREDENTIAL_BINDING)
    with tempfile.TemporaryDirectory(prefix="ctx9-trust-") as directory:
        root = Path(directory)
        blob_path, bundle_path = root / "release.json", root / "bundle.json"
        blob_path.write_bytes(blob)
        bundle_path.write_bytes(bundle)
        # The verifier has no need for private-read credentials or management authority.
        env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
        try:
            result = subprocess.run([verifier, "verify-blob", "--bundle", str(bundle_path), "--certificate-identity", identity, "--certificate-oidc-issuer", "https://gitlab.com", str(blob_path)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise PreflightError("verifier-unavailable") from None
        if result.returncode:
            raise PreflightError("trust-rejected")
    try:
        record = json.loads(blob)
        signed_catalog = record["private_catalog"]
        machine = record["machine_release"]
        catalog = {**manifest, "components": [{key: value for key, value in item.items() if key != "_private"} for item in manifest["components"]]}
        expected = {(item["platform"], item["architecture"], item["archive_url"][len(base):], item["archive_sha256"]) for item in artifacts}
        actual = {(item["platform"], item["architecture"], item["name"], item["sha256"]) for item in machine["artifacts"]}
        valid = record["schema_version"] == 1 and record["signed"] is True and record["values_returned"] is False and signed_catalog == catalog and machine["version"] == version and machine["source_commit"] == component["release"]["source_commit"] and machine["product"] == component["id"] and expected == actual and len(actual) == len(machine["artifacts"])
    except (UnicodeError, ValueError, KeyError, TypeError):
        raise PreflightError("invalid-release") from None
    if not valid:
        raise PreflightError("trust-rejected")
    catalog_sha256 = hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": 1, "state": "ready", "ready": True, "component": component["id"], "version": version, "source_commit": component["release"]["source_commit"], "catalog_sha256": catalog_sha256, "platform": operating_system, "architecture": architecture, "trust_verified": True, "archive_verified": False, "values_returned": False}


def preflight_failure(state: str) -> dict[str, Any]:
    return {"schema_version": 1, "state": state, "ready": False, "trust_verified": False, "values_returned": False}


def private_auth_preflight(raw: list[str]) -> int:
    """Only allow closed diagnostics out of the helper/reexecuted launcher."""
    helper = default_private_helper_path()
    if not helper.is_file():
        emit(preflight_failure("credential-missing"), True)
        return 1
    try:
        status = subprocess.run([sys.executable, str(helper), "status", "--json"], capture_output=True, text=True, timeout=30, check=False)
        payload = json.loads(status.stdout)
        if status.returncode or payload.get("ready") is not True:
            state = {"expired": "credential-expired", "credential is missing": "credential-missing", "credential metadata is missing": "credential-missing", "credential store is locked": "credential-locked"}.get(payload.get("state"), "credential-unavailable")
            emit(preflight_failure(state), True)
            return 1
        env = dict(os.environ)
        env[PRIVATE_AUTH_GUARD] = "1"
        result = subprocess.run([sys.executable, str(helper), "exec", "--", sys.executable, str(Path(__file__).resolve()), *raw], env=env, capture_output=True, text=True, timeout=150, check=False)
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or report.get("state") not in PREFLIGHT_STATES or report.get("values_returned") is not False:
            raise ValueError
        # Reconstruct the allowed result rather than forwarding any child output.
        if result.returncode == 0 and report.get("ready") is True and report.get("trust_verified") is True:
            fields = ("component", "version", "source_commit", "catalog_sha256", "platform", "architecture")
            if not all(isinstance(report.get(key), str) for key in fields):
                raise ValueError
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", report["component"]) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", report["version"]) or not is_hex(report["source_commit"], 40) or not is_hex(report["catalog_sha256"], 64) or report["platform"] not in {"macos", "linux"} or report["architecture"] not in {"aarch64", "x86_64"}:
                raise ValueError
            emit({**preflight_failure("ready"), **{key: report[key] for key in fields}, "ready": True, "trust_verified": True, "archive_verified": False}, True)
            return 0
        emit(preflight_failure(report["state"] if report["state"] != "ready" else "credential-unavailable"), True)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError):
        emit(preflight_failure("credential-unavailable"), True)
    return 1


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


def configured_private_policy(url: str) -> tuple[str | None, str | None]:
    registry = default_fleet_dependency_path()
    if not registry.is_file():
        return None, None
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
        matches = {
            (recipe.get("provenance_project"), dependency["contract"]["verify"].get("exact"))
            for dependency in data["dependencies"]
            for recipe in dependency.get("contract", {}).get("recipes", {}).values()
            if recipe.get("private_catalog_url") == url
        }
        if len(matches) != 1:
            return None, None
        return matches.pop()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise PreflightError("trust-policy-missing") from None


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
        opener = urllib.request.build_opener(NoPrivateRedirect()) if private else urllib.request.build_opener()
        with opener.open(request, timeout=30) as response, destination.open("wb") as output:
            deadline = time.monotonic() + 120
            size = 0
            while chunk := response.read1(1024 * 1024):
                size += len(chunk)
                if private and (time.monotonic() > deadline or size > 512 * 1024 * 1024):
                    raise PreflightError("transport-unavailable")
                output.write(chunk)
    except (OSError, urllib.error.URLError) as error:
        if private:
            raise PreflightError("transport-unavailable") from None
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
            if private:
                raise PreflightError("private-component-operation-failed")
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
            "result": {"ready": True, "changed": result.get("changed") is True, "values_returned": False} if private else result,
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
    command_parser.add_argument("--provenance-project", help=argparse.SUPPRESS)
    command_parser.add_argument("--expected-version", help=argparse.SUPPRESS)
    command_parser.add_argument("--expected-source-commit", help=argparse.SUPPRESS)
    command_parser.add_argument("--expected-catalog-sha256", help=argparse.SUPPRESS)
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    auth_parser = subcommands.add_parser("auth", help="inspect or use private component access")
    auth_parser.add_argument("action", choices=("status", "verify"))
    auth_parser.add_argument("--json", action="store_true")
    list_parser = subcommands.add_parser("list", help="list available components")
    list_parser.add_argument("--json", action="store_true")
    preflight_parser = subcommands.add_parser("preflight", help="verify exact private catalog, signer and host metadata without installation")
    preflight_parser.add_argument("component")
    preflight_parser.add_argument("--json", action="store_true")
    for name in ("install", "update", "doctor", "rollback", "uninstall"):
        operation_parser = subcommands.add_parser(name)
        operation_parser.add_argument("component", nargs="?" if name != "install" else None)
        operation_parser.add_argument("--json", action="store_true")
    return command_parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(raw)
    try:
        if args.expected_source_commit is not None and not re.fullmatch(r"[a-f0-9]{40}", args.expected_source_commit):
            raise PreflightError("invalid-release")
        if args.expected_catalog_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", args.expected_catalog_sha256):
            raise PreflightError("invalid-release")
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
            if args.command == "preflight":
                if os.environ.get(PRIVATE_AUTH_GUARD) == "1":
                    raise PreflightError("credential-unavailable")
                return private_auth_preflight(raw)
            return reexec_with_private_auth(raw)
        manifest = public_manifest
        private_sources = {}
        for url, binding in catalogs:
            private_manifest = load_private_manifest(url, binding)
            for item in private_manifest["components"]:
                private_sources[item["id"]] = (url, private_manifest)
            manifest = merge_manifests(manifest, private_manifest)
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
        if (args.expected_source_commit is not None or args.expected_catalog_sha256 is not None) and (len(selected) != 1 or selected[0].get("_private") is not True):
            raise PreflightError("invalid-release")
        trust_reports = []
        for component in selected:
            if component.get("_private") is not True:
                if args.command == "preflight":
                    raise PreflightError("invalid-release")
                continue
            url, private_manifest = private_sources[component["id"]]
            project, version = configured_private_policy(url)
            project = args.provenance_project or project
            version = args.expected_version or version
            identity = private_release_policy(url, project, version)
            report = verify_private_release(component, private_manifest, url, identity, version)
            if args.expected_source_commit is not None and report["source_commit"] != args.expected_source_commit:
                raise PreflightError("release-changed")
            if args.expected_catalog_sha256 is not None and report["catalog_sha256"] != args.expected_catalog_sha256:
                raise PreflightError("release-changed")
            trust_reports.append(report)
        if args.command == "preflight":
            emit(trust_reports[0], True)
            return 0
        mode = args.command if args.command in {"doctor", "rollback", "uninstall"} else "install"
        results = [run_component(component, mode) for component in selected]
        emit(results, args.json)
        return 0
    except PreflightError as error:
        if args.command == "preflight":
            emit(preflight_failure(error.state), True)
        else:
            print(f"ctx9: {error.state}", file=sys.stderr)
        return 1
    except (LauncherError, KeyError, TypeError, AttributeError) as error:
        if args.command == "preflight":
            detail = str(error)
            state = "launcher-upgrade-required" if "launcher upgrade required" in detail else "platform-incompatible" if "does not support" in detail else "invalid-release"
            emit(preflight_failure(state), True)
            return 1
        print(f"ctx9: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
