from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

import test_cli

MODULE = test_cli.MODULE


class PrivateReleaseJourney(unittest.TestCase):
    def test_exact_trusted_preflight_and_install_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = test_cli.LauncherTests().fake_manifest(root)
            manifest = json.loads(public.read_text())
            component = manifest["components"][0]
            platform, architecture = MODULE.host_identity()
            base = "https://gitlab.com/api/v4/projects/1/packages/generic/fixture/1.0.0/"
            archive = component["release"]
            manifest.update(catalog_kind="private-overlay", credential_binding="ctx9-gitlab-group-read")
            component["release"] = {
                "source_commit": "a" * 40,
                "minimum_launcher_version": "0.3.0",
                "provenance_url": base + "fake-1.0.0.release.sigstore.json",
                "artifacts": [{"platform": platform, "architecture": architecture, "archive_url": base + "fake.tar.gz", "archive_root": archive["archive_root"], "archive_sha256": archive["archive_sha256"]}],
            }
            record = {
                "schema_version": 1, "signed": True, "values_returned": False,
                "private_catalog": copy.deepcopy(manifest),
                "machine_release": {"product": "fake", "version": "1.0.0", "source_commit": "a" * 40, "artifacts": [{"platform": platform, "architecture": architecture, "name": "fake.tar.gz", "sha256": archive["archive_sha256"]}]},
            }
            blob = json.dumps(record).encode()
            identity = "https://gitlab.com/example/fixture//.gitlab-ci.yml@refs/tags/v1.0.0"
            # Synthetic verifier tests delegation and binding, not Sigstore cryptography.
            verifier = root / "cosign"
            verifier.write_text(
                "#!/usr/bin/env python3\nimport hashlib,json,os,sys\n"
                "args=sys.argv[1:]\n"
                "bundle=json.load(open(args[args.index('--bundle')+1]))\n"
                "valid=hashlib.sha256(open(args[-1],'rb').read()).hexdigest()==bundle['digest']\n"
                "valid=valid and args[args.index('--certificate-identity')+1]==bundle['identity']\n"
                "valid=valid and args[args.index('--certificate-oidc-issuer')+1]=='https://gitlab.com'\n"
                "valid=valid and not any(k.startswith('CTX9_GITLAB_') for k in os.environ)\n"
                "sys.exit(0 if valid else 1)\n"
            )
            verifier.chmod(0o755)
            documents = {
                base + "components.json": json.dumps(manifest).encode(),
                base + "fake-1.0.0.release.json": blob,
                base + "fake-1.0.0.release.sigstore.json": json.dumps({"digest": hashlib.sha256(blob).hexdigest(), "identity": identity}).encode(),
            }
            empty = root / "public.json"
            empty.write_text(json.dumps({"schema_version": 1, "components": []}))
            argv = ["--manifest", str(empty), "--private-catalog-url", base + "components.json", "--credential-binding", "ctx9-gitlab-group-read", "--provenance-project", "example/fixture", "--expected-version", "1.0.0"]

            def invoke(operation: str = "preflight", arguments: list[str] | None = None):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = MODULE.main([*(arguments or argv), operation, "fake", "--json"])
                return code, json.loads(output.getvalue())

            with (
                mock.patch.dict(os.environ, {"CTX9_GITLAB_READ_USERNAME": "synthetic-user", "CTX9_GITLAB_READ_TOKEN": "synthetic-token", "CTX9_FLEET_DEPENDENCIES": str(root / "absent")}),
                mock.patch.object(MODULE, "private_read", side_effect=lambda url, binding: documents[url]),
                mock.patch.object(MODULE.shutil, "which", return_value=str(verifier)),
            ):
                code, report = invoke()
                self.assertEqual(code, 0)
                self.assertTrue(report["trust_verified"])
                self.assertFalse(report["archive_verified"])
                self.assertEqual(report["source_commit"], "a" * 40)
                catalog_digest = report["catalog_sha256"]
                with mock.patch.object(MODULE, "download", side_effect=lambda url, destination, **kwargs: destination.write_bytes(Path(archive["archive_url"].removeprefix("file://")).read_bytes())):
                    code, report = invoke("install")
                    self.assertEqual(code, 0)
                    self.assertTrue(report[0]["ready"])
                bad_signer = ["wrong/project" if arg == "example/fixture" else arg for arg in argv]
                self.assertEqual(invoke(arguments=bad_signer)[1]["state"], "trust-rejected")
                changed = copy.deepcopy(manifest)
                changed["components"][0]["release"]["artifacts"][0]["archive_sha256"] = "b" * 64
                documents[base + "components.json"] = json.dumps(changed).encode()
                with mock.patch.object(MODULE, "run_component", side_effect=AssertionError("untrusted installer executed")):
                    self.assertEqual(invoke()[1]["state"], "trust-rejected")
                documents[base + "components.json"] = json.dumps(manifest).encode()
                # A valid new signature under the same version is not the reviewed release.
                pinned = [*argv, "--expected-source-commit", "a" * 40, "--expected-catalog-sha256", catalog_digest]
                self.assertEqual(invoke(arguments=pinned)[0], 0)
                changed = copy.deepcopy(manifest)
                changed["components"][0]["release"]["source_commit"] = "b" * 40
                changed_record = copy.deepcopy(record)
                changed_record["private_catalog"] = changed
                changed_record["machine_release"]["source_commit"] = "b" * 40
                changed_blob = json.dumps(changed_record).encode()
                documents.update({
                    base + "components.json": json.dumps(changed).encode(),
                    base + "fake-1.0.0.release.json": changed_blob,
                    base + "fake-1.0.0.release.sigstore.json": json.dumps({"digest": hashlib.sha256(changed_blob).hexdigest(), "identity": identity}).encode(),
                })
                self.assertEqual(invoke()[1]["source_commit"], "b" * 40)
                self.assertEqual(invoke(arguments=pinned)[1]["state"], "release-changed")
                self.assertEqual(invoke(arguments=[*argv, "--expected-source-commit", "invalid"])[1]["state"], "invalid-release")
                with mock.patch.object(MODULE, "run_component", side_effect=AssertionError("changed release executed")), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(MODULE.main([*pinned, "install", "fake", "--json"]), 1)
                # Same commit, valid new signature, changed archive metadata is also denied.
                changed["components"][0]["release"]["source_commit"] = "a" * 40
                changed["components"][0]["release"]["artifacts"][0]["archive_sha256"] = "e" * 64
                changed_record["machine_release"]["source_commit"] = "a" * 40
                changed_record["machine_release"]["artifacts"][0]["sha256"] = "e" * 64
                changed_blob = json.dumps(changed_record).encode()
                documents.update({base + "components.json": json.dumps(changed).encode(), base + "fake-1.0.0.release.json": changed_blob, base + "fake-1.0.0.release.sigstore.json": json.dumps({"digest": hashlib.sha256(changed_blob).hexdigest(), "identity": identity}).encode()})
                self.assertEqual(invoke()[0], 0)
                self.assertEqual(invoke(arguments=pinned)[1]["state"], "release-changed")
                with mock.patch.object(MODULE, "run_component", side_effect=AssertionError("changed catalog executed")), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(MODULE.main([*pinned, "install", "fake", "--json"]), 1)
                documents.update({base + "components.json": json.dumps(manifest).encode(), base + "fake-1.0.0.release.json": blob, base + "fake-1.0.0.release.sigstore.json": json.dumps({"digest": hashlib.sha256(blob).hexdigest(), "identity": identity}).encode()})
                with mock.patch.object(MODULE.shutil, "which", return_value=None):
                    self.assertEqual(invoke()[1]["state"], "verifier-unavailable")
                changed = copy.deepcopy(manifest)
                changed["components"][0]["release"]["artifacts"][0]["architecture"] = "unsupported"
                documents[base + "components.json"] = json.dumps(changed).encode()
                self.assertEqual(invoke()[1]["state"], "platform-incompatible")

    def test_private_transport_and_native_state_never_echo_provider_output(self) -> None:
        url = "https://gitlab.com/api/v4/projects/1/packages/generic/fixture/1.0.0/components.json"
        for status, state in ((401, "credential-rejected"), (403, "access-denied"), (404, "release-unavailable"), (429, "rate-limited"), (500, "transport-unavailable")):
            with (
                self.subTest(status=status),
                mock.patch.dict(os.environ, {"CTX9_GITLAB_READ_USERNAME": "synthetic", "CTX9_GITLAB_READ_TOKEN": "synthetic"}),
                mock.patch.object(MODULE.urllib.request, "build_opener") as opener,
            ):
                opener.return_value.open.side_effect = urllib.error.HTTPError(url, status, "sensitive provider output", {}, None)
                with self.assertRaises(MODULE.PreflightError) as raised:
                    MODULE.private_read(url, "ctx9-gitlab-group-read")
                self.assertEqual(raised.exception.state, state)
        with self.assertRaises(MODULE.LauncherError):
            MODULE.safe_private_url("https://another-host.invalid/components.json")
        with self.assertRaises(MODULE.PreflightError):
            MODULE.NoPrivateRedirect().redirect_request(None, None, 302, None, {}, "https://another-host.invalid")
        with mock.patch.dict(os.environ, {"CTX9_GITLAB_READ_USERNAME": "synthetic", "CTX9_GITLAB_READ_TOKEN": "synthetic"}), mock.patch.object(MODULE.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b'{"fixture":true}')
            self.assertEqual(MODULE.private_read(url, "ctx9-gitlab-group-read"), b'{"fixture":true}')
            opener.return_value.open.return_value = io.BytesIO(b"oversized")
            with self.assertRaises(MODULE.PreflightError) as raised:
                MODULE.private_read(url, "ctx9-gitlab-group-read", limit=4)
            self.assertEqual(raised.exception.state, "invalid-release")
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper.py"
            helper.touch()
            for native_state, state in (("expired", "credential-expired"), ("credential store is locked", "credential-locked"), ("credential is missing", "credential-missing"), ("sensitive provider output", "credential-unavailable")):
                output = io.StringIO()
                process = subprocess.CompletedProcess([], 1, json.dumps({"ready": False, "state": native_state}), "sensitive provider output")
                with mock.patch.object(MODULE, "default_private_helper_path", return_value=helper), mock.patch.object(MODULE.subprocess, "run", return_value=process), redirect_stdout(output):
                    self.assertEqual(MODULE.private_auth_preflight([]), 1)
                self.assertEqual(json.loads(output.getvalue())["state"], state)
                self.assertNotIn("sensitive", output.getvalue())


if __name__ == "__main__":
    unittest.main()
