# Notenv stable feed hosting

The public data branch `notenv-stable` hosts Notenv's consistent signed metadata
and hash-prefixed targets at
`https://raw.githubusercontent.com/ContextNine/ctx9/notenv-stable/`.
It is separate from the launcher catalog and does not select a daily version.
Force pushes and branch deletion are disabled.

New admission belongs to Notenv's protected stable publisher. Hosting verifies
its original keyless signed `admission.json`, exact immutable files and public
base before publication. A normal Git push publishes one complete generation.
On an uncertain push outcome, reconcile the remote commit before retrying.

`Renew admitted Notenv stable feed` runs at 00:17 and 12:17 UTC, or manually.
Its master-only `notenv-stable` environment holds only the existing online TUF
key, transferred using that environment's GitHub public encryption key. Notenv
retains root custody. Neither key appears in Git or release artifacts.

Renewal runs the publisher from the pinned corresponding-source archive of
official Notenv 4.0.1. It verifies the original admission, preserves its exact
descriptor, original official signatures and installed evidence, and rechecks
acceptance expiry. It cannot select new release bytes. Expiring acceptance
withdraws discovery without resetting the signed sequence/version high water.
An already expired or invalid feed fails for protected operator recovery.
No Actions artifact storage or new hosting service is used.

The workflow authenticates only its own public repository push. The feed branch
contains data, never executable workflow source. Root rotation or publisher
changes require a reviewed source change. The installed machine updater remains
owned by Notenv; server maintenance and Delivery/Platform are separate.

## Verified admission and renewal

The feed admits [official Notenv 4.0.4](https://github.com/ContextNine/ctx9/releases/tag/notenv-v4.0.4)
for Linux x64 and macOS arm64, from immutable application source
`729f5db99d039993fe37ec0c2555c69725ad8043`. Protected Notenv admission run
`40245527495` verifies the original official artifacts and both separately signed
native installed records from the complete successful run `40245002065`.
The signed prepared tree was published from its exact expected public base at
commit `792d7a77108aac1d2f174d2e14eece69c2ab72eb`.

[Renewal run 40245715038](https://github.com/ContextNine/ctx9/actions/runs/40245715038)
publishes generation 4 at commit `30de046540e0babeacd0045d1c42e2260f89438e`,
preserving descriptor sequence 1 and all original release/acceptance bytes.
Client read-back using the independently provisioned production bootstrap
accepts generation 4 and the same release. An isolated copy of those signed
bytes also refuses the prior signed generation and an altered signature body.
[Evidence](evidence/notenv-stable-hosting-2026-10-26.json) records the digests.

Native acceptance expires on November 24, 2026 at 23:34:22 UTC at the earliest.
Notenv must repeat actual native acceptance and admit its new evidence at a higher
descriptor sequence before then. Hosting renews metadata, never acceptance.
No launcher catalog pin, daily installation, Fleet desired version or managed
production deployment changed. Independent server updates remain outside this
machine feed.
