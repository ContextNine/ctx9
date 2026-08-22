# CTX9

`ctx9` is the public installer and discovery surface for independently released Context Nine tools. It downloads exact component releases, verifies their pinned SHA-256 digests, and delegates installation and health checks to each component's own installer.

The launcher does not require the Context Vault, a CTX9 workspace checkout, or private infrastructure.

## Install

Download the release archive and checksum from [GitHub Releases](https://github.com/MDerman/ctx9/releases), verify them, extract the archive, then run:

```bash
python3 ctx9-0.1.1/scripts/install.py
ctx9 --version
ctx9 list
```

The default locations are `~/.local/bin/ctx9` and `~/.local/share/ctx9`. Use `--install-dir` and `--data-dir` when another prefix is required.

## Components

```bash
ctx9 list
ctx9 install codex-repo-sync
ctx9 install codefoldersync
ctx9 update
ctx9 doctor
```

`components.json` is the release catalog. Every component remains independently versioned and owns its installer and doctor. `ctx9 update` installs the exact component versions approved by the installed launcher catalog; updating the launcher provides a newer catalog.

The initial components are [Codex Repo Sync](https://github.com/MDerman/codex-repo-sync), a public Codex plugin for repository configuration synchronization, and [CodeFolderSync](https://github.com/MDerman/codefoldersync), a peer-to-hub Code workspace synchronizer.

See [.docs/release-and-components.md](.docs/release-and-components.md) for the integrity and publication contract.
