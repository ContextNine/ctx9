# CTX9

`ctx9` is the public installer and discovery surface for independently released Context Nine tools. It downloads exact component releases, verifies their pinned SHA-256 digests, and delegates installation and health checks to each component's own installer.

The launcher does not require the Context Vault, a CTX9 workspace checkout, or private infrastructure.

## Install

Download the release archive and checksum from [GitHub Releases](https://github.com/ContextNine/ctx9/releases), verify them, extract the archive, then run:

```bash
python3 ctx9-0.3.22/scripts/install.py
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
ctx9 install testimonials
ctx9 install fleet
ctx9 install vault
ctx9 update
ctx9 doctor
```

`components.json` is the release catalog. Every component remains independently versioned and owns its installer and doctor. `ctx9 update` installs the exact component versions approved by the installed launcher catalog; updating the launcher provides a newer catalog.

On an enrolled fleet machine, `ctx9 list` also discovers Secret Bindings from the exact private dependency registry. `ctx9 auth` keeps its read-only GitLab credential in an internal helper, and `ctx9 install secret-bindings` authenticates transparently. The public catalog never gains private repository metadata. See [the release contract](docs/release-and-components.md).

The catalog includes Fleet, Context Vault, [Codex Repo Sync](https://github.com/ContextNine/codex-repo-sync), [CodeFolderSync](https://github.com/ContextNine/codefoldersync), the dependency-free [Publisher CLI](https://github.com/ContextNine/publisher), and the source-stamped Testimonials management CLI. The commands have distinct jobs: `ctx9` manages components on one machine, `fleet` converges approved state across machines, and `vault` manages Vault content and upgrades.

See [`docs/release-and-components.md`](docs/release-and-components.md) for the integrity and publication contract.
