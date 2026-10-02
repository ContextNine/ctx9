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
2. verify its release archive, checksum, source-commit release record, and GitHub attestation;
3. prove fresh installation, doctor, and second-run no-op on every claimed operating system;
4. update the pinned component entry and launcher tests;
5. publish a new launcher release and repeat fresh launcher acceptance.

The catalog may not reference private repositories, workspace paths, credentials, production deployment, or mutable branch archives.

When a public CLI is built from a private service repository, publish only its deterministic, source-stamped archive and checksum as assets on the public launcher release. The catalog points to that public asset and the component installer verifies its embedded source commit; the private service source and release credentials remain private.

Testimonials follows this boundary. Its public `testimonials-<version>.tar.gz` contains only the bundled CLI, native credential helper, installer, public README and exact source commit marker. The service source, environment contracts and production configuration are excluded.

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
archive for every supported platform/architecture pair. Private URLs must be exact credential-free GitLab
Generic Package HTTPS URLs. Redirects and query strings are rejected before credential forwarding. The launcher
rejects missing native credentials, duplicate public IDs, mutable-only identities, incomplete host artifacts,
and checksum mismatches. It never stores a header, token, or authenticated URL. Component-owned installers
remain responsible for atomic activation, status, rollback, and uninstall.

### Authenticated release preflight

The source implementation adds `ctx9 preflight <component> --json`. It is not in the released 0.3.24 archive.
Publish and accept a new launcher release before enrolling Fleet in this command. Do not replace an installed
launcher with this checkout or assume the source version string proves the capability is installed.

Private recipes must pin `provenance_project`, such as the component's GitLab namespace/project, alongside
the exact catalog URL, `ctx9-gitlab-group-read` binding and `verify.exact` semantic version. The launcher
derives the exact `.gitlab-ci.yml@refs/tags/v<version>` certificate identity from this local policy, with
`https://gitlab.com` as issuer. It never trusts a signer selected by the downloaded catalog. Fleet passes
the same policy explicitly to preflight and installation.

The launcher delegates cryptography to an enrolled `cosign` executable using
[`verify-blob`, exact certificate identity and issuer](https://docs.sigstore.dev/cosign/verifying/verify/).
The launcher itself still uses only Python's standard library. Cosign installation/version acceptance is a
separate dependency gate, not an automatic download or a cryptographic implementation inside the launcher.
No verifier means `verifier-unavailable`, never a checksum-only fallback. The verifier child does not receive
private-read or management credentials, and its raw output is not printed.

Preflight reads the exact catalog, signed release JSON and bundle. It verifies the bundle, the complete
catalog's equality to the signed catalog, source/version/product identity, host eligibility and the signed
platform/archive digest set. It does not install or run a component. `archive_verified: false` is deliberate:
archive bytes are downloaded and checksum-verified immediately before extraction and installer execution.
Installation, doctor, rollback and uninstall all repeat the trust check before running release-owned code.
Private installer output is reduced to readiness/change booleans rather than forwarding arbitrary output.

Closed failure states distinguish missing/locked/expired native access, rejected credentials, denied access,
missing release, rate limiting, transport failure, incompatible host, invalid release, missing local trust
policy, missing verifier and rejected trust. A 401 proves rejected credentials, not whether they were revoked
or mistyped. Do not rotate based on that status alone. Metadata reads and verifier execution are bounded;
no provider response body, traceback, header or key is included in the report.

Acceptance must use the real signed release and real accepted Cosign on both supported OS families. The
synthetic integration fixture proves orchestration, matching and fail-closed behavior, not cryptography or
live credential custody. Until that acceptance, do not claim the new installation workflow is shipped.
