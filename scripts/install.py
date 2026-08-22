#!/usr/bin/env python3
"""Install the ctx9 launcher without third-party dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

VERSION = "0.1.1"


def source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    data_dir = args.data_dir.expanduser().resolve()
    executable = data_dir / "src" / "ctx9.py"
    manifest = data_dir / "components.json"
    link = args.install_dir.expanduser().resolve() / "ctx9"
    return executable, manifest, link


def report(args: argparse.Namespace, ready: bool, changed: bool, errors: list[str]) -> int:
    executable, manifest, link = paths(args)
    value = {
        "component": "ctx9",
        "version": VERSION,
        "ready": ready,
        "changed": changed,
        "executable": str(link),
        "manifest": str(manifest),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(value, sort_keys=True))
    else:
        state = "ready" if ready else "not ready"
        print(f"ctx9 {VERSION}: {state} at {link}")
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    return 0 if ready else 1


def verify(args: argparse.Namespace) -> tuple[bool, list[str]]:
    executable, manifest, link = paths(args)
    expected_executable = source_root() / "src" / "ctx9.py"
    expected_manifest = source_root() / "components.json"
    errors: list[str] = []
    for installed, expected, label in (
        (executable, expected_executable, "launcher"),
        (manifest, expected_manifest, "component manifest"),
    ):
        if not installed.is_file():
            errors.append(f"missing {label}: {installed}")
        elif file_digest(installed) != file_digest(expected):
            errors.append(f"unexpected {label} digest: {installed}")
    if not link.is_symlink():
        errors.append(f"launcher link is missing: {link}")
    elif link.resolve() != executable:
        errors.append(f"launcher link targets {link.resolve()}, expected {executable}")
    return not errors, errors


def install(args: argparse.Namespace) -> bool:
    executable, manifest, link = paths(args)
    expected_executable = source_root() / "src" / "ctx9.py"
    expected_manifest = source_root() / "components.json"
    changed = False
    executable.parent.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    for source, destination, mode in (
        (expected_executable, executable, 0o755),
        (expected_manifest, manifest, 0o644),
    ):
        if not destination.is_file() or file_digest(destination) != file_digest(source):
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
            try:
                shutil.copyfile(source, temporary_path)
                os.chmod(temporary_path, mode)
                temporary_path.replace(destination)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()
            changed = True
    if link.exists() and not link.is_symlink():
        raise RuntimeError(f"refusing to replace non-symlink: {link}")
    if not link.is_symlink() or link.resolve() != executable:
        temporary_link = link.with_name(f".{link.name}.tmp-{os.getpid()}")
        if temporary_link.exists() or temporary_link.is_symlink():
            temporary_link.unlink()
        temporary_link.symlink_to(executable)
        temporary_link.replace(link)
        changed = True
    return changed


def parser() -> argparse.ArgumentParser:
    install_parser = argparse.ArgumentParser()
    install_parser.add_argument("--version", action="version", version=VERSION)
    install_parser.add_argument(
        "--install-dir", type=Path, default=Path.home() / ".local" / "bin"
    )
    install_parser.add_argument(
        "--data-dir", type=Path, default=Path.home() / ".local" / "share" / "ctx9"
    )
    install_parser.add_argument("--verify", action="store_true")
    install_parser.add_argument("--json", action="store_true")
    return install_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        changed = False if args.verify else install(args)
        ready, errors = verify(args)
        return report(args, ready, changed, errors)
    except (OSError, RuntimeError) as error:
        return report(args, False, False, [str(error)])


if __name__ == "__main__":
    raise SystemExit(main())
