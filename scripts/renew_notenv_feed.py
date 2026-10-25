"""Renew an already admitted Notenv feed with its pinned official publisher.

This hosting task cannot select a release. New admission stays with Notenv's
protected publisher. Git publishes one complete generation without force.
"""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

SOURCE_SHA256 = "2151243764fc87a4db5421668c7903099ff82e75c248344770a305f80020ff2d"
SOURCE_URL = "https://github.com/ContextNine/ctx9/releases/download/notenv-v4.0.1/notenv-4.0.1-source.tar.gz"
IDENTITY = "https://github.com/ContextNine/notenv/.github/workflows/publish-stable-machine-update.yml@refs/heads/master"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=300, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_file(path):
    return json.loads(path.read_bytes())


def safe_file(root, name):
    path = root / name
    assert not Path(name).is_absolute() and ".." not in Path(name).parts
    assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
    return path


def prepare(root):
    assert os.environ["GITHUB_REPOSITORY"] == "ContextNine/ctx9"
    assert os.environ["GITHUB_REF"] == "refs/heads/master"
    root.mkdir(mode=0o700)
    archive = root / "publisher.tar.gz"
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response, archive.open("xb") as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            assert total < 128 * 1024 * 1024
            output.write(chunk)
    assert digest(archive) == SOURCE_SHA256
    with tarfile.open(archive, "r:gz") as bundle:
        assert all(Path(m.name).parts[0] == "notenv-public-source" for m in bundle.getmembers())
        bundle.extractall(root, filter="data")
    source = root / "notenv-public-source"
    run("pnpm", "install", "--frozen-lockfile", cwd=source)
    feed = root / "feed"
    run("git", "clone", "--single-branch", "--branch", "notenv-stable", "https://github.com/ContextNine/ctx9.git", str(feed))
    base = subprocess.check_output(["git", "-C", str(feed), "rev-parse", "HEAD"], text=True).strip()
    admission = json_file(feed / "admission.json")
    assert admission["kind"] == "notenv-stable-admission" and admission["values_returned"] is False
    run("cosign", "verify-blob", "--bundle", str(feed / "admission.sigstore.json"),
        "--certificate-identity", IDENTITY,
        "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
        "--certificate-github-workflow-sha", admission["publisher_commit"], str(feed / "admission.json"))
    for name, expected in admission["files"].items():
        if name != "metadata/timestamp.json":
            assert digest(safe_file(feed, name)) == expected
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = json_file(feed / "metadata/timestamp.json")["signed"]
    snapshot = json_file(feed / f'metadata/{timestamp["meta"]["snapshot.json"]["version"]}.snapshot.json')["signed"]
    targets = json_file(feed / f'metadata/{snapshot["meta"]["targets.json"]["version"]}.targets.json')["signed"]
    for role in (timestamp, snapshot, targets):
        assert datetime.datetime.fromisoformat(role["expires"].replace("Z", "+00:00")) > now, "expired-feed-needs-release-authority"
    original_targets = [name for name in admission["files"] if name.endswith(".targets.json")]
    assert len(original_targets) == 1
    original = json_file(safe_file(feed, original_targets[0]))["signed"]
    assert not targets["targets"] or targets["targets"] == original["targets"], "renewal-cannot-change-admission"
    for field in ("sequence", "version", "descriptor_sha256"):
        assert targets["notenv"][field] == original["notenv"][field]
    inputs = root / "inputs"
    inputs.mkdir(mode=0o700)

    def target(name):
        entry = targets["targets"][name]
        path = Path(name)
        value = safe_file(feed / "targets", str(path.parent / (entry["hashes"]["sha256"] + "." + path.name)))
        assert value.stat().st_size == entry["length"] and digest(value) == entry["hashes"]["sha256"]
        return value

    request = {"operation": "withdraw"}
    if "notenv/stable.json" in targets["targets"]:
        descriptor = json_file(target("notenv/stable.json"))
        # Expiring acceptance withdraws the channel; it is never extended here.
        alive = all(datetime.datetime.fromisoformat(json_file(target(a["acceptance"]["target"]))["expires_at"].replace("Z", "+00:00")) > now + datetime.timedelta(minutes=5) for a in descriptor["artifacts"])
        if alive:
            shutil.copyfile(target("notenv/stable.json"), inputs / "descriptor.json")
            request = {"operation": "admit", "descriptor": "descriptor.json", "publication": "publication.json", "signature": "publication.sigstore.json", "platforms": []}
            for field in ("publication", "signature"):
                shutil.copyfile(target(descriptor[field]["target"]), inputs / request[field])
            for artifact in descriptor["artifacts"]:
                platform = artifact["platform"]
                prefix = f'releases/{descriptor["version"]}/{platform}'
                evidence = target(prefix + ".evidence.json")
                entry = {"archive": platform + ".tar.gz", "evidence": platform + ".json", "evidence_signature": platform + ".sigstore.json", "evidence_commit": json_file(evidence)["workflow_commit"]}
                for field, value in (("archive", target(artifact["target"])), ("evidence", evidence), ("evidence_signature", target(prefix + ".evidence.sigstore.json"))):
                    shutil.copyfile(value, inputs / entry[field])
                request["platforms"].append(entry)
    (inputs / "request.json").write_text(json.dumps(request))
    (root / "base.json").write_text(json.dumps({"commit": base, "operation": request["operation"]}))


def sign_and_publish(root):
    base = json_file(root / "base.json")
    source, feed = root / "notenv-public-source", root / "feed"
    material = os.environ.pop("NOTENV_TUF_ONLINE_KEYS")
    run("pnpm", "exec", "tsx", "scripts/publish-stable-machine-update.ts",
        str((root / "inputs/request.json").resolve()), str(feed.resolve()), str((root / "prepared").resolve()),
        input=material.encode(), cwd=source)
    del material
    for path in (root / "prepared").rglob("*"):
        if path.is_file():
            destination = feed / path.relative_to(root / "prepared")
            if destination.exists() and destination.name != "timestamp.json":
                assert destination.read_bytes() == path.read_bytes(), "immutable-metadata-conflict"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    receipt = {"schema_version": 1, "kind": "notenv-stable-renewal", "previous_public_commit": base["commit"],
        "operation": base["operation"], "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "timestamp_sha256": digest(feed / "metadata/timestamp.json"), "daily_installation_changed": False, "production_deployed": False, "values_returned": False}
    (feed / "renewal.json").write_text(json.dumps(receipt, sort_keys=True))
    run("git", "-C", str(feed), "add", "metadata", "renewal.json", *(["targets"] if (feed / "targets").exists() else []))
    run("git", "-C", str(feed), "-c", "user.name=CTX9 Release", "-c", "user.email=release@users.noreply.github.com", "commit", "-m", "chore(notenv): renew admitted stable metadata")
    auth = base64.b64encode(("x-access-token:" + os.environ.pop("GITHUB_TOKEN")).encode()).decode()
    environment = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + auth}
    run("git", "-C", str(feed), "push", "origin", "HEAD:refs/heads/notenv-stable", env=environment)
    print(json.dumps(receipt))


if __name__ == "__main__":
    import sys
    assert sys.argv[1] in ("prepare", "publish") and len(sys.argv) == 2
    selected = Path("build/notenv-stable-renewal").resolve()
    (prepare if sys.argv[1] == "prepare" else sign_and_publish)(selected)
