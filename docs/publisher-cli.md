# Publisher CLI lifecycle

Launcher installs one `publish` command from the Publisher repository's reproducible `v3.1.0` archive. The catalog pins its URL and SHA-256. Publisher owns credential custody, doctor, API behavior, installation, verification, and uninstall.

Acceptance is:

```bash
ctx9 install publisher
ctx9 doctor publisher
publish --version
ctx9 uninstall publisher
```

The former File Upload and Artifacts CLI components are not aliases or independent catalog entries. Their repositories and old data remain intact until the separately approved production cutover and retirement steps.
