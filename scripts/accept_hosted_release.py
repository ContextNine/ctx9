#!/usr/bin/env python3
"""Exercise the packaged launcher with real GitHub Sigstore and synthetic components."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from unittest.mock import patch

REPOSITORY = "ContextNine/ctx9"
WORKFLOW = ".github/workflows/test.yml@refs/heads/master"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--cosign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = os.environ.get("GITHUB_SHA", "")
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/master" or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or os.environ.get("GITHUB_WORKFLOW_REF") != f"{REPOSITORY}/{WORKFLOW}"
        or os.environ.get("GITHUB_WORKFLOW_SHA") != commit
        or not args.cosign.is_absolute() or not args.cosign.is_file()):
        raise RuntimeError("hosted-context-required")
    sidecar = json.loads(Path(str(args.archive) + ".release.json").read_bytes())
    version = sidecar["version"]
    if (sidecar["source_commit"] != commit or sidecar["component"] != "ctx9"
        or sidecar["artifact"] != {"name": args.archive.name, "sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest()}):
        raise RuntimeError("archive-source-mismatch")
    public_environment = {name: os.environ[name] for name in ("HOME", "PATH", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR") if name in os.environ}
    with tempfile.TemporaryDirectory(prefix="ctx9-hosted-acceptance-") as temporary:
        root = Path(temporary)
        with tarfile.open(args.archive) as archive:
            if any(not member.isfile() or Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in archive):
                raise RuntimeError("archive-layout-invalid")
            archive.extractall(root, filter="data")
        source = root / f"ctx9-{version}"
        install = [os.sys.executable, str(source / "scripts/install.py"), "--install-dir", str(root / "bin"),
                   "--data-dir", str(root / "installed"), "--json"]
        for extra, changed in (([], True), ([], False), (["--verify"], False)):
            result = subprocess.run([*install, *extra], env=public_environment, check=True, capture_output=True, text=True, timeout=30)
            report = json.loads(result.stdout)
            if not report["ready"] or report["changed"] is not changed:
                raise RuntimeError("isolated-installation-failed")
        result = subprocess.run([str(root / "bin/ctx9"), "--version"], env=public_environment,
                                check=True, capture_output=True, text=True, timeout=30)
        if result.stdout.strip() != f"ctx9 {version}":
            raise RuntimeError("installed-version-mismatch")
        spec = importlib.util.spec_from_file_location("installed_launcher", root / "installed/src/ctx9.py")
        assert spec and spec.loader
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        host, architecture = launcher.host_identity()
        component = root / "fixture-component"
        component.mkdir()
        (component / "install.py").write_text(
            "import argparse,json,os,pathlib\n"
            "p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--verify',action='store_true');p.add_argument('--json',action='store_true');a=p.parse_args()\n"
            "assert not any(k.startswith('CTX9_GITLAB_') or k in ['GITHUB_TOKEN','ACTIONS_ID_TOKEN_REQUEST_TOKEN','ACTIONS_ID_TOKEN_REQUEST_URL'] for k in os.environ)\n"
            "state=pathlib.Path(a.state);changed=not state.exists()\n"
            "if not a.verify and changed: state.write_text('synthetic-installed-state')\n"
            "print(json.dumps({'ready':state.is_file(),'changed':changed and not a.verify}));raise SystemExit(0 if state.is_file() else 1)\n")
        component_archive = root / "fixture.tar.gz"
        with tarfile.open(component_archive, "w:gz") as archive:
            archive.add(component, arcname=component.name)
        base = "https://gitlab.com/api/v4/projects/1/packages/generic/fixture/1.0.0/"
        digest = hashlib.sha256(component_archive.read_bytes()).hexdigest()
        catalog = {"schema_version": 1, "catalog_kind": "private-overlay", "credential_binding": launcher.PRIVATE_CREDENTIAL_BINDING,
            "components": [{"id": "fixture", "name": "Synthetic fixture", "version": "1.0.0", "platforms": [host],
                "architectures": [architecture], "provides": ["command:fixture"], "documentation": "https://example.invalid/fixture",
                "release": {"source_commit": commit, "minimum_launcher_version": version,
                    "provenance_url": base + "fixture-1.0.0.release.sigstore.json", "artifacts": [{"platform": host,
                        "architecture": architecture, "archive_url": base + "fixture.tar.gz", "archive_root": component.name,
                        "archive_sha256": digest}]},
                "installer": {"path": "install.py", "install_args": ["--state", str(root / "component-state")],
                              "doctor_args": ["--state", str(root / "component-state"), "--verify"]}}]}
        record = {"schema_version": 1, "signed": True, "values_returned": False, "private_catalog": catalog,
            "publication": {"provider": "github", "repository": REPOSITORY, "workflow_ref": f"{REPOSITORY}/{WORKFLOW}",
                            "workflow_commit": commit},
            "machine_release": {"product": "fixture", "version": "1.0.0", "source_commit": commit,
                "artifacts": [{"platform": host, "architecture": architecture, "name": "fixture.tar.gz", "sha256": digest}]}}
        record_path, bundle = root / "fixture.release.json", root / "fixture.release.sigstore.json"
        record_path.write_text(json.dumps(record))
        signing_environment = public_environment | {name: os.environ[name] for name in (
            "ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")}
        subprocess.run([str(args.cosign), "sign-blob", "--yes", "--bundle", str(bundle), str(record_path)],
                       env=signing_environment, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        documents = {base + "components.json": json.dumps(catalog).encode(),
            base + "fixture-1.0.0.release.json": record_path.read_bytes(),
            base + "fixture-1.0.0.release.sigstore.json": bundle.read_bytes()}
        empty = root / "empty.json"
        empty.write_text('{"schema_version":1,"components":[]}')

        def invoke(operation, *, provider="github", pins=()):
            arguments = ["--manifest", str(empty), "--private-catalog-url", base + "components.json",
                "--credential-binding", launcher.PRIVATE_CREDENTIAL_BINDING, "--provenance-provider", provider,
                "--provenance-project", REPOSITORY, "--expected-version", "1.0.0", *pins]
            if provider == "github":
                arguments.extend(["--provenance-workflow", WORKFLOW])
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                code = launcher.main([*arguments, operation, "fixture", "--json"])
            return code, json.loads(output.getvalue()) if output.getvalue() else None

        with (patch.dict(os.environ, {"CTX9_FLEET_DEPENDENCIES": str(root / "absent"),
                "CTX9_GITLAB_READ_USERNAME": "NOTENV_SENTINEL_USER", "CTX9_GITLAB_READ_TOKEN": "NOTENV_SENTINEL_TOKEN"}),
              patch.object(launcher, "private_read", side_effect=lambda url, binding: documents[url]),
              patch.object(launcher, "download", side_effect=lambda url, destination, **kwargs: shutil.copyfile(component_archive, destination))):
            code, preflight = invoke("preflight")
            if code or not preflight["trust_verified"]:
                raise RuntimeError("real-signature-not-accepted")
            pins = ["--expected-source-commit", commit, "--expected-catalog-sha256", preflight["catalog_sha256"]]
            for operation, changed in (("install", True), ("doctor", False), ("install", False)):
                code, result = invoke(operation, pins=pins)
                if code or not result[0]["ready"] or result[0]["result"]["changed"] is not changed:
                    raise RuntimeError("installed-component-lifecycle-failed")
            code, result = invoke("preflight", provider="gitlab")
            if code != 1 or result["state"] != "trust-rejected":
                raise RuntimeError("wrong-issuer-not-rejected")
            documents[base + "fixture-1.0.0.release.json"] = documents[base + "fixture-1.0.0.release.json"].replace(
                commit.encode(), ("f" * 40).encode())
            code, result = invoke("preflight")
            if code != 1 or result["state"] != "trust-rejected":
                raise RuntimeError("tampered-record-not-rejected")
        args.output.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(record_path, args.output / record_path.name)
        shutil.copyfile(bundle, args.output / bundle.name)
        receipt = {"schema_version": 1, "component": "ctx9", "version": version, "source_commit": commit,
            "platform": host, "architecture": architecture, "real_sigstore_verified": True,
            "isolated_archive_installation": True, "component_install_doctor_noop": True,
            "wrong_issuer_and_tampered_record_rejected": True, "daily_installation_changed": False,
            "fixture_transport": "synthetic", "native_custody_verified": False, "values_returned": False}
        (args.output / "acceptance.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
        print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"ready":false,"code":"hosted-launcher-acceptance-failed","values_returned":false}')
        raise SystemExit(1)
