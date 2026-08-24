# Repository instructions

This repository owns the public `ctx9` component launcher and its signed-off component catalog.

- Keep the launcher thin. Components own their installers, doctors, release cadence, and runtime behavior.
- Use only Python's standard library so a fresh macOS or Linux machine can run the release installer.
- Pin every component artifact by exact version, URL, and SHA-256 in `components.json`.
- Never add a private repository, personal path, credential, or workspace dependency to the public catalog.
- `ctx9` is the umbrella command. Component repositories own distinct commands and capabilities; never recreate their implementations here.
- Publishing a component requires clean release artifacts plus fresh macOS and Linux acceptance where supported.
- Repository-specific documentation lives in `docs/`. Update it with catalog, installer, integrity, release, or verification changes and keep `docs/README.md` current.
