# Release and component contract

The installed launcher contains one immutable `components.json` catalog. Updating a component means installing the exact release named by that catalog; updating the launcher is how a user receives a newer approved catalog.

Each component entry must contain:

- one stable component ID and display name;
- exact version and release tag;
- public archive URL and pinned SHA-256, or an exact artifact for each supported native host;
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

## Public native archives

Portable components use one archive. Native components use `release.artifacts` to select one archive by the exact operating-system/architecture pair, using the same selection as private native components. A supported operating system and a supported architecture do not imply every combination is available. A missing pair stops before download.

A public native release declares:

- `repository` as its public GitHub `owner/repository`, with `tag` equal to `v<component version>` or `<component ID>-v<component version>` for shared release hosting;
- a full `source_commit` and `minimum_launcher_version` naming an accepted launcher release with this capability;
- `artifacts` containing `platform`, `architecture`, `archive_url`, `archive_sha256` and `archive_root` for each available host pair.

Each URL must name a credential-free HTTPS asset under that repository's exact versioned GitHub release. Query strings, fragments and duplicate host pairs are rejected. Artifact support must fit the component's declared platforms and architectures. Native entries do not also declare a portable archive. Download, checksum verification, safe extraction and the component-owned installer remain the installation path. Public native downloads never request private headers or the private credential helper.

Before moving Notenv into the public catalog, complete its anonymous signed-artifact and clean-machine acceptance. Retire its private Fleet recipe/overlay entry as part of the coordinated migration, preserving unrelated private components. Private catalogs still cannot replace a public component. Source capability alone does not authorize adding an unaccepted artifact to `components.json`.

Launcher 0.4.4 admits the original Notenv 3.0.0 archives from public
`notenv-v3.0.0` hosting. Anonymous downloads, original signatures, temporary
installation/doctor/repeat and exact CLI identity pass on all three fleet machines.
The actual published Linux archive also passes enrollment, protected execution,
restart and restored-server execution in hosted run `39307686536`. Public
attestations bind all eight release files to the reviewed hosting workflow.
See the [acceptance receipt](evidence/notenv-public-3.0.0-2026-10-19.json).
This is catalog admission, not stable auto-update eligibility, production or
daily machine adoption. Mac native replacement and service/consumer checks
remain explicit cutover gates. Newer Notenv 4.0.0 source is not included.

The official Launcher 0.4.4 release now passes its exact tag/source/workflow
attestation checks for all three files. Independent anonymous Linux and macOS
downloads match archive `4f81b988...386472d` and pass temporary fresh installation,
doctor, repeat no-op and installed public Notenv catalog checks. Mattbook is
offline, so primary-owned adoption and its target acceptance remain pending.
See the [official release receipt](evidence/launcher-0.4.4-2026-10-19.json).

