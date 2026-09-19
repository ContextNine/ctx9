#!/usr/bin/env python3
"""Install the ctx9 launcher without third-party dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

VERSION = "0.3.18"


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


def launcher_script(executable: Path) -> bytes:
    quoted_executable = shlex.quote(str(executable))
    return (
        "#!/bin/sh\n"
        "# Managed by the CTX9 launcher.\n"
        "set -eu\n"
        "for interpreter in "
        '"/opt/homebrew/opt/python@3.12/libexec/bin/python3" '
        '"/usr/local/opt/python@3.12/libexec/bin/python3"; do\n'
        '  if [ -x "$interpreter" ]; then\n'
        f'    exec "$interpreter" {quoted_executable} "$@"\n'
        "  fi\n"
        "done\n"
        f"exec python3 {quoted_executable} \"$@\"\n"
    ).encode("utf-8")


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
    if not link.is_file() or link.is_symlink():
        errors.append(f"launcher entrypoint is missing: {link}")
    elif link.read_bytes() != launcher_script(executable):
        errors.append(f"unexpected launcher entrypoint digest: {link}")
    elif not os.access(link, os.X_OK):
        errors.append(f"launcher entrypoint is not executable: {link}")
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
    expected_entrypoint = launcher_script(executable)
    if link.is_symlink() and link.resolve() != executable:
        raise RuntimeError(f"refusing to replace unrelated symlink: {link}")
    if link.is_file() and not link.is_symlink():
        current_entrypoint = link.read_bytes()
        if (
            current_entrypoint != expected_entrypoint
            and not current_entrypoint.startswith(b"#!/bin/sh\n# Managed by the CTX9 launcher.\n")
        ):
            raise RuntimeError(f"refusing to replace unrelated command: {link}")
    if link.is_symlink() or not link.is_file() or link.read_bytes() != expected_entrypoint:
        with tempfile.NamedTemporaryFile(dir=link.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(expected_entrypoint)
        os.chmod(temporary_path, 0o755)
        temporary_path.replace(link)
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
