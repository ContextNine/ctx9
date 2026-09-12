# Release and component contract

The installed launcher contains one immutable `components.json` catalog. Updating a component means installing the exact release named by that catalog; updating the launcher is how a user receives a newer approved catalog.

Each component entry must contain:

- one stable component ID and display name;
- exact version and release tag;
- public archive URL and pinned SHA-256;
- archive root and component-owned installer path;
- supported operating systems and architectures;
- install and doctor arguments accepted by the release installer;
- provided command or capability identities;
- public documentation URL.

The launcher verifies host eligibility and archive integrity before extracting. Archives containing absolute paths, parent traversal, symbolic links, or hard links are rejected. The component installer must return JSON with `ready: true`; it remains authoritative for installation, idempotence, local custody, and verification.

Before adding or updating a catalog entry:

1. publish the component from clean `master` with focused tests and release automation passing;
2. verify its release archive and checksum;
3. prove fresh installation, doctor, and second-run no-op on every claimed operating system;
4. update the pinned component entry and launcher tests;
5. publish a new launcher release and repeat fresh launcher acceptance.

The catalog may not reference private repositories, workspace paths, credentials, production deployment, or mutable branch archives.

When a public CLI is built from a private service repository, publish only its deterministic, source-stamped archive and checksum as assets on the public launcher release. The catalog points to that public asset and the component installer verifies its embedded source commit; the private service source and release credentials remain private.

## Private catalog overlay

Private products use a separate value-free catalog with `catalog_kind: private-overlay` and the exact
`ctx9-gitlab-group-read` credential binding. The public catalog remains unchanged. Enrolled fleet machines
discover the catalog from their exact dependency registry and expose the narrow credential only to `ctx9`:

```bash
ctx9 auth verify --json
ctx9 list
ctx9 install secret-bindings
```

Each private release entry must name an exact source commit, minimum launcher version, and one checksummed
archive for every supported platform/architecture pair. URLs must be credential-free HTTPS. The launcher
rejects missing native credentials, duplicate public IDs, mutable-only identities, incomplete host artifacts,
and checksum mismatches. It never stores a header, token, or authenticated URL. Component-owned installers
remain responsible for atomic activation, status, rollback, and uninstall.
