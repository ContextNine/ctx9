from __future__ import annotations

import importlib.util
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/build_component_asset.py"
SPEC = importlib.util.spec_from_file_location("build_component_asset", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComponentAssetTests(unittest.TestCase):
    def test_archive_is_deterministic_and_materializes_safe_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", source], check=True)
            subprocess.run(["git", "-C", source, "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", source, "config", "user.email", "test@example.com"], check=True)
            (source / "AGENTS.md").write_text("instructions\n", encoding="utf-8")
            (source / "CLAUDE.md").symlink_to("AGENTS.md")
            subprocess.run(["git", "-C", source, "add", "-A"], check=True)
            subprocess.run(["git", "-C", source, "commit", "-qm", "fixture"], check=True)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            first_digest = MODULE.build(source, "HEAD", "component-1.0.0", first)
            second_digest = MODULE.build(source, "HEAD", "component-1.0.0", second)
            self.assertEqual(first_digest, second_digest)
            with tarfile.open(first, "r:gz") as archive:
                linked = archive.getmember("component-1.0.0/CLAUDE.md")
                self.assertTrue(linked.isfile())
                self.assertEqual(archive.extractfile(linked).read(), b"instructions\n")


if __name__ == "__main__":
    unittest.main()