The original source acceptance passed all 14 launcher tests in [hosted Test run 39006140517](https://github.com/ContextNine/ctx9/actions/runs/39006140517) at exact source `5e979f2b7466b77ec2a2dd04ad639fe6dfdb7281`. The integration journey executes selected synthetic macOS/Linux archive installers, confirms anonymous requests, and denies an unsupported pair and tampered archive before installer execution. Launcher 0.4.2 now publishes this capability and is adopted on all three registered machines, with [official-download and installed-byte acceptance](evidence/launcher-0.4.2-2026-10-18.json). Actual public Notenv native downloads and their installed custody remain separate gates; no Notenv public catalog entry is added.

Shared public hosting uses the component-specific `notenv-v<version>` release,
separate from launcher version tags. Publish original signed platform archives,
their checksums, the original record/bundle and reviewed corresponding source.
Do not publish private Git history, custody, retained operation ZIPs or the raw
private image-source archive. Download consumers need no GitHub or GitLab login.
The manual native-download attestation workflow anonymously downloads and verifies
the original signature, source/version and reviewed source digest before issuing
additional public GitHub attestations. It cannot publish assets, deploy or update
a machine. Preview publication does not admit a component to the public catalog
or stable updates.

## Private catalog overlay

Private products use a separate value-free catalog with `catalog_kind: private-overlay` and the exact
`ctx9-gitlab-group-read` credential binding. The public catalog remains unchanged. Enrolled fleet machines
discover the catalog from their exact dependency registry and expose the narrow credential only to `ctx9`:

```bash
ctx9 auth verify --json
ctx9 list
ctx9 install private-product
```

Each private release entry must name an exact source commit, minimum launcher version, and one checksummed
archive for every supported platform/architecture pair. Private URLs must be exact credential-free GitLab
Generic Package HTTPS URLs. Redirects and query strings are rejected before credential forwarding. The launcher
rejects missing native credentials, duplicate public IDs, mutable-only identities, incomplete host artifacts,
and checksum mismatches. It never stores a header, token, or authenticated URL. Component-owned installers
remain responsible for atomic activation, status, rollback, and uninstall.

### Authenticated release preflight

The 0.4 series adds `ctx9 preflight <component> --json` and explicit private release trust policy.
It is not in the released 0.3.24 archive. Version 0.4.1 discovers the enrolled dependency registry at
`~/.agents/internal/defaults/dependencies.json`. Publish and accept it before enrolling Fleet in this contract.
Do not replace an installed launcher with this checkout or assume the source version string proves the
capability is installed.

Private recipes must pin `provenance_provider` and `provenance_project`, alongside the exact catalog URL,
`ctx9-gitlab-group-read` binding and `verify.exact` semantic version. Storage and signing are independent:
GitLab Generic Packages can hold a release signed by the configured GitHub workflow.

- `provenance_provider: gitlab` derives the exact `.gitlab-ci.yml@refs/tags/v<version>` certificate identity
  and `https://gitlab.com` issuer. This explicitly selects a retained GitLab release, without fallback.
- `provenance_provider: github` requires an owner/repository project and `provenance_workflow`, such as
  `.github/workflows/publish-machine-release.yml@refs/heads/master`. The identity is that exact repository,
  workflow and ref, with issuer `https://token.actions.githubusercontent.com`. The signed record's
  publication fields must match the enrolled policy. Cosign must also bind its claimed publisher commit
  to the certificate's workflow SHA, independently of the application's source commit.

Missing or ambiguous policy fails closed. A failed issuer never selects the other provider. The downloaded
catalog cannot choose a signer. Fleet passes the same policy explicitly to preflight and installation.
An existing recipe needs an explicit provider before adopting this contract; no implicit GitLab default
or source CLI fallback is provided. These settings do not change its selected component version.

The launcher delegates cryptography to an enrolled `cosign` executable using
[`verify-blob`, exact certificate identity and issuer](https://docs.sigstore.dev/cosign/verifying/verify/).
The launcher itself still uses only Python's standard library. Cosign installation/version acceptance is a
separate dependency gate, not an automatic download or a cryptographic implementation inside the launcher.
The 0.4.2 verifier gate requires Cosign 3.1.3 or newer and rejects older binaries before reading signed
records. This covers the upstream [legacy-bundle identity-bypass advisory](https://github.com/sigstore/cosign/security/advisories/GHSA-fx35-mq7g-6g98).
No verifier means `verifier-unavailable`, never a checksum-only fallback. The verifier child does not receive
private-read or management credentials, and its raw output is not printed.
Private component installers also do not inherit download, management or CI signing credentials. They retain
only public runtime, home/XDG and native-session settings needed for their own installation and custody.

Preflight reads the exact catalog, signed release JSON and bundle. It verifies the bundle, the complete
catalog's equality to the signed catalog, source/version/product identity, host eligibility and the signed
platform/archive digest set. It does not install or run a component. `archive_verified: false` is deliberate:
archive bytes are downloaded and checksum-verified immediately before extraction and installer execution.
Installation, doctor, rollback and uninstall all repeat the trust check before running release-owned code.
Private installer output is reduced to readiness/change booleans rather than forwarding arbitrary output.

The ready report includes the full `source_commit` and `catalog_sha256`, a SHA-256 of the complete
verified catalog encoded as sorted-key, compact JSON. This digest covers release metadata only, including
archive URLs, hashes and installer policy. Fleet passes `--expected-source-commit` and
`--expected-catalog-sha256` from its accepted preflight to later operations. Either mismatch returns
`release-changed` before downloading or executing an installer, even when the new catalog has a valid
signature and the same version. Malformed pins are rejected, not ignored. These pins do not replace
signature verification or archive-byte checks.

Closed failure states distinguish missing/locked/expired native access, rejected credentials, denied access,
missing release, rate limiting, transport failure, incompatible host, invalid release, missing local trust
policy, missing verifier and rejected trust. A 401 proves rejected credentials, not whether they were revoked
or mistyped. Do not rotate based on that status alone. Metadata reads and verifier execution are bounded;
no provider response body, traceback, header or key is included in the report.

Acceptance must use the real signed release and real accepted Cosign on both supported OS families. The
synthetic integration fixture proves orchestration, matching and fail-closed behavior, not cryptography or
live credential custody. Until that acceptance, do not claim the new installation workflow is shipped.

The hosted `Test` workflow separately installs the built launcher archive into isolated paths on both
macOS and Linux. It signs synthetic component metadata using real GitHub Sigstore, then the installed
launcher verifies the actual bundle and exercises pinned install, doctor and no-op installation. Wrong
issuer and tampered-record checks use that same real signature. Retained receipts distinguish this real
cryptographic check from its synthetic transport/component and unverified native custody. It never changes
a daily installation or contacts a real private package endpoint. Official release downloads and actual
Notenv/native custody still need their own acceptance.

## Fleet 0.2.18 catalog selection

Launcher 0.4.2 selects Fleet CLI 0.2.18 from the official Skill Problem System
0.3.2 source release. The component and source-product version numbers are
independent. Its archive has no enclosing directory, so the public catalog
selects `archive_root: "."`; it contains only regular files and directories.
The original published bytes, exact tag/source/workflow attestation and isolated
installation, doctor and repeat runtime-upgrade pass on Linux and macOS. Source
ownership and configuration remain unchanged during the repeat upgrade. See the
[receipt](evidence/fleet-0.2.18-2026-10-18.json). Launcher 0.4.2's official
download passes isolated acceptance on all three machines. Normal primary-owned
Fleet updates adopt both releases; installed launcher runtime/catalog files and
all 33 Fleet runtime files match the official archives on each machine, and
Fleet doctors pass. The [adoption receipt](evidence/launcher-0.4.2-2026-10-18.json)
records the updater's stale final-report limitation. This does not accept or
adopt a new Notenv native release.

## Fleet 0.2.19 catalog selection

Launcher 0.4.3 selects Fleet 0.2.19 from Skill Problem System v0.3.3,
source `6bce4b5d6199665d85950f23ef51b67b201901f2`. Fleet can select an explicit
new signing policy in the same exact-version adoption transaction, without
temporarily changing the policy for the retained old version. The public
component/archive format and existing private Notenv overlay remain unchanged.

The three official Fleet release files pass exact source/tag/workflow GitHub
attestation verification. Anonymous Linux download and the independent Mac
download have the same pinned archive hash. Its existing fresh-install,
verification, repeated-install, runtime-upgrade and uninstall journeys pass
against those extracted official bytes on both operating systems. One
starter-registry worker case remains its configured skip on each OS. See the
[receipt](evidence/fleet-0.2.19-2026-10-19.json).

Launcher 0.4.3 is published. Its official archive, checksum and source record
pass exact tag/source/workflow attestation verification. Anonymous independent
Linux and macOS downloads have identical bytes and pass fresh installation,
verification and repeat-install no-op. Mattbook's SSH connection times out before
its own check. Canonical desired pins are saved, but primary visibility, Vault
Git completion and primary-owned Fleet adoption remain pending. See the
[Launcher receipt](evidence/launcher-0.4.3-2026-10-19.json). Neither this
publication nor its isolated acceptance installs or adopts Notenv 3.0.0.
