from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "src" / "ctx9.py"
INSTALLER = ROOT / "scripts" / "install.py"
SPEC = importlib.util.spec_from_file_location("ctx9_launcher", CLI)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LauncherTests(unittest.TestCase):
    def run_cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = {
            **os.environ,
            "CTX9_FLEET_DEPENDENCIES": "/nonexistent/ctx9-test-dependencies.json",
            **(env or {}),
        }
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def fake_manifest(self, root: Path, digest_override: str | None = None) -> Path:
        source = root / "fake-component-1.0.0"
        (source / "scripts").mkdir(parents=True)
        installer = source / "scripts" / "install.py"
        installer.write_text(
            """#!/usr/bin/env python3
import argparse, json
p = argparse.ArgumentParser()
p.add_argument('--verify', action='store_true')
p.add_argument('--json', action='store_true')
a = p.parse_args()
print(json.dumps({'component': 'fake', 'ready': True, 'changed': not a.verify}))
""",
            encoding="utf-8",
        )
        archive = root / "fake.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(source, arcname=source.name)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "components": [
                {
                    "id": "fake",
                    "name": "Fake",
                    "version": "1.0.0",
                    "platforms": ["macos", "linux"],
                    "architectures": ["aarch64", "x86_64"],
                    "release": {
                        "repository": "example/fake",
                        "tag": "v1.0.0",
                        "archive_url": archive.as_uri(),
                        "archive_sha256": digest_override or digest,
                        "archive_root": source.name,
                    },
                    "installer": {
                        "path": "scripts/install.py",
                        "install_args": [],
                        "doctor_args": ["--verify"],
                    },
                    "provides": ["command:fake"],
                    "documentation": "https://example.com/fake",
                }
            ],
        }
        path = root / "components.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_list_and_version(self) -> None:
        version = self.run_cli("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "ctx9 0.3.24")
        listed = self.run_cli("list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        component_ids = {component["id"] for component in json.loads(listed.stdout)}
        self.assertEqual(
            component_ids,
            {
                "codex-repo-sync",
                "codefoldersync",
                "publisher",
                "testimonials",
                "fleet",
                "vault",
            },
        )

    def test_private_auth_exec_is_not_a_public_command(self) -> None:
        result = self.run_cli("auth", "exec")
        self.assertEqual(result.returncode, 2)

    def test_auth_json_is_forwarded_to_private_helper(self) -> None:
        with mock.patch.object(MODULE, "run_private_helper", return_value=0) as helper:
            self.assertEqual(MODULE.main(["auth", "status", "--json"]), 0)
        helper.assert_called_once_with(["status", "--json"])

    def test_component_install_update_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.fake_manifest(Path(temporary))
            for operation in ("install", "update", "doctor"):
                result = self.run_cli(
                    "--manifest", str(manifest), operation, "fake", "--json"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)[0]
                self.assertTrue(payload["ready"])
                self.assertEqual(
                    payload["operation"], "doctor" if operation == "doctor" else "install"
                )

    def test_checksum_mismatch_stops_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.fake_manifest(Path(temporary), "0" * 64)
            result = self.run_cli("--manifest", str(manifest), "install", "fake")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum mismatch", result.stderr)

    def test_launcher_install_verify_and_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_dir = root / "bin"
            data_dir = root / "share" / "ctx9"
            install_dir.mkdir()
            legacy_executable = data_dir / "src" / "ctx9.py"
            legacy_executable.parent.mkdir(parents=True)
            legacy_executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (install_dir / "ctx9").symlink_to(legacy_executable)
            command = [
                sys.executable,
                str(INSTALLER),
                "--install-dir",
                str(install_dir),
                "--data-dir",
                str(data_dir),
                "--json",
            ]
            first = subprocess.run(command, text=True, capture_output=True, check=False)
            second = subprocess.run(command, text=True, capture_output=True, check=False)
            verify = subprocess.run(
                [*command, "--verify"], text=True, capture_output=True, check=False
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(json.loads(first.stdout)["changed"])
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(json.loads(second.stdout)["changed"])
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["ready"])
            self.assertFalse((install_dir / "ctx9").is_symlink())
            installed = subprocess.run(
                [str(install_dir / "ctx9"), "--version"],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(installed.stdout.strip(), "ctx9 0.3.24")

    def test_public_component_operation_does_not_require_private_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.fake_manifest(Path(temporary))
            with (
                mock.patch.object(
                    MODULE,
                    "configured_private_catalogs",
                    side_effect=AssertionError("private catalog should not be loaded"),
                ),
                mock.patch.object(MODULE, "emit"),
            ):
                result = MODULE.main(["--manifest", str(manifest), "doctor", "fake", "--json"])
            self.assertEqual(result, 0)

    def test_private_overlay_requires_narrow_binding_and_selects_exact_platform(self) -> None:
        private = {
            "schema_version": 1,
            "catalog_kind": "private-overlay",
            "credential_binding": "ctx9-gitlab-group-read",
            "components": [
                {
                    "id": "private-fixture",
                    "name": "Private fixture",
                    "version": "1.0.0",
                    "platforms": ["macos", "linux"],
                    "architectures": ["aarch64", "x86_64"],
                    "release": {
                        "source_commit": "a" * 40,
                        "minimum_launcher_version": "0.2.0",
                        "artifacts": [
                            {
                                "platform": "macos",
                                "architecture": "aarch64",
                                "archive_url": "https://gitlab.com/example/private.tar.gz",
                                "archive_sha256": "1" * 64,
                                "archive_root": "fixture-1.0.0",
                            }
                        ],
                    },
                    "installer": {
                        "path": "scripts/install.py",
                        "install_args": [],
                        "doctor_args": ["--verify"],
                        "rollback_args": ["--rollback"],
                        "uninstall_args": ["--uninstall"],
                    },
                    "provides": ["command:fixture"],
                    "documentation": "https://example.com",
                }
            ],
        }
        with mock.patch.dict(
            os.environ,
            {"CTX9_GITLAB_READ_USERNAME": "synthetic", "CTX9_GITLAB_READ_TOKEN": "synthetic"},
            clear=False,
        ):
            validated = MODULE.validate_manifest(private, private=True)
            self.assertTrue(validated["components"][0]["_private"])
            headers = MODULE.private_headers("ctx9-gitlab-group-read")
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertNotIn("synthetic", json.dumps(validated))

    def test_private_overlay_fails_closed_without_credential_or_exact_metadata(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(MODULE.LauncherError, "credential is unavailable"):
                MODULE.private_headers("ctx9-gitlab-group-read")
        with self.assertRaisesRegex(MODULE.LauncherError, "credential-free HTTPS"):
            MODULE.safe_private_url("https://token@gitlab.com/catalog.json")
        with self.assertRaisesRegex(MODULE.LauncherError, "credential binding mismatch"):
            MODULE.validate_manifest(
                {
                    "schema_version": 1,
                    "catalog_kind": "private-overlay",
                    "credential_binding": "broad-token",
                    "components": [],
                },
                private=True,
            )

    def test_fleet_registry_adds_private_components_without_duplicate_platform_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "dependencies.json"
            catalog = (
                "https://gitlab.com/api/v4/projects/1/packages/generic/"
                "secret-bindings-machine/1.2.4/components.json"
            )
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "dependencies": [
                            {
                                "contract": {
                                    "recipes": {
                                        platform: {
                                            "manager": "ctx9-component",
                                            "private_catalog_url": catalog,
                                            "credential_binding": "ctx9-gitlab-group-read",
                                        }
                                        for platform in ("macos", "linux")
                                    }
                                }
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.configured_private_catalogs(registry),
                [(catalog, "ctx9-gitlab-group-read")],
            )


if __name__ == "__main__":
    unittest.main()
