# CTX9

`ctx9` is the public installer and discovery surface for independently released Context Nine tools. It downloads exact component releases, verifies their pinned SHA-256 digests, and delegates installation and health checks to each component's own installer.

The launcher does not require the Context Vault, a CTX9 workspace checkout, or private infrastructure.

## Install

Download the release archive and checksum from [GitHub Releases](https://github.com/MDerman/ctx9/releases), verify them, extract the archive, then run:

```bash
python3 ctx9-0.2.1/scripts/install.py
ctx9 --version
ctx9 list
```

The default locations are `~/.local/bin/ctx9` and `~/.local/share/ctx9`. Use `--install-dir` and `--data-dir` when another prefix is required.
The installed entrypoint prefers the fleet-managed Homebrew Python 3.12 runtime on macOS, then uses `python3` on other supported systems. This avoids accidentally invoking Apple's Xcode-gated Python shim from a non-login service or SSH session.

## Components

```bash
ctx9 list
ctx9 install codex-repo-sync
ctx9 install codefoldersync
ctx9 install publisher
ctx9 update
ctx9 doctor
```

`components.json` is the release catalog. Every component remains independently versioned and owns its installer and doctor. `ctx9 update` installs the exact component versions approved by the installed launcher catalog; updating the launcher provides a newer catalog.

Private components use a separate authenticated, value-free catalog overlay. The launcher accepts it only
when invoked through the narrow `ctx9-gitlab-read` credential boundary, verifies an exact host archive and
checksum, and leaves installation, rollback, and uninstall to the component. The public catalog never gains
private repository metadata. See [the release contract](docs/release-and-components.md).

The catalog currently includes [Codex Repo Sync](https://github.com/MDerman/codex-repo-sync), [CodeFolderSync](https://github.com/MDerman/codefoldersync), and the dependency-free [Publisher CLI](https://github.com/MDerman/publisher). Publisher provides one `publish` command for documents, files, and evidence. Each component remains independently versioned and released.

See [`docs/release-and-components.md`](docs/release-and-components.md) for the integrity and publication contract.
