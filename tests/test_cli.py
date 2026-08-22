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
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            capture_output=True,
            env=env,
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
        self.assertEqual(version.stdout.strip(), "ctx9 0.2.0")
        listed = self.run_cli("list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)[0]["id"], "codex-repo-sync")

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
            command = [
                sys.executable,
                str(INSTALLER),
                "--install-dir",
                str(root / "bin"),
                "--data-dir",
                str(root / "share" / "ctx9"),
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
            installed = subprocess.run(
                [str(root / "bin" / "ctx9"), "--version"],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(installed.stdout.strip(), "ctx9 0.2.0")

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


if __name__ == "__main__":
    unittest.main()
