#!/usr/bin/env python3
"""Build a deterministic, link-free component archive from one Git ref."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


def git(source: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(source), *arguments])


def entries(source: Path, ref: str) -> list[tuple[str, str, str]]:
    records = git(source, "ls-tree", "-r", "-z", "--full-tree", ref).split(b"\0")
    result: list[tuple[str, str, str]] = []
    for record in records:
        if not record:
            continue
        metadata, encoded_path = record.split(b"\t", 1)
        mode, kind, _object_id = metadata.decode().split()
        if kind != "blob":
            raise RuntimeError(f"unsupported Git entry: {encoded_path.decode()}")
        result.append((mode, kind, encoded_path.decode()))
    return result


def normalized_link(path: str, target: str) -> str:
    candidate = PurePosixPath(path).parent / PurePosixPath(target)
    parts: list[str] = []
    if candidate.is_absolute():
        raise RuntimeError(f"absolute archive link is not allowed: {path}")
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise RuntimeError(f"archive link escapes the repository: {path}")
            parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts).as_posix()


def blob(source: Path, ref: str, path: str, mode: str, modes: dict[str, str]) -> tuple[bytes, int]:
    contents = git(source, "show", f"{ref}:{path}")
    if mode != "120000":
        return contents, 0o755 if mode == "100755" else 0o644
    target = normalized_link(path, contents.decode().strip())
    target_mode = modes.get(target)
    if target_mode is None or target_mode == "120000":
        raise RuntimeError(f"archive link target must be one regular tracked file: {path}")
    return git(source, "show", f"{ref}:{target}"), 0o755 if target_mode == "100755" else 0o644


def build(source: Path, ref: str, root_name: str, output: Path) -> str:
    tracked = entries(source, ref)
    modes = {path: mode for mode, _kind, path in tracked}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for mode, _kind, path in tracked:
            contents, permissions = blob(source, ref, path, mode, modes)
            info = tarfile.TarInfo(f"{root_name}/{path}")
            info.size = len(contents)
            info.mode = permissions
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(contents))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed:
            compressed.write(buffer.getvalue())
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--root-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(build(arguments.source.resolve(), arguments.ref, arguments.root_name, arguments.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
