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
